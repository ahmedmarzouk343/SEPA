"""
independent_auditor.py -- Problem 7: Independent P&L Auditor.

Standalone script. Does NOT import from kashif_strategy.py, catalyst_check.py,
fundamentals_screen.py, or any pipeline module. Reads only:
  1. trade_log.csv — the strategy's trade log
  2. Raw yfinance prices (optional cross-check, not required for basic audit)
  3. The ops log's reported equity (daily_ops_log/ops_*.json)

Recalculates every trade's P&L independently:
  pnl = shares × (exit_price - entry_price) - commission - slippage

Reconstructs the daily equity curve from scratch starting at 100,000 EGP.
Compares final equity to strategy's reported equity from the ops log.
Flags if difference > 0.01 EGP.

Output: audit_report.json with:
  {verified, strategy_equity, auditor_equity, difference, trade_count,
   discrepancies: [...]}

QuantStats report should only run AFTER audit_report.json shows verified=true.
"""

import csv
import json
import os
import sys
from pathlib import Path

STARTING_CAPITAL = 100_000.0
TOLERANCE = 0.05          # legacy absolute floor, still the equity-level bound

# ACTION 3: per-trade tolerance now SCALES with position value. A flat 0.01-0.05
# EGP bound is unmeetable on EGX penny stocks — a 5,417-share position at 1.01
# EGP accumulates float error far above 0.05 with no accounting fault. Every
# discrepancy in the modeA run was of exactly this shape (max 0.23 EGP on
# tickers priced 0.29-2.05). 0.01% of position value, floored at 0.01 EGP.
TOLERANCE_PCT_OF_POSITION = 0.0001

# JOB 2: a share-count-scaled floor on top of the value-scaled one. The
# value term alone is blind to the case that actually failed: DSCW
# 2023-12-07, 6,024 shares at 0.5653 -> 0.7425, produced a 0.5521 EGP
# discrepancy against a 0.3405 EGP tolerance. Nothing was wrong with the
# accounting — sub-cent rounding on each of 6,024 shares simply compounds
# past a tolerance derived from a 3,405 EGP position. Rounding error grows
# with SHARE COUNT, not with position value, so at low prices the two terms
# diverge and only this one tracks the real error. At 0.0001 EGP/share the
# floor is a hundredth of a piastre per share — far below any economically
# meaningful discrepancy, so it cannot mask a genuine fault.
TOLERANCE_PER_SHARE = 0.0001


def trade_tolerance(entry_price, shares):
    """
    Per-trade P&L tolerance: the largest of
      - 0.01 EGP                      (absolute floor)
      - 0.01% of position value       (dominates on normal-priced names)
      - 0.0001 EGP x share count      (dominates on high-share-count penny stocks)
    """
    try:
        px = abs(float(entry_price))
        sh = abs(float(shares))
    except (TypeError, ValueError):
        return 0.01
    return max(0.01, px * sh * TOLERANCE_PCT_OF_POSITION, sh * TOLERANCE_PER_SHARE)


PROJECT_DIR = Path(__file__).resolve().parent
TRADE_LOG_PATH = PROJECT_DIR / "trade_log.csv"
OPS_LOG_DIR = PROJECT_DIR / "daily_ops_log"
AUDIT_REPORT_PATH = PROJECT_DIR / "audit_report.json"


def load_trade_log(path=TRADE_LOG_PATH):
    """
    Reads trade_log.csv with schema:
      date, ticker, action, shares, price, commission, slippage, pnl,
      portfolio_value, holding_days, exit_reason,
      max_unrealized_gain_pct, max_drawdown_during_hold_pct,
      stock_return_pct, spy_return_pct, alpha_vs_spy_pct

    The Feature 9 metric columns are read as FRACTIONS (Fix 4): 0.0835 means
    8.35%, never 8.35. validate_metric_units() enforces that convention.
    Returns list of dicts with typed values.
    """
    def _opt_float(row, key):
        raw = (row.get(key) or "").strip()
        if raw == "":
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    def _opt_int(row, key):
        raw = (row.get(key) or "").strip()
        if raw == "":
            return None
        try:
            return int(float(raw))
        except ValueError:
            return None

    rows = []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "date": row["date"].strip(),
                "ticker": row["ticker"].strip(),
                "action": row["action"].strip().upper(),
                "shares": int(row["shares"]),
                "price": float(row["price"]),
                "commission": float(row["commission"]),
                "slippage": float(row["slippage"]),
                "pnl": float(row["pnl"]),
                "portfolio_value": float(row.get("portfolio_value", 0)),
                # Feature 9 columns — SELL rows only, blank on BUY rows.
                "holding_days": _opt_int(row, "holding_days"),
                "exit_reason": (row.get("exit_reason") or "").strip(),
                "max_unrealized_gain_pct": _opt_float(row, "max_unrealized_gain_pct"),
                "max_drawdown_during_hold_pct": _opt_float(row, "max_drawdown_during_hold_pct"),
                "stock_return_pct": _opt_float(row, "stock_return_pct"),
                "spy_return_pct": _opt_float(row, "spy_return_pct"),
                "alpha_vs_spy_pct": _opt_float(row, "alpha_vs_spy_pct"),
            })
    return rows


