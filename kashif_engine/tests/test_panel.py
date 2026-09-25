"""Panel known answers: RS percentile (the pending 8-10 series test), the
vectorised days-since-high twin, and a no-lookahead truncation check."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kashif_engine import panel as PANEL  # noqa: E402
from market_regime_gate import compute_pullback_metrics  # noqa: E402
from trend_template_test import compute_rs_percentile  # noqa: E402


def _series(ret, n=300, start=100.0, seed=0):
    """Price path whose 252-bar return at the last bar is exactly `ret`."""
    idx = pd.bdate_range("2021-01-04", periods=n)
    p = np.full(n, start)
    p[-253:] = np.linspace(start, start * (1 + ret), 253)
    df = pd.DataFrame({"Open": p, "High": p * 1.01, "Low": p * 0.99, "Close": p,
                       "Volume": 1e5}, index=idx)
    return df


def test_rs_percentile_ten_series_known_answer():
    # 10 series, distinct 252-day returns -> percentiles 10, 20, ..., 100.
    rets = [-0.40, -0.20, -0.05, 0.00, 0.10, 0.25, 0.30, 0.55, 0.90, 1.50]
    frames = {f"S{i}": PANEL.ticker_frame(_series(r)) for i, r in enumerate(rets)}
    wide = pd.DataFrame({t: f["ret_252"] for t, f in frames.items()})
    rs = compute_rs_percentile(wide).iloc[-1]
    assert wide.iloc[-1].tolist() == pytest.approx(rets)
    assert rs.tolist() == pytest.approx([10, 20, 30, 40, 50, 60, 70, 80, 90, 100])
    # tt_9 at 70: exactly the top four pass (70, 80, 90, 100).
    assert (rs >= 70).sum() == 4


def test_rs_percentile_ties_and_missing_nine_series():
    # Ties share the average rank; a ticker without 252 bars stays NaN and
    # does not change anyone else's rank (na_option='keep').
    rets = [0.10, 0.10, 0.30, -0.10, 0.50, 0.20, 0.20, 0.20]
    frames = {f"T{i}": PANEL.ticker_frame(_series(r)) for i, r in enumerate(rets)}
    idx = frames["T0"].index
    short = _series(0.99).loc[idx[-200:]]               # listed 200 bars ago -> no 252-day return
    frames["SHORT"] = PANEL.ticker_frame(short).reindex(idx)
    wide = pd.DataFrame({t: f["ret_252"] for t, f in frames.items()})
    rs = compute_rs_percentile(wide).iloc[-1]
    assert np.isnan(rs["SHORT"])
    # 8 valid: -0.10 (1), 0.10 x2 (2,3 -> 2.5), 0.20 x3 (4,5,6 -> 5), 0.30 (7), 0.50 (8)
    exp = {"T3": 1 / 8, "T0": 2.5 / 8, "T1": 2.5 / 8, "T5": 5 / 8, "T6": 5 / 8, "T7": 5 / 8,
           "T2": 7 / 8, "T4": 8 / 8}
    for t, v in exp.items():
        assert rs[t] == pytest.approx(v * 100)


def test_days_since_high_matches_original_on_plateau():
    # 10-day flat peak followed by a 10-day pullback -> 10, not 19 (config v0.16 example).
    p = pd.Series(np.r_[np.linspace(80, 100, 30), np.full(10, 100.0), np.linspace(99, 91, 10)])
    orig = compute_pullback_metrics(p, window=20)["days_since_local_high"]
    vec = PANEL._days_since_max(p.to_numpy(), 20)
    assert np.allclose(orig.to_numpy(), vec, equal_nan=True)
    assert vec[-1] == 10


def test_panel_rows_do_not_change_when_future_is_removed():
    """Every panel column on day t must be identical when bars after t are deleted."""
    from kashif_engine.data import prices as P
    for t in ("NVDA", "AAON", "SMCI"):
        full = P.load(t)
        a = PANEL.ticker_frame(full)
        for cut in ("2022-06-15", "2023-08-23", "2024-06-06"):
            b = PANEL.ticker_frame(full.loc[:cut])
            day = b.index[-1]
            ra, rb = a.loc[day], b.loc[day]
            for col in b.columns:
                va, vb = ra[col], rb[col]
                if isinstance(va, float) and np.isnan(va):
                    assert np.isnan(vb), (t, cut, col)
                else:
                    assert va == pytest.approx(vb), (t, cut, col)


def test_vtol_reverse_split_correction():
    """Yahoo booked Era Group's 1-for-3 reverse split (2020-06-11) as 1-for-2,
    leaving a fake +55% overnight jump. Corrected at load time: ~+3.5%."""
    from kashif_engine.data import prices as P
    f = P.load("VTOL")
    jump = f.loc["2020-06-12", "Close"] / f.loc["2020-06-11", "Close"] - 1
    assert abs(jump) < 0.10
    raw = pd.read_parquet(P.CACHE_DIR / "US" / "VTOL.parquet")
    assert raw.loc["2020-06-12", "Close"] / raw.loc["2020-06-11", "Close"] - 1 > 0.5    # cache untouched
    assert f.loc["2022-01-03":].equals(P.add_raw_columns(raw).loc["2022-01-03":])       # 2022+ unchanged
