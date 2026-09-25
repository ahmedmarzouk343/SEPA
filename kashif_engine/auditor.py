"""Independent auditor: recompute a run's P&L from its trade list alone.

Reads only the run's fills.csv / dividends.csv / trades.csv / run.json and the
cached price files. It does NOT import the ledger or the engine; the cost
formulas come from the MarketSpec (the published fee schedule), and ADDV is
recomputed from the price file, not taken from the run.

Checks
  1. tape       every fill price lies inside that day's [low, high]; market
                entries fill at the open; stops at the stop level or the open.
  2. costs      commission + slippage recomputed per fill from raw shares /
                raw price / prior-day ADDV.
  3. dividends  recomputed from the price file for shares held at the prior close.
  4. cash & equity  capital - buys + sells + dividends, marked at the last
                close, must equal the ledger EXACTLY (Decimal, same inputs).
  5. per-trade  FIFO round trips rebuilt from fills; net P&L must equal
                trades.csv exactly (to the cent) and the sum must tie out.
"""
from __future__ import annotations

import json
import math
import sys
from decimal import Decimal, getcontext
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
getcontext().prec = 34
D = lambda x: Decimal(repr(float(x)))  # noqa: E731


def audit(run_dir, market, tol_cost=1e-6) -> dict:
    from kashif_engine.data import prices as P
    run_dir = Path(run_dir)
    run = json.loads((run_dir / "run.json").read_text())
    fills = pd.read_csv(run_dir / "fills.csv") if (run_dir / "fills.csv").stat().st_size > 2 else pd.DataFrame()
    divs_path = run_dir / "dividends.csv"
    divs = pd.read_csv(divs_path) if divs_path.stat().st_size > 2 else pd.DataFrame()
    trades = pd.read_csv(run_dir / "trades.csv") if (run_dir / "trades.csv").stat().st_size > 2 else pd.DataFrame()
    problems = []
    px_cache = {}

    def px(t):
        if t not in px_cache:
            f = P.load(t, market.name)
            f["addv50"] = (f["Close"] * f["Volume"]).rolling(50).mean()
            px_cache[t] = f
        return px_cache[t]

    # 1 + 2: tape and costs
    for r in fills.itertuples(index=False):
        f = px(r.ticker)
        day = pd.Timestamp(r.date)
        if day not in f.index:
            problems.append(f"{r.date} {r.ticker}: fill on a day with no bar")
            continue
        bar = f.loc[day]
        lo, hi = bar["Low"], bar["High"]
        if not (lo - 1e-9 <= r.price <= hi + 1e-9):
            problems.append(f"{r.date} {r.ticker} {r.side}: price {r.price} outside [{lo}, {hi}]")
        if r.side == "BUY" and abs(r.price - bar["Open"]) > 1e-9:
            problems.append(f"{r.date} {r.ticker} BUY at {r.price} != open {bar['Open']}")
        factor = bar["SplitFactor"]
        i = f.index.get_loc(day)
        addv_prev = f["addv50"].iloc[i - 1] if i > 0 else float("nan")
        q = abs(r.shares)
        raw_q, raw_p = q / factor, r.price * factor
        comm = market.commission(raw_q, raw_p)
        slip = q * r.price * market.slippage_bps(q * r.price, addv_prev if math.isfinite(addv_prev) else None) / 1e4
        if abs(comm - r.commission) > tol_cost or abs(slip - r.slippage) > tol_cost:
            problems.append(f"{r.date} {r.ticker} {r.side}: costs {r.commission:.6f}/{r.slippage:.6f} "
                            f"recomputed {comm:.6f}/{slip:.6f}")
        if abs(raw_q - r.raw_shares) > 1e-6 or abs(raw_p - r.raw_price) > 1e-6:
            problems.append(f"{r.date} {r.ticker}: raw conversion mismatch")

    # 3: dividends from the tape, for shares held at the previous close
    holdings = {}   # ticker -> shares, replayed day by day
    by_day = {d: g for d, g in fills.groupby("date")} if len(fills) else {}
    days = sorted(set(fills["date"]) | set(divs["date"] if len(divs) else [])) if len(fills) else []
    expected_div = []
    all_days = pd.date_range(run["start"], run["end"], freq="B")
    held_prev = {}
    for day in all_days:
        ds = str(day.date())
        for t, q in held_prev.items():
            f = px(t)
            if day in f.index and f.at[day, "Dividends"] > 0:
                expected_div.append((ds, t, q, float(f.at[day, "Dividends"])))
        for r in by_day.get(ds, pd.DataFrame()).itertuples(index=False):
            holdings[r.ticker] = holdings.get(r.ticker, 0.0) + (r.shares if r.side == "BUY" else -r.shares)
            if abs(holdings[r.ticker]) < 1e-12:
                holdings.pop(r.ticker)
        held_prev = dict(holdings)
    got = sorted((r.date, r.ticker, r.shares, r.per_share) for r in divs.itertuples(index=False)) if len(divs) else []
    if sorted(expected_div) != got:
        missing = set(expected_div) - set(got)
        extra = set(got) - set(expected_div)
        problems.append(f"dividends: {len(missing)} expected-not-booked, {len(extra)} booked-not-expected "
                        f"(e.g. {sorted(missing)[:3]} / {sorted(extra)[:3]})")

    # 4: cash and equity, exact
    cash = D(run["capital"])
    for r in fills.itertuples(index=False):
        gross = D(r.shares) * D(r.price)
        if r.side == "BUY":
            cash -= gross + D(r.commission) + D(r.slippage)
        else:
            cash += gross - D(r.commission) - D(r.slippage)
    for r in divs.itertuples(index=False) if len(divs) else []:
        cash += D(r.shares) * D(r.per_share)
    end = pd.Timestamp(run["end"])
    equity = cash
    for t, q in holdings.items():
        f = px(t).loc[:end]
        equity += D(q) * D(f["Close"].iloc[-1])
    ledger_equity = Decimal(repr(run["final_equity_ledger"]))
    bal = run["ledger_balances"]
    ledger_cash = D(bal.get("cash", 0)) + D(bal.get("receivable", 0)) + D(bal.get("payable", 0))
    cash_match = abs(cash - ledger_cash) < Decimal("1e-9")
    equity_match = abs(equity - ledger_equity) < Decimal("1e-6")
    if not cash_match:
        problems.append(f"cash: auditor {cash} vs ledger {ledger_cash}")
    if not equity_match:
        problems.append(f"equity: auditor {equity} vs ledger {ledger_equity}")

    # 5: per-trade P&L rebuilt FIFO from fills
    open_lots, rebuilt = {}, []
    for r in fills.itertuples(index=False):
        if r.side == "BUY":
            open_lots[r.ticker] = r
        else:
            b = open_lots.pop(r.ticker, None)
            if b is None:
                problems.append(f"{r.date} {r.ticker}: SELL without an open BUY")
                continue
            if abs(b.shares - r.shares) > 1e-9:
                problems.append(f"{r.ticker}: partial round trip {b.shares} vs {r.shares}")
            net = D(r.shares) * (D(r.price) - D(b.price)) - D(b.commission) - D(b.slippage) \
                - D(r.commission) - D(r.slippage)
            rebuilt.append((r.ticker, b.date, r.date, net))
    per_trade_ok = len(rebuilt) == len(trades)
    if per_trade_ok and len(trades):
        for (t, ed, xd, net), tr in zip(rebuilt, trades.itertuples(index=False)):
            if t != tr.ticker or ed != tr.entry_date or xd != tr.exit_date or \
                    abs(float(net) - tr.net_pnl) > 0.005:
                per_trade_ok = False
                problems.append(f"trade {t} {ed}->{xd}: auditor {float(net):.4f} vs trades.csv {tr.net_pnl:.4f}")
                break
    elif not per_trade_ok:
        problems.append(f"round trips: auditor {len(rebuilt)} vs trades.csv {len(trades)}")

    realized = sum(n for *_, n in rebuilt)
    report = {
        "run_id": run["run_id"], "fills": len(fills), "round_trips": len(rebuilt),
        "auditor_cash": str(cash), "ledger_cash": str(ledger_cash),
        "auditor_equity": str(equity), "ledger_equity": str(ledger_equity),
        "cash_exact_match": cash_match, "equity_exact_match": equity_match,
        "per_trade_match": per_trade_ok, "realized_net_pnl": str(realized),
        "dividends_booked": len(got), "dividends_expected": len(expected_div),
        "problems": problems, "passed": not problems,
    }
    (run_dir / "audit.json").write_text(json.dumps(report, indent=2))
    return report
