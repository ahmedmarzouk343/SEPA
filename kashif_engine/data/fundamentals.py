"""Point-in-time fundamentals adapter over us_fundamentals/fundamentals_store.

Every lookup goes through the store's own gate -- get_known_fundamentals() /
get_known_history() (earnings_release_date <= as_of) -- and every EPS through
adjust_eps_for_splits(..., sim_date). Nothing here reads date.today().

Knowledge timing. The store carries a release DATE with no time of day, and
most SEC filings land after the close. A release on day R is therefore
treated as usable from R+1 (MarketSpec.fundamentals_usable_from with
before_close=False): at the close of simulated day D the adapter queries the
store with as_of = D - 1 day.

Staleness. If the newest usable release is more than STALE_DAYS old, the next
quarter is overdue; the row is still returned but flagged stale, and the
strategy must skip fundamentals-based entry that day. (The store's own
stale_gap_quarter column is computed from the NEXT release date, which is
lookahead -- it is deliberately not used.)

Growth convention. YoY growth = (cur - prior) / |prior|, defined only when the
exact year-ago fiscal quarter is known and prior != 0. The old
fundamentals_fetcher returned cur/prior (a ratio, so +25% growth read as
1.25 and passed a 20% floor for almost any profitable stock) -- that bug is
why this adapter computes growth itself instead of reusing the fetcher.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "us_fundamentals"))
sys.path.insert(0, str(ROOT))

from fundamentals_store import (  # noqa: E402
    adjust_eps_for_splits, get_known_fundamentals, get_known_history,
)
from fundamentals_screen import evaluate_fundamentals  # noqa: E402


def split_table_fingerprint() -> str:
    """Hash of the merged split table; EPS is split-adjusted at query time,
    so cached screen results must change when the table changes."""
    import hashlib
    from fundamentals_store import STOCK_SPLITS
    rows = sorted((t, str(e["effective_date"]), str(e["ratio"])) for t, ev in STOCK_SPLITS.items() for e in ev)
    return hashlib.sha256(repr(rows).encode()).hexdigest()[:16]

STALE_DAYS = 120
N_QUARTERS = 8
YEAR_AGO_TOL_DAYS = 25        # year-ago quarter end within 365 +/- 25 days
QTR_MIN_DAYS, QTR_MAX_DAYS = 60, 120   # consecutive quarter ends


def _growth(cur, prior):
    if cur is None or prior is None or pd.isna(cur) or pd.isna(prior) or prior == 0:
        return None
    return (cur - prior) / abs(prior)


def knowledge_date(sim_date: date, market) -> date:
    """Latest release date whose data is usable at sim_date's close."""
    # usable_from(R) <= sim_date  <=>  R <= sim_date - lag; find lag once.
    lag = (market.fundamentals_usable_from(sim_date, False) - sim_date).days
    return sim_date - timedelta(days=lag)


