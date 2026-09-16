"""
run_backtest_sp500.py — S&P 500 comparison backtest runner.

Same strategy, same parameters, same filters — only the universe changes.
Key differences from run_backtest.py:
  - Imports SP500_TICKERS (no .CA suffix)
  - Monkey-patches catalyst_check → always NEUTRAL (no Gemini API calls)
  - Sets MARKET_SUFFIX="" so fundamentals_fetcher queries bare US tickers
  - Outputs trade_log_sp500.csv
"""

import argparse
import csv
import datetime
import logging
import sys
import time
from pathlib import Path

import backtrader as bt
import pandas as pd
import yfinance as yf

PROJECT_DIR = Path(__file__).resolve().parent

# Action 2: every output of this runner is scoped to its market, so an EGX
# run and an S&P 500 run can never write the same file.
MARKET = "SP500"
RECEIPTS_DIR = PROJECT_DIR / f"decision_receipts_{MARKET}"

# --------------------------------------------------------------------------
# Monkey-patch catalyst_check and fetch_fundamentals BEFORE importing strategy
# --------------------------------------------------------------------------

def _stub_catalyst_check(ticker, pipeline_run_id=None, **kwargs):
    return {
        "score": "NEUTRAL",
        "source": "STUB_SP500",
        "priority_tier": "N/A",
        "pipeline_blocks_entry": False,
        "rationale": "Stubbed for S&P 500 comparison — no Gemini API calls",
        "event_description": None,
        "disclosure_category": None,
        "retry_log": [],   # MUST be a list, never None — see _update_catalyst_counters
        "error_flag": False,
        "model_call_attempted": False,
    }


import kashif_strategy
kashif_strategy.catalyst_check = _stub_catalyst_check
kashif_strategy.MARKET_SUFFIX = ""

from sp500_tickers import SP500_TICKERS
import data_persistence
from kashif_strategy import KashifStrategy
from kashif_sizer import MinerviniSizer

# --------------------------------------------------------------------------
# Date constants — identical to EGX run
# --------------------------------------------------------------------------
WARMUP_START = "2022-08-01"
IS_START = "2023-08-27"
IS_END = "2025-08-26"
VAL_START = "2025-08-27"
VAL_END = "2026-02-26"
OOS_START = "2026-02-27"
OOS_END = "2026-08-27"

PERIODS = {
    "IS":  (IS_START, IS_END),
    "VAL": (VAL_START, VAL_END),
    "OOS": (OOS_START, OOS_END),
}

MIN_VIABLE_TICKERS = 22

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
OPS_LOG_DIR = PROJECT_DIR / "daily_ops_log"
OPS_LOG_DIR.mkdir(exist_ok=True)

today_str = datetime.date.today().strftime("%Y%m%d")
ops_log_path = OPS_LOG_DIR / f"run_backtest_sp500_{today_str}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(ops_log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("run_backtest_sp500")


def parse_args():
    parser = argparse.ArgumentParser(description="Kashif S&P 500 Comparison Backtest")
    parser.add_argument(
        "period",
        choices=["IS", "VAL", "OOS"],
        help="Backtest period: IS (in-sample), VAL (validation), OOS (out-of-sample)",
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=None,
        help="Override ticker list. Default: all ~503 S&P 500.",
    )
    parser.add_argument(
        "--clear-receipts",
        action="store_true",
        default=False,
        help=("Delete all existing decision_receipts/*.jsonl before the run. "
              "Receipt files are append-mode and named by simulated date, so "
              "without this, runs interleave in the same files. Default: keep."),
    )
    return parser.parse_args()


def clear_decision_receipts(receipts_dir=None):
    """Fix 5: delete every receipt file so the run starts from a clean slate.

    Action 2: defaults to this market's OWN receipts directory, so the flag
    can never delete another market's run.
    """
    receipts_dir = Path(receipts_dir) if receipts_dir else RECEIPTS_DIR
    if not receipts_dir.exists():
        return 0
    removed = 0
    for path in receipts_dir.glob("decision_receipts_*.jsonl"):
        path.unlink()
        removed += 1
    return removed


