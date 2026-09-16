"""
run_backtest.py — Real data loader and runner for Kashif EGX virtual trading.

Fetches yfinance history for all 195 valid EGX tickers, builds dual feeds
(auto_adjust=True for OHLC, auto_adjust=False for Volume), warms up 253
bars before the in-sample start, and runs KashifStrategy through Cerebro.

Accepts a PERIOD argument: IS (in-sample), VAL (validation), OOS (out-of-sample).
OOS requires an oos_locked.flag file in the project directory.

Outputs:
  - trade_log_{period}_{date}.csv with full schema (including Feature 9 exit metrics)
  - ops log under daily_ops_log/
  - audit_report_{period}_{date}.json (independent auditor)
  - quantstats_{period}_{date}.html (QuantStats report, only if audit passes)
"""

import argparse
import csv
import datetime
import logging
import os
import sys
import time
from pathlib import Path

import backtrader as bt
import pandas as pd
import yfinance as yf

import kashif_strategy

from egx_tickers import VALID_TICKERS, BAD_DATA_TICKERS, ZERO_DATA_TICKERS
from split_corrections import apply_split_corrections, write_split_log
from kashif_strategy import CATALYST_MODE, ENTRY_TIMING_MARKET
from entry_timing import EGX_SINGLE_CONTRACTION_VOLUME_DRYUP_ALLOWANCE
import data_persistence
from kashif_strategy import KashifStrategy
from kashif_sizer import MinerviniSizer
from catalyst_check import get_budget_status

PROJECT_DIR = Path(__file__).resolve().parent

# Action 2: every output of this runner is scoped to its market, so an EGX
# run and an S&P 500 run can never write the same file.
MARKET = "EGX"
# PAIRED EXPERIMENT: an optional label that suffixes every output file and the
# receipts directory, so two arms run back to back cannot overwrite each
# other's trade log, audit report, or receipts. Empty by default — an ordinary
# run keeps its existing filenames.
RUN_LABEL = os.environ.get("KASHIF_RUN_LABEL", "").strip()
_LABEL_SUFFIX = f"_{RUN_LABEL}" if RUN_LABEL else ""

RECEIPTS_DIR = PROJECT_DIR / f"decision_receipts_{MARKET}{_LABEL_SUFFIX}"

# --------------------------------------------------------------------------
# Date constants — do not change.
# --------------------------------------------------------------------------
# RS warmup: the first ~253 bars (WARMUP_START to IS_START) produce NO
# trade signals. RS percentile requires 252 bars of history before the
# cross-sectional ranking is valid. Data is fetched from WARMUP_START so
# that by IS_START every ticker has enough history for a meaningful RS
# percentile. Any signal generated during the warmup window would be
# based on incomplete ranking and must be suppressed.
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
ops_log_path = OPS_LOG_DIR / f"run_backtest_{today_str}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(ops_log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("run_backtest")