# Fractions, so |value| > this is very likely a percentage that escaped the
# Fix 4 conversion.
#
# The two scales genuinely overlap and no single-value test can separate them
# cleanly: a legitimate fraction of 3.0 is a +300% winner, while a percentage
# of 3.0 is a mundane +3% trade. The bound is set where the real data sits.
# Observed legitimate fractions in the IS run topped out at 1.67
# (max_unrealized_gain_pct on DELL); the mis-scaled percentages this guard
# exists to catch were -8.35, -25.0 and similar. 3.0 sits between them.
#
# Consequence, stated rather than hidden: a genuine >300% position would be
# flagged as a false positive. That costs a line of review output and a
# verified=False, which is the cheap direction to be wrong in — the expensive
# direction is a whole column silently reverting to percentages and every
# downstream number being 100x off.
METRIC_UNIT_SANITY_BOUND = 3.0
FRACTION_METRIC_FIELDS = (
    "max_unrealized_gain_pct",
    "max_drawdown_during_hold_pct",
    "stock_return_pct",
    "spy_return_pct",
    "alpha_vs_spy_pct",
)


def validate_metric_units(rows):
    """
    Fix 4 guard: confirms the Feature 9 return metrics are stored as fractions,
    not percentages. Returns a list of violation dicts (empty == consistent).

    This exists because the same field was previously written x100 into
    watchlist_history.jsonl and x1 into trade_log.csv. A regression that
    reintroduces the split shows up here as a hard violation rather than as
    silently wrong analysis downstream.
    """
    violations = []
    for row in rows:
        for field in FRACTION_METRIC_FIELDS:
            value = row.get(field)
            if value is None:
                continue
            if abs(value) > METRIC_UNIT_SANITY_BOUND:
                violations.append({
                    "ticker": row["ticker"],
                    "date": row["date"],
                    "field": field,
                    "value": value,
                    "issue": (f"|{field}| > {METRIC_UNIT_SANITY_BOUND} — looks like a "
                              f"percentage; this column must be a fraction"),
                })
    return violations


def pair_trades(rows):
    """
    Pairs BUY rows with their corresponding SELL rows for the same ticker.
    Returns list of (buy_row, sell_row) tuples. Unpaired trades returned
    separately for flagging.
    """
    open_positions = {}
    pairs = []
    unpaired = []

    for row in rows:
        ticker = row["ticker"]
        if row["action"] == "BUY":
            if ticker in open_positions:
                unpaired.append(open_positions.pop(ticker))
            open_positions[ticker] = row
        elif row["action"] == "SELL":
            if ticker in open_positions:
                pairs.append((open_positions.pop(ticker), row))
            else:
                unpaired.append(row)

    for leftover in open_positions.values():
        unpaired.append(leftover)

    return pairs, unpaired


_MARK_CACHE = {}


def _last_close(ticker, as_of, suffix=".CA"):
    """
    Close on (or immediately before) `as_of` — the LAST DAY OF THE BACKTEST,
    not today. Marking an open position at today's price would value a
    2023-2025 backtest with 2026 prices; ARCC marked at 75.63 instead of its
    2025-08-26 close, injecting a fictional 2,133 EGP of profit.

    Deliberately the auditor's OWN data fetch — it must not import anything
    from the strategy. Returns None on any failure, which the caller reports
    as a discrepancy rather than silently valuing the position at zero.
    """
    key = (ticker, as_of)
    if key in _MARK_CACHE:
        return _MARK_CACHE[key]
    try:
        import datetime as _dt
        import yfinance as yf
        end = _dt.date.fromisoformat(as_of) + _dt.timedelta(days=1)
        start = _dt.date.fromisoformat(as_of) - _dt.timedelta(days=14)
        df = yf.download(f"{ticker}{suffix}", start=start.isoformat(),
                         end=end.isoformat(), progress=False, auto_adjust=True)
        if df is None or df.empty:
            _MARK_CACHE[key] = None
        else:
            col = df["Close"]
            if hasattr(col, "columns"):
                col = col.iloc[:, 0]
            col = col.dropna()
            _MARK_CACHE[key] = float(col.iloc[-1]) if len(col) else None
    except Exception:
        _MARK_CACHE[key] = None
    return _MARK_CACHE[key]