def fetch_dual_feed(ticker, start, end):
    """
    Fetch two DataFrames for one ticker (US market — no .CA suffix):
      - adj_df: auto_adjust=True  -> adjusted OHLC
      - raw_df: auto_adjust=False -> raw Volume
    """
    try:
        adj_df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
        raw_df = yf.download(ticker, start=start, end=end, auto_adjust=False, progress=False)
    except Exception as e:
        log.warning("Download failed for %s: %s", ticker, e)
        return None

    if adj_df is None or adj_df.empty:
        return None
    if raw_df is None or raw_df.empty:
        return None

    if isinstance(adj_df.columns, pd.MultiIndex):
        adj_df.columns = adj_df.columns.get_level_values(0)
    if isinstance(raw_df.columns, pd.MultiIndex):
        raw_df.columns = raw_df.columns.get_level_values(0)

    adj_df["Volume"] = raw_df["Volume"]
    return adj_df


TRADE_LOG_FIELDS = [
    "date", "ticker", "action", "shares", "price", "commission",
    "slippage", "pnl", "portfolio_value",
    "holding_days", "exit_reason",
    "max_unrealized_gain_pct", "max_drawdown_during_hold_pct",
    "stock_return_pct", "spy_return_pct", "alpha_vs_spy_pct",
]


def write_trade_log(trades, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TRADE_LOG_FIELDS)
        writer.writeheader()
        for t in trades:
            writer.writerow({k: t.get(k, "") for k in TRADE_LOG_FIELDS})


class TradeLogger(bt.Analyzer):
    """Captures every order fill for trade_log_sp500.csv."""

    def __init__(self):
        super().__init__()
        self.trades = []

    def notify_order(self, order):
        if order.status != order.Completed:
            return
        price = order.executed.price
        size = abs(order.executed.size)
        commission = round(order.executed.comm, 4)
        self.trades.append({
            "date": str(self.strategy.datas[0].datetime.date(0)),
            "ticker": order.data._name,
            "action": "BUY" if order.isbuy() else "SELL",
            "shares": size,
            "price": round(price, 4),
            "commission": commission,
            "slippage": 0.0,
            "pnl": 0.0,
            "portfolio_value": round(self.strategy.broker.getvalue(), 2),
        })

    def notify_trade(self, trade):
        if trade.isclosed and self.trades:
            ticker = trade.data._name
            row = None
            for candidate in reversed(self.trades):
                if candidate["ticker"] == ticker and candidate["action"] == "SELL" and candidate["pnl"] == 0.0:
                    row = candidate
                    break
            if row is None:
                return
            row["pnl"] = round(trade.pnlcomm, 2)
            metrics = self.strategy.position_exit_metrics.pop(trade.data, {})
            row["holding_days"] = metrics.get("holding_days", "")
            row["exit_reason"] = metrics.get("exit_reason", "")
            row["max_unrealized_gain_pct"] = metrics.get("max_unrealized_gain_pct", "")
            row["max_drawdown_during_hold_pct"] = metrics.get("max_drawdown_during_hold_pct", "")
            row["stock_return_pct"] = metrics.get("stock_return_pct", "")
            row["spy_return_pct"] = metrics.get("spy_return_pct", "")
            row["alpha_vs_spy_pct"] = metrics.get("alpha_vs_spy_pct", "")

    def get_analysis(self):
        return self.trades