def parse_args():
    parser = argparse.ArgumentParser(description="Kashif EGX Backtest Runner")
    parser.add_argument(
        "period",
        choices=["IS", "VAL", "OOS"],
        help="Backtest period: IS (in-sample), VAL (validation), OOS (out-of-sample)",
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=None,
        help="Override ticker list (e.g. --tickers COMI TMGH SWDY). Default: all 195 valid.",
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


SPLIT_RATIO_HIGH = 3.0      # single-day close ratio above this = suspected split/reverse-split
SPLIT_RATIO_LOW = 1.0 / 3.0


def scan_for_splits(ticker, df):
    """
    FIX 3: data-quality scan only. Flags any single-day close-to-close ratio
    above 3x or below 0.33x — the signature of an unadjusted split, reverse
    split, or a bad print.

    REPORT ONLY. Deliberately does NOT exclude the ticker or alter which
    trades are taken; a genuine 3x single-day move is possible on a thin EGX
    name and auto-excluding would silently drop real data. Returns a list of
    {ticker, date, prev_close, close, ratio}.
    """
    flags = []
    try:
        closes = df["Close"].dropna()
        if len(closes) < 2:
            return flags
        ratio = closes / closes.shift(1)
        for dt, r in ratio.items():
            if r is None or not (r > 0):
                continue
            if r > SPLIT_RATIO_HIGH or r < SPLIT_RATIO_LOW:
                prev = float(closes.shift(1).loc[dt])
                flags.append({
                    "ticker": ticker,
                    "date": str(dt.date()) if hasattr(dt, "date") else str(dt),
                    "prev_close": round(prev, 4),
                    "close": round(float(closes.loc[dt]), 4),
                    "ratio": round(float(r), 3),
                })
    except Exception as e:  # noqa: BLE001 — a scan must never break the run
        log.warning("Split scan failed for %s: %s", ticker, e)
    return flags


def fetch_dual_feed(ticker, start, end):
    """
    Fetch two DataFrames for one ticker:
      - adj_df: auto_adjust=True  -> adjusted OHLC
      - raw_df: auto_adjust=False -> raw Volume

    Merges raw Volume into adj_df. Returns the merged DataFrame or None.
    """
    symbol = f"{ticker}.CA"
    try:
        adj_df = yf.download(symbol, start=start, end=end, auto_adjust=True, progress=False)
        raw_df = yf.download(symbol, start=start, end=end, auto_adjust=False, progress=False)
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
    """Write trade_log.csv with the full Feature 9 schema."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TRADE_LOG_FIELDS)
        writer.writeheader()
        for t in trades:
            writer.writerow({k: t.get(k, "") for k in TRADE_LOG_FIELDS})


class TradeLogger(bt.Analyzer):
    """Captures every order fill (BUY/SELL) for trade_log.csv and auditor pairing.

    Uses backtrader's actual executed values:
    - order.executed.price already includes slippage (broker applies it)
    - order.executed.comm is the actual commission the broker charged
    - trade.pnlcomm is PnL after commission (the real net P&L)
    Slippage field is 0 because it's baked into the executed price.
    """

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
    # PAIRED EXPERIMENT: scope the persistence store by run label too. Two arms
    # running concurrently would otherwise share one ticker_state parquet and
    # one watchlist_history jsonl, so each would read state the other wrote —
    # and a controlled comparison cannot have the arms feeding each other.
    paths = data_persistence.set_market(f"{MARKET}{_LABEL_SUFFIX}")
    log.info("Market scope: %s", paths)

    if args.clear_receipts:
        removed = clear_decision_receipts()
        log.info("Cleared %d existing decision receipt file(s) (--clear-receipts)", removed)

    if period == "OOS":
        flag_path = PROJECT_DIR / "oos_locked.flag"
        if not flag_path.exists():
            log.error(
                "OOS period requires oos_locked.flag in %s. "
                "Create it after locking parameters: "
                'echo "Parameters locked" > oos_locked.flag',
                PROJECT_DIR,
            )
            sys.exit(1)

    period_start, period_end = PERIODS[period]
    log.info("=" * 70)
    log.info("Kashif EGX Backtest Runner")
    log.info("=" * 70)
    log.info("Period: %s (%s to %s)", period, period_start, period_end)
    # PAIRED EXPERIMENT: print the varied settings so each log states, on its
    # own, which arm produced it — no cross-referencing a shell history.
    log.info("RUN CONFIG: label=%s  entry_timing_market=%r  catalyst_mode=%s  "
             "single_contraction_allowance=%s",
             RUN_LABEL or "(none)", ENTRY_TIMING_MARKET, CATALYST_MODE,
             EGX_SINGLE_CONTRACTION_VOLUME_DRYUP_ALLOWANCE)
    log.info("Warmup period: %s to %s (~253 bars, no signals)", WARMUP_START, IS_START)
    ticker_list = args.tickers if args.tickers else VALID_TICKERS
    log.info("Tickers: %d (%s)", len(ticker_list),
             "custom override" if args.tickers
             else "%d zero-data + %d bad-data (%s) excluded from 224 total"
                  % (len(ZERO_DATA_TICKERS), len(BAD_DATA_TICKERS),
                     ", ".join(sorted(BAD_DATA_TICKERS))))

    # ------------------------------------------------------------------
    # Fetch data — dual feeds per ticker, starting from WARMUP_START
    # ------------------------------------------------------------------
    cerebro = bt.Cerebro()
    viable_count = 0
    skipped = []
    split_flags = []          # FIX 3: data-quality scan, report only
    split_records = []        # JOB 1: split corrections actually applied
    t0 = time.time()

    for i, ticker in enumerate(ticker_list):
        if (i + 1) % 50 == 0:
            elapsed = time.time() - t0
            log.info("  Downloading... %d/%d (%.0fs elapsed)", i + 1, len(ticker_list), elapsed)
        merged_df = fetch_dual_feed(ticker, WARMUP_START, period_end)
        if merged_df is None or len(merged_df) < 50:
            skipped.append(ticker)
            continue

        # JOB 1: correct known unadjusted splits BEFORE anything reads the
        # series, so every downstream indicator sees a continuous price
        # history. Runs automatically on every backtest; what it did is
        # appended to split_corrections_applied.log below.
        merged_df, corrections = apply_split_corrections(ticker, merged_df)
        split_records.extend(corrections)

        # The scan now runs on the CORRECTED frame, so anything it still flags
        # is a residual anomaly nobody has accounted for.
        split_flags.extend(scan_for_splits(ticker, merged_df))

        data = bt.feeds.PandasData(dataname=merged_df, name=ticker)
        cerebro.adddata(data)
        viable_count += 1

    download_time = time.time() - t0
    log.info("Download complete: %.0fs", download_time)
    log.info("Viable tickers loaded: %d / %d", viable_count, len(VALID_TICKERS))
    # JOB 1: report and persist the corrections applied this run.
    if split_records:
        applied = [r for r in split_records if r["status"] == "APPLIED"]
        broken = [r for r in applied if not r["continuous"]]
        log.info("SPLIT CORRECTION: %d of %d known splits applied.",
                 len(applied), len(split_records))
        for r in sorted(split_records, key=lambda r: r["ticker"]):
            if r["status"] == "APPLIED":
                log.info("  CORRECTED %-6s %s  %d:1  %d bars adjusted  "
                         "residual %.4fx  continuous=%s",
                         r["ticker"], r["date"], r["ratio"], r["bars_adjusted"],
                         r["residual_ratio"], "YES" if r["continuous"] else "NO")
            else:
                log.warning("  NOT CORRECTED %-6s %s  %s",
                            r["ticker"], r["date"], r["status"])
        if broken:
            log.warning("SPLIT CORRECTION: %d ticker(s) STILL discontinuous after "
                        "adjustment — review split_corrections_applied.log.", len(broken))
        log_path = write_split_log(split_records, period=period)
        log.info("SPLIT CORRECTION: audit trail appended to %s", log_path.name)

    # FIX 3: report every suspected split. Flag for manual review — no exclusion.
    if split_flags:
        by_ticker = {}
        for f in split_flags:
            by_ticker.setdefault(f["ticker"], []).append(f)
        log.warning("SPLIT SCAN (post-correction): %d RESIDUAL suspected split/bad-print "
                    "day(s) across %d ticker(s) (ratio >%.1fx or <%.2fx). "
                    "FLAGGED FOR REVIEW ONLY — none excluded.",
                    len(split_flags), len(by_ticker), SPLIT_RATIO_HIGH, SPLIT_RATIO_LOW)
        for tk in sorted(by_ticker):
            for f in by_ticker[tk]:
                log.warning("  SPLIT? %-6s %s  close %.4f -> %.4f  ratio %.3fx",
                            f["ticker"], f["date"], f["prev_close"], f["close"], f["ratio"])
    else:
        log.info("SPLIT SCAN (post-correction): no residual splits across %d tickers.",
                 viable_count)

    if skipped:
        log.info("Skipped tickers (%d): %s", len(skipped), ", ".join(skipped[:20]))
        if len(skipped) > 20:
            log.info("  ... and %d more", len(skipped) - 20)

    if viable_count < MIN_VIABLE_TICKERS:
        log.warning(
            "STARTUP CHECK: only %d viable tickers (< %d minimum). "
            "Results may not be representative.",
            viable_count, MIN_VIABLE_TICKERS,
        )

    # ------------------------------------------------------------------
    # Configure Cerebro
    # ------------------------------------------------------------------
    cerebro.broker.setcash(100_000)
    cerebro.broker.setcommission(commission=0.005)
    cerebro.broker.set_slippage_perc(perc=0.001)

    # ACTION 2: fixed at 6, was max(4, min(viable_count // 10, 20)).
    # With 195 viable EGX tickers that formula produced NINETEEN slots, so
    # each position was ~5,300 EGP of a 100,000 book and a winner barely
    # moved the portfolio. The book specifies 4-6 concurrent positions for an
    # account this size; 6 gives ~16,700 EGP per position, roughly 3x the
    # impact per winning trade.
    target_pos = 6
    cerebro.addstrategy(KashifStrategy, target_position_count=target_pos, run_period=period,
                        decision_receipts_dir=str(RECEIPTS_DIR))
    cerebro.addsizer(MinerviniSizer)
    cerebro.addanalyzer(TradeLogger, _name="trade_logger")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", riskfreerate=0.20, annualize=True)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade_analyzer")
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="time_return")

    log.info("Cerebro: cash=100000 EGP, commission=0.5%%, slippage=0.1%%, target_positions=%d", target_pos)
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
    log.info("Final portfolio value: %.2f EGP", final_value)
    log.info("Return: %.2f%%", total_return)

    # ------------------------------------------------------------------
    # Write trade_log.csv
    # ------------------------------------------------------------------
    trade_log_path = PROJECT_DIR / f"trade_log_{MARKET}_{period}_{today_str}{_LABEL_SUFFIX}.csv"
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
    log.info("Sharpe ratio (annualized, rf=20%%): %s", f"{sharpe_ratio:.4f}" if sharpe_ratio else "N/A")

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

    budget = get_budget_status()
    log.info("Catalyst API calls: %d / %d (remaining: %d)",
             budget["budget_used"], budget["budget_total"], budget["budget_remaining"])

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
    audit_report_path = PROJECT_DIR / f"audit_report_{MARKET}_{period}_{today_str}{_LABEL_SUFFIX}.json"
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
                            title=f"Kashif EGX {period} ({period_start} to {period_end})")
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