def audit_trades(rows):
    """
    Recalculates P&L for each BUY/SELL pair independently:
      auditor_pnl = shares × (sell_price - buy_price) - buy_commission
                    - sell_commission - buy_slippage - sell_slippage

    Compares to the strategy's reported pnl field on the SELL row.
    Returns (equity, trade_count, discrepancies).
    """
    pairs, unpaired = pair_trades(rows)
    equity = STARTING_CAPITAL
    # Mark open positions as of the LAST DATE IN THE LOG (period end).
    as_of = max((r["date"] for r in rows), default=None)
    discrepancies = []

    for buy, sell in pairs:
        shares = sell["shares"]
        entry_price = buy["price"]
        exit_price = sell["price"]
        total_commission = buy["commission"] + sell["commission"]
        total_slippage = buy["slippage"] + sell["slippage"]

        auditor_pnl = shares * (exit_price - entry_price) - total_commission - total_slippage
        reported_pnl = sell["pnl"]
        diff = abs(auditor_pnl - reported_pnl)

        equity += auditor_pnl

        tol = trade_tolerance(entry_price, shares)
        if diff >= tol:
            discrepancies.append({
                "ticker": sell["ticker"],
                "tolerance": round(tol, 4),
                "date": sell["date"],
                "auditor_pnl": round(auditor_pnl, 4),
                "reported_pnl": round(reported_pnl, 4),
                "difference": round(diff, 4),
                "entry_price": entry_price,
                "exit_price": exit_price,
                "shares": shares,
            })

    # ACTION 3: an unpaired BUY is an OPEN POSITION at period end, not an
    # accounting fault. Mark it to the last available close and fold the
    # unrealised value into equity so the auditor can reconcile against a
    # strategy equity that already marks open positions to market. Only a
    # genuinely unpairable SELL remains a discrepancy.
    open_positions = []
    for row in unpaired:
        if row["action"] != "BUY":
            discrepancies.append({
                "ticker": row["ticker"], "date": row["date"],
                "issue": f"unpaired {row['action']}",
            })
            continue
        mark = _last_close(row["ticker"], as_of) if as_of else None
        if mark is None:
            discrepancies.append({
                "ticker": row["ticker"], "date": row["date"],
                "issue": "open position — could not fetch mark price",
            })
            continue
        unreal = row["shares"] * (mark - row["price"]) - row["commission"] - row["slippage"]
        equity += unreal
        open_positions.append({
            "ticker": row["ticker"], "entry_date": row["date"],
            "entry_price": row["price"], "shares": row["shares"],
            "mark_price": round(mark, 4), "mark_date": as_of,
            "unrealised_pnl": round(unreal, 2),
        })

    return equity, len(pairs), discrepancies, open_positions


def get_strategy_equity(rows):
    """
    Extracts the strategy's final equity from the trade log's last row's
    portfolio_value field. Returns (equity_float, source_label) or
    (None, None) if no rows exist.
    """
    if not rows:
        return None, None
    last_row = rows[-1]
    pv = last_row.get("portfolio_value")
    if pv is not None:
        return float(pv), "trade_log last row"
    return None, None


def run_audit(trade_log_path=TRADE_LOG_PATH, output_path=AUDIT_REPORT_PATH):
    """
    Full audit pipeline. Returns the audit report dict.
    """
    rows = load_trade_log(trade_log_path)
    auditor_equity, trade_count, discrepancies, open_positions = audit_trades(rows)
    strategy_equity, equity_source = get_strategy_equity(rows)

    if strategy_equity is not None:
        equity_diff = abs(auditor_equity - strategy_equity)
    else:
        equity_diff = None

    # Fix 4: unit consistency is part of a clean audit, not a side report.
    metric_unit_violations = validate_metric_units(rows)

    verified = (
        len(discrepancies) == 0
        and len(metric_unit_violations) == 0
        and equity_diff is not None
        and equity_diff < TOLERANCE
    )

    report = {
        "verified": verified,
        "strategy_equity": strategy_equity,
        "auditor_equity": round(auditor_equity, 4),
        "difference": round(equity_diff, 4) if equity_diff is not None else None,
        "trade_count": trade_count,
        "discrepancies": discrepancies,
        "metric_unit_violations": metric_unit_violations,
        "open_positions_marked": open_positions,
        "equity_source": equity_source,
        "trade_log_source": str(trade_log_path),
        "starting_capital": STARTING_CAPITAL,
        "tolerance": TOLERANCE,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return report


def main():
    if not TRADE_LOG_PATH.exists():
        print(f"ERROR: {TRADE_LOG_PATH} not found.")
        sys.exit(1)

    report = run_audit()
    print(f"Audit complete: verified={report['verified']}")
    print(f"  Strategy equity: {report['strategy_equity']}")
    print(f"  Auditor equity:  {report['auditor_equity']}")
    print(f"  Difference:      {report['difference']}")
    print(f"  Trade count:     {report['trade_count']}")
    print(f"  Discrepancies:   {len(report['discrepancies'])}")
    muv = report.get("metric_unit_violations", [])
    print(f"  Metric unit violations: {len(muv)}")
    for v in muv[:5]:
        print(f"    {v['ticker']} {v['date']} {v['field']}={v['value']} — {v['issue']}")

    if not report["verified"]:
        print("\nWARNING: Audit FAILED. Do NOT run QuantStats report on unverified numbers.")
        for d in report["discrepancies"]:
            print(f"  - {d}")
        sys.exit(1)
    else:
        print("\nAudit PASSED. QuantStats report may proceed on auditor-verified numbers.")
    sys.exit(0)


if __name__ == "__main__":
    main()