def main():
    args = parse_args()
    period = args.period

    # Action 2: scope watchlist_history / ticker_state to this market BEFORE
    # any strategy code runs.
    paths = data_persistence.set_market(MARKET)
    log.info("Market scope: %s", paths)

    if args.clear_receipts:
        removed = clear_decision_receipts()
        log.info("Cleared %d existing decision receipt file(s) (--clear-receipts)", removed)

    if period == "OOS":
        flag_path = PROJECT_DIR / "oos_locked.flag"
        if not flag_path.exists():
            log.error("OOS period requires oos_locked.flag.")
            sys.exit(1)

    period_start, period_end = PERIODS[period]
    log.info("=" * 70)
    log.info("Kashif S&P 500 Comparison Backtest")
    log.info("=" * 70)
    log.info("Period: %s (%s to %s)", period, period_start, period_end)
    log.info("Warmup: %s to %s (~253 bars)", WARMUP_START, IS_START)
    log.info("Catalyst: STUBBED to NEUTRAL (no API calls)")
    log.info("Fundamentals: LIVE via yfinance (MARKET_SUFFIX='' for US tickers)")

    ticker_list = args.tickers if args.tickers else SP500_TICKERS
    log.info("Tickers: %d (%s)", len(ticker_list),
             "custom override" if args.tickers else "S&P 500 from Wikipedia")

    # ------------------------------------------------------------------
    # Fetch data
    # ------------------------------------------------------------------
    cerebro = bt.Cerebro()
    viable_count = 0
    skipped = []
    t0 = time.time()

    for i, ticker in enumerate(ticker_list):
        if (i + 1) % 50 == 0:
            elapsed = time.time() - t0
            log.info("  Downloading... %d/%d (%.0fs elapsed)", i + 1, len(ticker_list), elapsed)
        merged_df = fetch_dual_feed(ticker, WARMUP_START, period_end)
        if merged_df is None or len(merged_df) < 50:
            skipped.append(ticker)
            continue

        data = bt.feeds.PandasData(dataname=merged_df, name=ticker)
        cerebro.adddata(data)
        viable_count += 1

    # Feature 9: add SPY as benchmark feed for alpha calculation.
    spy_df = fetch_dual_feed("SPY", WARMUP_START, period_end)
    if spy_df is not None and len(spy_df) >= 50:
        spy_data = bt.feeds.PandasData(dataname=spy_df, name="SPY")
        cerebro.adddata(spy_data)
        log.info("SPY benchmark feed loaded (%d bars)", len(spy_df))
    else:
        log.warning("SPY benchmark feed unavailable — alpha metrics will be zero")

    download_time = time.time() - t0
    log.info("Download complete: %.0fs", download_time)
    log.info("Viable tickers loaded: %d / %d", viable_count, len(ticker_list))
    if skipped:
        log.info("Skipped tickers (%d): %s", len(skipped), ", ".join(skipped[:20]))
        if len(skipped) > 20:
            log.info("  ... and %d more", len(skipped) - 20)

    if viable_count < MIN_VIABLE_TICKERS:
        log.warning("Only %d viable tickers (< %d minimum).", viable_count, MIN_VIABLE_TICKERS)

    # ------------------------------------------------------------------
    # Configure Cerebro — same as EGX: 100k, 0.5% commission, 0.1% slippage
    # ------------------------------------------------------------------
    cerebro.broker.setcash(100_000)
    cerebro.broker.setcommission(commission=0.005)
    cerebro.broker.set_slippage_perc(perc=0.001)

    target_pos = 6  # v0.27: same as EGX — book's 4-6 range, aggressive end
    cerebro.addstrategy(KashifStrategy, target_position_count=target_pos, run_period=period,
                        decision_receipts_dir=str(RECEIPTS_DIR))
    cerebro.addsizer(MinerviniSizer)
    cerebro.addanalyzer(TradeLogger, _name="trade_logger")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", riskfreerate=0.05, annualize=True)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade_analyzer")
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="time_return")

    log.info("Cerebro: cash=100000 USD, commission=0.5%%, slippage=0.1%%, target_positions=%d", target_pos)
    log.info("Running backtest...")
    run_start = time.time()

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    results = cerebro.run()
    strat = results[0]

    run_time = time.time() - run_start
    final_value = cerebro.broker.getvalue()
    total_return = (final_value / 100_000 - 1) * 100
    log.info("Backtest complete in %.0fs.", run_time)
    log.info("Final portfolio value: %.2f USD", final_value)
    log.info("Return: %.2f%%", total_return)

    # ------------------------------------------------------------------
    # Write trade_log_sp500.csv
    # ------------------------------------------------------------------
    trade_log_path = PROJECT_DIR / f"trade_log_{MARKET}_{period}_{today_str}.csv"
    analyzer = strat.analyzers.trade_logger
    trades = analyzer.get_analysis()
    write_trade_log(trades, trade_log_path)
    log.info("Trade log: %s (%d rows)", trade_log_path, len(trades))

    # ------------------------------------------------------------------
    # Detailed Metrics
    # ------------------------------------------------------------------
    log.info("")
    log.info("=" * 70)
    log.info("DETAILED METRICS")
    log.info("=" * 70)

    log.info("Regime-open bars: %d", strat.regime_open_count)
    dc = strat._regime_diag_counts
    log.info("Regime condition breakdown (bars True):")
    log.info("  eval_bars=%d  ratio=%d  pullback=%d  divergence=%d",
             dc["eval_bars"], dc["ratio"], dc["pullback"], dc["divergence"])

    log.info("Tickers scanned: %d", strat._tickers_scanned)
    log.info("Hard filter pass: %d", strat._tickers_passing_hard_filter)
    log.info("Reached catalyst check: %d", strat._tickers_reaching_catalyst_check)
    log.info("New entries signaled: %d", strat._new_entries_signaled)

    sharpe_analysis = strat.analyzers.sharpe.get_analysis()
    sharpe_ratio = sharpe_analysis.get("sharperatio", None)
    log.info("Sharpe ratio (annualized, rf=5%%): %s", f"{sharpe_ratio:.4f}" if sharpe_ratio else "N/A")

    dd = strat.analyzers.drawdown.get_analysis()
    max_dd = dd.get("max", {}).get("drawdown", 0)
    max_dd_len = dd.get("max", {}).get("len", 0)
    log.info("Max drawdown: %.2f%%", max_dd)
    log.info("Max drawdown duration: %d bars", max_dd_len)

    ta = strat.analyzers.trade_analyzer.get_analysis()
    total_closed = ta.get("total", {}).get("closed", 0)
    won = ta.get("won", {}).get("total", 0)
    lost = ta.get("lost", {}).get("total", 0)
    log.info("Trade count (closed): %d (won=%d, lost=%d)", total_closed, won, lost)

    log.info("")
    log.info("First 10 rows of trade log:")
    for i, t in enumerate(trades[:10]):
        log.info("  %d. %s %s %s %s shares @ %.2f  pnl=%.2f  pv=%.2f",
                 i + 1, t["date"], t["action"], t["ticker"], t["shares"],
                 float(t["price"]), float(t["pnl"]), float(t["portfolio_value"]))

    log.info("Download time: %.0fs", download_time)
    log.info("Backtest run time: %.0fs", run_time)
    log.info("Total time: %.0fs", download_time + run_time)
    log.info("=" * 70)

    # ------------------------------------------------------------------
    # Independent Auditor
    # ------------------------------------------------------------------
    log.info("")
    log.info("=" * 70)
    log.info("INDEPENDENT AUDITOR")
    log.info("=" * 70)
    from independent_auditor import run_audit
    audit_report_path = PROJECT_DIR / f"audit_report_{MARKET}_{period}_{today_str}.json"
    audit = run_audit(trade_log_path=trade_log_path, output_path=audit_report_path)
    log.info("Verified: %s", audit["verified"])
    log.info("Auditor equity: %.4f", audit["auditor_equity"])
    log.info("Strategy equity: %s", audit["strategy_equity"])
    log.info("Difference: %s", audit["difference"])
    log.info("Trade count (paired): %d", audit["trade_count"])
    log.info("Discrepancies: %d", len(audit["discrepancies"]))
    if audit["discrepancies"]:
        for disc in audit["discrepancies"][:5]:
            log.info("  %s", disc)
    log.info("Audit report: %s", audit_report_path)

    # ------------------------------------------------------------------
    # QuantStats Report
    # ------------------------------------------------------------------
    log.info("")
    log.info("=" * 70)
    log.info("QUANTSTATS REPORT")
    log.info("=" * 70)
    try:
        import quantstats as qs
        time_returns = strat.analyzers.time_return.get_analysis()
        if time_returns:
            dates = sorted(time_returns.keys())
            returns_series = pd.Series(
                [time_returns[d] for d in dates],
                index=pd.DatetimeIndex([d for d in dates]),
                name="Strategy",
            )
            qs_report_path = PROJECT_DIR / f"quantstats_{MARKET}_{period}_{today_str}.html"
            qs.reports.html(returns_series, output=str(qs_report_path),
                            title=f"Kashif S&P 500 {period} ({period_start} to {period_end})")
            log.info("QuantStats HTML report: %s", qs_report_path)

            log.info("QuantStats key metrics:")
            log.info("  CAGR: %.2f%%", qs.stats.cagr(returns_series) * 100)
            log.info("  Max Drawdown: %.2f%%", qs.stats.max_drawdown(returns_series) * 100)
            def _qs_scalar(val):
                if val is None:
                    return None
                if hasattr(val, 'iloc'):
                    val = val.iloc[0]
                return float(val)

            qs_sharpe = _qs_scalar(qs.stats.sharpe(returns_series))
            qs_sortino = _qs_scalar(qs.stats.sortino(returns_series))
            qs_calmar = _qs_scalar(qs.stats.calmar(returns_series))
            log.info("  Sharpe: %s", f"{qs_sharpe:.4f}" if qs_sharpe is not None else "N/A")
            log.info("  Sortino: %s", f"{qs_sortino:.4f}" if qs_sortino is not None else "N/A")
            log.info("  Calmar: %s", f"{qs_calmar:.4f}" if qs_calmar is not None else "N/A")
        else:
            log.warning("No time returns data — skipping QuantStats.")
    except Exception as e:
        log.error("QuantStats report failed: %s", e)

    log.info("=" * 70)


if __name__ == "__main__":
    main()
