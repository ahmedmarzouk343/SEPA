"""Lookahead-safe signal panels, computed once per universe and cached.

Every column is a TRAILING computation (rolling windows ending at the row's own
bar, shifts into the past, cross-sectional ranks over the same row), so the
value on day t uses only bars <= t. The per-bar strategy then reads one row
instead of recomputing 400-bar windows for ~1,000 tickers every day, which is
what made the old monolithic strategy too slow for a full-universe run.

The indicator math is NOT re-implemented here: it calls the project's
canonical functions (trend_template_test.compute_indicators /
evaluate_conditions / compute_rs_percentile and the market_regime_gate
condition helpers) on each ticker's own bar sequence.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trend_template_test import compute_indicators, evaluate_conditions, compute_rs_percentile  # noqa: E402
from market_regime_gate import (  # noqa: E402
    compute_new_high_low_ratio, new_high_low_ratio_favorable, compute_higher_low,
    market_regime_gate, RS_LEADER_THRESHOLD, PULLBACK_DEPTH_MAX,
    PULLBACK_DURATION_MAX_DAYS, LOCAL_HIGH_WINDOW, DIVERGENCE_WINDOW,
    DIVERGENCE_PIVOT_LEADER, DIVERGENCE_PIVOT_UNIVERSE, REGIME_GATE_MIN_CONDITIONS,
)
from kashif_engine.data import prices as P  # noqa: E402

PANEL_DIR = ROOT / "kashif_data" / "panels"
TT_CORE = ["tt_1", "tt_2", "tt_3", "tt_4", "tt_5", "tt_6", "tt_7", "tt_8a", "tt_8b"]
HIGHLOW_WINDOW = 253          # kashif_strategy: close vs the last 253 closes
VOLUME_WINDOW = 50            # vcp_detection.BREAKOUT_VOLUME_WINDOW (incl. today)
ATR_PERIOD = 14


def _days_since_max(values: np.ndarray, window: int) -> np.ndarray:
    """Vectorised twin of market_regime_gate.compute_pullback_metrics'
    _days_since_max: offset of the MOST RECENT max inside each trailing window
    (ties resolve to the newest bar). Checked against the original in
    tests/test_panel.py."""
    n = len(values)
    out = np.full(n, np.nan)
    if n < window:
        return out
    from numpy.lib.stride_tricks import sliding_window_view
    w = sliding_window_view(values, window)[:, ::-1]      # newest first
    out[window - 1:] = np.argmax(w, axis=1)
    out[window - 1:][np.isnan(w).any(axis=1)] = np.nan
    return out


def ticker_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Per-ticker trailing indicators on the ticker's OWN bar sequence."""
    x = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    ind = compute_indicators(x)
    cond, evaluable_wo_rs, _ = evaluate_conditions(ind, pd.Series(np.nan, index=ind.index))
    out = pd.DataFrame(index=x.index)
    for c in ("Open", "High", "Low", "Close", "Volume"):
        out[c] = x[c]
    for c in ("sma_50", "sma_150", "sma_200", "high_52wk", "low_52wk", "ret_252"):
        out[c] = ind[c]
    # tt_1..tt_8b all true, and every raw indicator they need is real.
    raw_ok = ind[["sma_150", "sma_200", "high_52wk", "low_52wk"]].notna().all(axis=1)
    out["tt_core"] = cond[TT_CORE].all(axis=1) & raw_ok
    out["tt_core_n"] = cond[TT_CORE].sum(axis=1)
    out["sma_20"] = x["Close"].rolling(20).mean()
    out["avgvol50"] = x["Volume"].rolling(VOLUME_WINDOW).mean()
    out["vol_ratio"] = x["Volume"] / out["avgvol50"]
    out["addv50"] = (x["Close"] * x["Volume"]).rolling(VOLUME_WINDOW).mean()
    prev_close = x["Close"].shift(1)
    tr = pd.concat([x["High"] - x["Low"], (x["High"] - prev_close).abs(),
                    (x["Low"] - prev_close).abs()], axis=1).max(axis=1)
    # simple mean of the last 14 true ranges over price -- kashif_strategy._atr_pct
    out["atr14_pct"] = tr.rolling(ATR_PERIOD).mean() / x["Close"]
    c = x["Close"]
    out["new_high"] = (c >= c.rolling(HIGHLOW_WINDOW).max()) & (c.rolling(HIGHLOW_WINDOW).count() == HIGHLOW_WINDOW)
    out["new_low"] = (c <= c.rolling(HIGHLOW_WINDOW).min()) & (c.rolling(HIGHLOW_WINDOW).count() == HIGHLOW_WINDOW)
    lh = c.rolling(LOCAL_HIGH_WINDOW).max()
    out["pullback_depth"] = (lh - c) / lh
    out["days_since_high"] = _days_since_max(c.to_numpy(dtype=float), LOCAL_HIGH_WINDOW)
    out["higher_low"] = compute_higher_low(c, window=DIVERGENCE_WINDOW)
    out["nbars"] = np.arange(1, len(x) + 1)
    return out