def snapshot(ticker: str, sim_date: date, market, n_quarters: int = N_QUARTERS) -> dict:
    """What the strategy may know about `ticker` at the close of sim_date."""
    as_of = knowledge_date(sim_date, market)
    latest = get_known_fundamentals(ticker, as_of)
    if latest is None:
        return {"status": "NO_DATA", "as_of": as_of, "reason": "no release known yet"}
    hist = get_known_history(ticker, as_of)
    assert hist.iloc[-1]["fiscal_quarter"] == latest["fiscal_quarter"], "gate mismatch"

    # Quarters are paired by quarter_end_date, not by fiscal label: ~16 tickers
    # have fiscal-year changes or SPAC/transition stubs whose labels jump
    # (scan_label_consistency.py), and label arithmetic would mis-pair them.
    q = hist.sort_values("quarter_end_date").drop_duplicates("quarter_end_date", keep="last")
    # History break (SPAC shell, reverse merger, fresh start): quarters ending
    # before it belong to another entity or basis, so nothing is compared
    # across it. Only breaks already public at sim_date apply.
    from kashif_engine.data.price_corrections import history_breaks, FUND_KINDS
    cut = [pd.Timestamp(b["date"]) for b in history_breaks(ticker)
           if b["kind"] in FUND_KINDS and pd.Timestamp(b["date"]).date() <= sim_date]
    if cut:
        q = q[pd.to_datetime(q["quarter_end_date"]) >= max(cut)]
        if q.empty:
            return {"status": "NO_DATA", "as_of": as_of, "reason": f"history break {max(cut).date()}"}
    recs = []
    for r in q.itertuples(index=False):
        eps = None if pd.isna(r.eps) else adjust_eps_for_splits(
            ticker, float(r.eps), r.earnings_release_date, sim_date)
        recs.append({"end": pd.Timestamp(r.quarter_end_date), "eps": eps,
                     "revenue": None if pd.isna(r.revenue) else float(r.revenue),
                     "label": r.fiscal_quarter, "release": r.earnings_release_date})

    def year_ago(i):
        target = recs[i]["end"] - pd.Timedelta(days=365)
        best = None
        for j in range(i - 1, -1, -1):
            gap = abs((recs[j]["end"] - target).days)
            if gap <= YEAR_AGO_TOL_DAYS and (best is None or gap < best[0]):
                best = (gap, j)
            if recs[j]["end"] < target - pd.Timedelta(days=YEAR_AGO_TOL_DAYS):
                break
        return recs[best[1]] if best else None

    # Anchor on the NEWEST quarter known, not the row released last: a
    # restated/comparative old quarter can carry the latest release date
    # (MBC 2023-06..08: Q2 2022 re-released after Q1 2023 was out).
    li = len(recs) - 1
    release = recs[li]["release"]
    days_since = (sim_date - release).days
    out = {
        "status": "OK", "as_of": as_of, "latest_quarter": recs[li]["label"],
        "latest_quarter_end": str(recs[li]["end"].date()),
        "latest_release": release, "days_since_release": days_since,
        "stale": days_since > STALE_DAYS,
    }

    # Consecutive quarters ending at the latest one (a missing quarter ends the run).
    seq = [li]
    while seq[-1] > 0 and len(seq) < n_quarters + 4:
        gap = (recs[seq[-1]]["end"] - recs[seq[-1] - 1]["end"]).days
        if not (QTR_MIN_DAYS <= gap <= QTR_MAX_DAYS):
            break
        seq.append(seq[-1] - 1)
    seq.reverse()

    def yoy(field):
        vals = [_growth(recs[i][field], (year_ago(i) or {}).get(field)) for i in seq]
        run = []
        for g in reversed(vals):          # most recent contiguous defined run
            if g is None:
                break
            run.append(g)
        return list(reversed(run))[-n_quarters:]

    eps_g = yoy("eps")
    rev_g = yoy("revenue")

    # Annual EPS: at each fiscal-Q4 row, the sum of the 4 consecutive quarters
    # ending there (chained by date). Consecutive fiscal years only.
    annual = []
    for i in range(li + 1):
        if not str(recs[i]["label"]).startswith("Q4") or i < 3:
            continue
        chain = recs[i - 3:i + 1]
        spans_ok = all(QTR_MIN_DAYS <= (chain[k + 1]["end"] - chain[k]["end"]).days <= QTR_MAX_DAYS
                       for k in range(3))
        if spans_ok and all(c["eps"] is not None for c in chain):
            annual.append((recs[i]["end"], sum(c["eps"] for c in chain)))
    ann_run = []
    for end_d, v in reversed(annual):
        if ann_run and not (330 <= (ann_run[-1][0] - end_d).days <= 400):
            break
        ann_run.append((end_d, v))
    ann_run.reverse()

    ya = year_ago(li)
    rows_latest = recs[li]
    cur_eps = rows_latest["eps"]
    ya_eps = ya["eps"] if ya else None
    out.update({
        "latest_eps": cur_eps,
        "year_ago_eps": ya_eps,
        "eps_yoy_growth_by_quarter": eps_g,
        "revenue_yoy_growth_by_quarter": rev_g,
        "annual_eps_by_year": [v for _, v in ann_run],
        "annual_fiscal_year_ends": [str(e.date()) for e, _ in ann_run],
        "turnaround": ya_eps is not None and cur_eps is not None and ya_eps <= 0 < cur_eps,
    })
    return out


