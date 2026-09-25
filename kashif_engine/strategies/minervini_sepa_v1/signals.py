"""Precomputed, lookahead-safe signals for Minervini SEPA v1.

Two tables, both independent of the tunable parameters and cached:

1. Fundamentals verdict per ticker per trading day
   (kashif_engine.data.fundamentals.daily_verdicts -> the 4-question screen
   evaluated with the store's point-in-time gate at every date the verdict
   can change, carried forward between them).

2. VCP / entry-timing evaluations on every ticker-day that could possibly be
   an entry under ANY parameter set in the grid: regime open, Trend Template
   tt_1..tt_8b true, RS >= the loosest RS threshold, fundamentals PASS, and
   breakout-day volume >= the loosest multiple. evaluate_entry_timing() gets
   the last HISTORY_BARS bars ENDING ON THAT DAY -- the same 400-bar window
   kashif_strategy used -- and the loosest volume multiple; the run then
   applies its own multiple to the stored breakout volume_ratio. Exactly
   equivalent, because volume is the only part of price_ready that depends
   on the multiple.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

SIG_DIR = ROOT / "kashif_data" / "signals"
HISTORY_BARS = 400            # kashif_strategy.HISTORY_BUFFER_MAXLEN (FIX A)
CODE_VERSION = "sig-v2"       # bump when signal logic changes, invalidates caches


def _key(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, default=str).encode()).hexdigest()[:12]


# ---------------------------------------------------------------- fundamentals
def _fund_worker(args):
    ticker, days, market_name = args
    from kashif_engine.data import fundamentals as F
    from kashif_engine.markets import MARKETS
    try:
        v = F.daily_verdicts(ticker, pd.DatetimeIndex(days), MARKETS[market_name])
        v["ticker"] = ticker
        return v.reset_index(names="date")
    except Exception as e:  # noqa: BLE001 -- reported per ticker, never swallowed silently
        return pd.DataFrame([{"date": pd.Timestamp(days[0]), "ticker": ticker, "fund_verdict": "SKIP",
                              "fund_reason": f"ERROR {type(e).__name__}: {e}"}])


def fundamentals_panel(tickers, days: pd.DatetimeIndex, market, workers=8, log=print) -> pd.DataFrame:
    """Long table (date, ticker, fund_verdict, fund_reason, ...) cached on disk."""
    SIG_DIR.mkdir(parents=True, exist_ok=True)
    store_mtime = max(p.stat().st_mtime for p in (ROOT / "us_fundamentals" / "scaled_fundamentals_parquet").rglob("*.parquet"))
    key = _key(CODE_VERSION, "fund", sorted(tickers), str(days[0]), str(days[-1]), market.name, store_mtime)
    path = SIG_DIR / f"fund_{market.name}_{key}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    t0 = time.time()
    jobs = [(t, list(days), market.name) for t in tickers]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        parts = list(ex.map(_fund_worker, jobs, chunksize=8))
    out = pd.concat(parts, ignore_index=True)
    out["fund_release"] = out["fund_release"].astype(str)
    out.to_parquet(path)
    errs = out[out["fund_reason"].astype(str).str.startswith("ERROR")]
    log(f"  fundamentals panel: {len(tickers)} tickers in {time.time() - t0:.0f}s, "
        f"{errs['ticker'].nunique()} tickers with errors")
    return out


# ---------------------------------------------------------------- VCP
def _vcp_worker(args):
    ticker, dates, vmin = args
    from kashif_engine.data import prices as P
    from entry_timing import evaluate_entry_timing
    df = P.load(ticker, "US")[["Open", "High", "Low", "Close", "Volume"]]
    rows = []
    for d in dates:
        win = df.loc[:d].iloc[-HISTORY_BARS:]
        try:
            r = evaluate_entry_timing(win, volume_multiplier=vmin)
        except Exception as e:  # noqa: BLE001 -- recorded as a rejection reason
            rows.append({"ticker": ticker, "date": d, "reason": f"ERROR {type(e).__name__}: {e}"})
            continue
        b = r.get("base_details") or {}
        bd = r.get("breakout_detail") or {}
        cs = b.get("contractions") or []
        rows.append({
            "ticker": ticker, "date": d, "reason": r["reason"], "price_ready_min": bool(r["price_ready"]),
            "pivot": r["pivot_price"], "vcp_quality": r["vcp_quality_score"],
            "contractions": len(cs), "final_depth": cs[-1]["depth"] if cs else None,
            "correction_depth": b.get("correction_depth"), "base_days": b.get("duration_trading_days"),
            "flags": ";".join(b.get("flags") or []),
            "price_confirmed": bd.get("price_confirmed"), "volume_ratio": bd.get("volume_ratio"),
            "close": bd.get("close"),
        })
    return rows


def vcp_table(pre: pd.DataFrame, vmin: float, workers=8, log=print) -> pd.DataFrame:
    """Run entry timing on every pre-filtered (ticker, date) pair; cached."""
    SIG_DIR.mkdir(parents=True, exist_ok=True)
    from kashif_engine.data import prices as P
    price_fp = [(t, (P.CACHE_DIR / "US" / f"{t}.parquet").stat().st_mtime_ns)
                for t in sorted(pre["ticker"].unique())]            # re-fetched bars -> new key
    key = _key(CODE_VERSION, "vcp", vmin, pre[["ticker", "date"]].astype(str).values.tolist(), price_fp)
    path = SIG_DIR / f"vcp_US_{key}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    t0 = time.time()
    jobs = [(t, list(g["date"]), vmin) for t, g in pre.groupby("ticker")]
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for part in ex.map(_vcp_worker, jobs, chunksize=2):
            rows.extend(part)
    out = pd.DataFrame(rows)
    out.to_parquet(path)
    log(f"  VCP evaluations: {len(out)} ticker-days in {time.time() - t0:.0f}s, "
        f"{int(out['price_ready_min'].fillna(False).sum())} price-ready at x{vmin}")
    return out