def build(tickers, market="US", calendar_ticker="SPY", log=print) -> dict:
    """Build (or load) the panel. Returns dict of wide DataFrames + regime."""
    cache = PANEL_DIR / market
    cache.mkdir(parents=True, exist_ok=True)
    frames = {}
    for i, t in enumerate(tickers):
        f = P.load(t, market)
        if f is None or len(f) < 2:
            continue
        frames[t] = ticker_frame(f)
        if (i + 1) % 200 == 0:
            log(f"  panel: {i + 1}/{len(tickers)} tickers")
    cal = P.load(calendar_ticker, market).index
    wide = {}
    for col in ("Open", "High", "Low", "Close", "Volume", "sma_20", "sma_50", "avgvol50", "vol_ratio",
                "addv50", "atr14_pct", "tt_core", "tt_core_n", "ret_252", "new_high", "new_low",
                "pullback_depth", "days_since_high", "higher_low", "nbars"):
        wide[col] = pd.DataFrame({t: fr[col] for t, fr in frames.items()}).reindex(cal)
    # tt_9 input: RS percentile across the FULL universe, per date, among the
    # tickers that have a 252-bar return that day (na_option='keep').
    wide["rs_pct"] = compute_rs_percentile(wide["ret_252"])
    wide["regime"] = regime(wide)
    for k, v in wide.items():
        v.to_parquet(cache / f"{k}.parquet")
    return wide


def load(market="US") -> dict:
    cache = PANEL_DIR / market
    return {p.stem: pd.read_parquet(p) for p in cache.glob("*.parquet")}


def regime(w: dict) -> pd.DataFrame:
    """market_regime_gate's three conditions per date (OR gate by default)."""
    nb = w["nbars"]
    # 1. new-high/new-low ratio vs 21 bars earlier.
    counts_h = w["new_high"].fillna(False).astype(bool).sum(axis=1)
    counts_l = w["new_low"].fillna(False).astype(bool).sum(axis=1)
    ratio = compute_new_high_low_ratio(counts_h.astype(float), counts_l.astype(float))
    ratio_fav = new_high_low_ratio_favorable(ratio).fillna(False)
    # kashif_strategy needs 22 accumulated days of counts before judging.
    have_counts = (w["nbars"] >= HIGHLOW_WINDOW).any(axis=1)
    ratio_fav &= have_counts.rolling(22).sum().fillna(0) >= 22
    # 2. leader basket (RS >= 90, >= 20 bars) average pullback depth/duration.
    leaders = (w["rs_pct"] >= RS_LEADER_THRESHOLD) & (nb >= LOCAL_HIGH_WINDOW)
    depth = w["pullback_depth"].where(leaders)
    dur = w["days_since_high"].where(leaders)
    avg_depth, avg_dur = depth.mean(axis=1), dur.mean(axis=1)
    pullback = (avg_depth <= PULLBACK_DEPTH_MAX) & (avg_dur <= PULLBACK_DURATION_MAX_DAYS)
    # 3. leaders making higher lows while the universe is not.
    hl = w["higher_low"].where(nb >= 2 * DIVERGENCE_WINDOW)   # needs 40 bars, else excluded
    lead_hl = hl.where(leaders & (nb >= 2 * DIVERGENCE_WINDOW))
    universe_hl_pct = hl.astype(float).mean(axis=1)
    leader_hl_pct = lead_hl.astype(float).mean(axis=1)
    divergence = (leader_hl_pct > DIVERGENCE_PIVOT_LEADER) & (universe_hl_pct < DIVERGENCE_PIVOT_UNIVERSE)
    n_leaders = leaders.sum(axis=1)
    gate = pd.Series([market_regime_gate(a, b, c, REGIME_GATE_MIN_CONDITIONS)[0]
                      for a, b, c in zip(ratio_fav, pullback.fillna(False), divergence.fillna(False))],
                     index=ratio.index)
    gate &= n_leaders > 0      # no leader basket yet = insufficient history = closed
    return pd.DataFrame({
        "new_highs": counts_h, "new_lows": counts_l, "hl_ratio": ratio, "ratio_favorable": ratio_fav,
        "n_leaders": n_leaders, "leader_avg_depth": avg_depth, "leader_avg_days": avg_dur,
        "pullback_shallow": pullback.fillna(False), "leader_hl_pct": leader_hl_pct,
        "universe_hl_pct": universe_hl_pct, "divergence": divergence.fillna(False), "gate_open": gate,
    })