def screen(ticker: str, sim_date: date, market) -> dict:
    """Fundamentals verdict for entry on sim_date.

    verdict in {PASS, FAIL, SKIP}. SKIP = not evaluable (no data, stale, or
    the latest quarter's growth is undefined) -- the stock is not eligible for
    a fundamentals-based entry that day, and the reason is logged.
    """
    snap = snapshot(ticker, sim_date, market)
    if snap["status"] == "NO_DATA":
        return {"verdict": "SKIP", "reason": "NO_FUNDAMENTALS", "snapshot": snap}
    if snap["stale"]:
        return {"verdict": "SKIP", "reason": f"STALE_{snap['days_since_release']}d", "snapshot": snap}
    if snap["latest_eps"] is None:
        return {"verdict": "SKIP", "reason": "LATEST_EPS_MISSING", "snapshot": snap}
    eps_g = snap["eps_yoy_growth_by_quarter"]
    if not eps_g:
        return {"verdict": "SKIP", "reason": "EPS_GROWTH_UNDEFINED", "snapshot": snap}

    category = "turnaround" if snap["turnaround"] else None
    res = evaluate_fundamentals(snap, category=category)
    verdict = "PASS" if res["pass"] else "FAIL"
    reason = res["overall_reason"]
    # A loss that narrows is not earnings growth: Q1 needs positive current EPS.
    if verdict == "PASS" and snap["latest_eps"] <= 0:
        verdict, reason = "FAIL", f"Q1 FAIL: current EPS {snap['latest_eps']:.4g} is a loss"
    return {"verdict": verdict, "reason": reason, "category": category,
            "detail": res, "snapshot": snap}


def event_dates(ticker: str, start: date, end: date, market) -> list[date]:
    """Simulated dates on which the screen verdict can change.

    Between these dates no new release becomes usable and the staleness flag
    cannot flip, and later splits rescale every compared EPS by the same
    factor, so growth rates, signs and annual comparisons are unchanged.
    tests/test_fundamentals_pit.py re-checks this claim on random days.
    """
    hist = get_known_history(ticker, end)
    ds = {start}
    if hist.empty:                # no fundamentals at all: one SKIP verdict for the whole range
        return sorted(ds)
    lag = (market.fundamentals_usable_from(start, False) - start).days
    for r in pd.to_datetime(hist["earnings_release_date"]).dt.date:
        for d in (r + timedelta(days=lag), r + timedelta(days=STALE_DAYS + 1)):
            if start <= d <= end:
                ds.add(d)
    return sorted(ds)


def daily_verdicts(ticker: str, trading_days: pd.DatetimeIndex, market) -> pd.DataFrame:
    """Verdict per trading day, evaluated at every event date and carried forward."""
    start, end = trading_days[0].date(), trading_days[-1].date()
    recs = []
    for d in event_dates(ticker, start, end, market):
        s = screen(ticker, d, market)
        snap = s["snapshot"]
        g = snap.get("eps_yoy_growth_by_quarter") or []
        recs.append({
            "date": pd.Timestamp(d), "fund_verdict": s["verdict"], "fund_reason": s["reason"],
            "fund_quarter": snap.get("latest_quarter"), "fund_release": snap.get("latest_release"),
            "eps_growth": g[-1] if g else None,
        })
    ev = pd.DataFrame(recs).set_index("date").sort_index()
    return ev.reindex(trading_days, method="ffill")
