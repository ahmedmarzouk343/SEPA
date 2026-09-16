"""
Known-answer regression test for Feature 5 (Entry Timing / VCP Detection):
vcp_detection.py and entry_timing.py.

Tests: detect_swings, identify_bases, validate_base, find_pivot, check_breakout,
score_vcp_quality (end-to-end and direct), plus entry_timing orchestrator for
tick-quantized pre-filter and dual-timeframe weekly gate.

See original docstring for construction notes on smoothing lag, rolling-median
effects on detected indices/depths, and fixture design rationale.
"""

import itertools
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

import vcp_detection as vd  # noqa: E402
import entry_timing as et  # noqa: E402
from vcp_detection import (  # noqa: E402
    detect_swings, identify_bases, validate_base, find_pivot, check_breakout,
    score_vcp_quality, MONOTONICITY_RULE_B_TOLERANCE, VOLUME_DRYUP_RATIO,
)

TOL = 1e-6


def ramp(start_val, end_val, n_bars):
    step = (end_val - start_val) / n_bars
    return [start_val + step * i for i in range(1, n_bars + 1)]


def build_df(closes, volumes=None, start="2024-01-01", hl_pct=0.003):
    n = len(closes)
    dates = pd.date_range(start, periods=n, freq="B")
    closes_s = pd.Series(closes, index=dates, dtype=float)
    opens = closes_s.shift(1).fillna(closes_s.iloc[0])
    highs = pd.concat([opens, closes_s], axis=1).max(axis=1) * (1 + hl_pct)
    lows = pd.concat([opens, closes_s], axis=1).min(axis=1) * (1 - hl_pct)
    if volumes is None:
        volumes = [100000.0] * n
    vols = pd.Series(volumes, index=dates, dtype=float)
    return pd.DataFrame({"Open": opens, "High": highs, "Low": lows, "Close": closes_s, "Volume": vols})


def build_series_df(n_bars, event_points, hl_pct=0.003):
    idxs = sorted(event_points.keys())
    closes = np.full(n_bars, np.nan)
    for idx in idxs:
        closes[idx] = event_points[idx]
    closes = pd.Series(closes).interpolate(method="linear", limit_direction="both").values
    jitter = np.array([((i * 37) % 100) / 100000.0 for i in range(n_bars)])
    closes = closes + jitter
    return build_df(list(closes), volumes=[100000.0] * n_bars, hl_pct=hl_pct)


# ---- Fixture 1 data ----

def _fixture1_data():
    warmup = [100.0] * 25
    leg_up0 = ramp(100, 140, 12)
    leg_dn1 = ramp(140, 112, 10)
    leg_up1 = ramp(112, 130, 10)
    leg_dn2 = ramp(130, 114.4, 10)
    leg_up2 = ramp(114.4, 125, 10)
    leg_dn3 = ramp(125, 117.5, 8)
    settle = ramp(117.5, 135, 10)
    closes = warmup + leg_up0 + leg_dn1 + leg_up1 + leg_dn2 + leg_up2 + leg_dn3 + settle
    volumes = ([100000.0] * (len(closes) - len(leg_dn3) - len(settle))
               + [55000.0] * len(leg_dn3) + [100000.0] * len(settle))
    return build_df(closes, volumes)


def test_fixture1_peak_trough_detection():
    df = _fixture1_data()
    peaks, troughs = detect_swings(df["Close"], df["High"], df["Low"], df["Volume"],
                                   vd.ATR_PERIOD, vd.ATR_MULTIPLIER, vd.SMOOTHING_WINDOW, vd.DISTANCE_DAYS)
    assert list(peaks) == [38, 58, 78]
    assert list(troughs) == [48, 68, 86]


def test_fixture1_base_validation():
    df = _fixture1_data()
    peaks, troughs = detect_swings(df["Close"], df["High"], df["Low"], df["Volume"],
                                   vd.ATR_PERIOD, vd.ATR_MULTIPLIER, vd.SMOOTHING_WINDOW, vd.DISTANCE_DAYS)
    bases = identify_bases(peaks, troughs, df["High"])
    assert len(bases) == 1
    v = validate_base(bases[0], df, df.index)
    assert v["valid"] is True
    depths = [round(c["depth"] * 100, 2) for c in v["contractions"]]
    assert abs(depths[0] - 17.55) < 0.01
    assert abs(depths[1] - 10.64) < 0.01
    assert abs(depths[2] - 4.45) < 0.01
    assert v["duration_trading_days"] == 48
    assert abs(v["correction_depth"] * 100 - 17.55) < 0.01


def test_fixture1_pivot_and_score():
    df = _fixture1_data()
    peaks, troughs = detect_swings(df["Close"], df["High"], df["Low"], df["Volume"],
                                   vd.ATR_PERIOD, vd.ATR_MULTIPLIER, vd.SMOOTHING_WINDOW, vd.DISTANCE_DAYS)
    bases = identify_bases(peaks, troughs, df["High"])
    v = validate_base(bases[0], df, df.index)
    pivot = find_pivot(v, df)
    assert abs(pivot - 124.4346875) < 0.01
    q = score_vcp_quality(v)
    assert q["vcp_quality_score"] == 2.0
    assert q["depth_score"] == 1.0
    assert q["contraction_count_score"] == 1.0


# ---- Fixture 2 ----

def _fixture2_data():
    warmup2 = [80.0] * 25
    leg_up0 = ramp(80, 100, 10)
    leg_dn1 = ramp(100, 85, 10)
    leg_up1 = ramp(85, 95, 10)
    leg_dn2 = ramp(95, 87.4, 10)
    leg_up2 = ramp(87.4, 92, 10)
    leg_dn3 = ramp(92, 81.88, 8)
    settle = ramp(81.88, 100, 10)
    closes = warmup2 + leg_up0 + leg_dn1 + leg_up1 + leg_dn2 + leg_up2 + leg_dn3 + settle
    return build_df(closes)


def test_fixture2_oscillating_accepted_at_150():
    df = _fixture2_data()
    peaks, troughs = detect_swings(df["Close"], df["High"], df["Low"], df["Volume"],
                                   vd.ATR_PERIOD, vd.ATR_MULTIPLIER, vd.SMOOTHING_WINDOW, vd.DISTANCE_DAYS)
    bases = identify_bases(peaks, troughs, df["High"])
    assert len(bases) == 1
    v = validate_base(bases[0], df, df.index)
    depths = [round(c["depth"] * 100, 2) for c in v.get("contractions", [])]
    assert abs(depths[0] - 13.21) < 0.01
    assert abs(depths[1] - 7.33) < 0.01
    assert abs(depths[2] - 9.57) < 0.01
    assert v["valid"] is True
    assert v["rejection_reason"] is None
    assert v.get("rejection_detail") is None
    assert 9.57 <= 13.21 * 0.75  # rule_a passes
    assert 9.57 <= 7.33 * 1.50   # rule_b passes at 1.50
    assert 9.57 > 7.33 * 1.30    # would fail at old 1.30


# ---- Fixture 3 ----

def test_fixture3a_duration_minimum_boundary():
    events_a = {0: 100.0, 3: 100.0, 7: 80.0, 10: 95.0, 15: 85.5}
    df = build_series_df(40, events_a)
    base = {"start_trough_idx": 0, "end_trough_idx": 15,
            "contractions": [{"peak_idx": 3, "trough_idx": 7}, {"peak_idx": 10, "trough_idx": 15}]}
    v = validate_base(base, df, df.index)
    assert v["valid"] is True
    assert v["duration_trading_days"] == 15
    assert any("SHORT_DURATION" in f for f in v["flags"])


def test_fixture3b_duration_over_max():
    events_b = {0: 100.0, 5: 100.0, 15: 80.0, 160: 95.0, 326: 85.5}
    df = build_series_df(340, events_b)
    base = {"start_trough_idx": 0, "end_trough_idx": 326,
            "contractions": [{"peak_idx": 5, "trough_idx": 15}, {"peak_idx": 160, "trough_idx": 326}]}
    v = validate_base(base, df, df.index)
    assert v["valid"] is False
    assert v["rejection_reason"] == "BASE_TOO_LONG"


# ---- Fixture 4 ----

def test_fixture4a_depth_too_deep():
    events = {0: 100.0, 3: 100.0, 10: 39.0, 20: 60.0, 30: 54.0}
    df = build_series_df(40, events)
    base = {"start_trough_idx": 0, "end_trough_idx": 30,
            "contractions": [{"peak_idx": 3, "trough_idx": 10}, {"peak_idx": 20, "trough_idx": 30}]}
    v = validate_base(base, df, df.index)
    assert v["valid"] is False
    assert v["rejection_reason"] == "CORRECTION_TOO_DEEP"


def test_fixture4b_depth_caution_zone():
    events = {0: 100.0, 3: 100.0, 10: 41.0, 20: 60.0, 30: 54.0}
    df = build_series_df(40, events)
    base = {"start_trough_idx": 0, "end_trough_idx": 30,
            "contractions": [{"peak_idx": 3, "trough_idx": 10}, {"peak_idx": 20, "trough_idx": 30}]}
    v = validate_base(base, df, df.index)
    assert v["valid"] is True
    assert abs(v["correction_depth"] * 100 - 59.24) < 0.05
    assert any("CORRECTION_DEPTH_CAUTION" in f for f in v["flags"])


# ---- Fixture 5 ----

def test_fixture5_volume_confirmation():
    n = 55
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    base_df = pd.DataFrame({"Open": [100.0] * n, "High": [100.3] * n, "Low": [99.7] * n,
                            "Close": [100.0] * n, "Volume": [100000.0] * n}, index=dates)
    pivot = 105.0

    for vol, expected_breakout in [(150000.0, True), (120000.0, False)]:
        extra = pd.DataFrame({"Open": [100.0], "High": [111.0], "Low": [99.5], "Close": [110.0], "Volume": [vol]},
                             index=pd.date_range(dates[-1] + pd.Timedelta(days=1), periods=1, freq="B"))
        df = pd.concat([base_df, extra])
        confirmed, detail = check_breakout(df, df["Volume"], pivot)
        assert detail["price_confirmed"] is True
        assert confirmed == expected_breakout


# ---- Fixture 6 ----

def test_fixture6_squat_tolerance():
    n = 55
    dates = pd.date_range("2024-02-01", periods=n, freq="B")
    base_df = pd.DataFrame({"Open": [100.0] * n, "High": [100.3] * n, "Low": [99.7] * n,
                            "Close": [100.0] * n, "Volume": [100000.0] * n}, index=dates)
    squat = pd.DataFrame({"Open": [100.0], "High": [106.0], "Low": [99.5], "Close": [104.0], "Volume": [130000.0]},
                         index=pd.date_range(dates[-1] + pd.Timedelta(days=1), periods=1, freq="B"))
    flat_gap = pd.DataFrame({"Open": [104.0, 104.0], "High": [104.5, 104.5], "Low": [103.5, 103.5],
                             "Close": [104.0, 104.0], "Volume": [100000.0, 100000.0]},
                            index=pd.date_range(squat.index[-1] + pd.Timedelta(days=1), periods=2, freq="B"))
    confirm = pd.DataFrame({"Open": [104.0], "High": [109.0], "Low": [103.5], "Close": [108.0], "Volume": [150000.0]},
                           index=pd.date_range(flat_gap.index[-1] + pd.Timedelta(days=1), periods=1, freq="B"))
    df = pd.concat([base_df, squat, flat_gap, confirm])
    pivot = 105.0

    squat_confirmed, squat_detail = check_breakout(df, df["Volume"], pivot, index=n)
    assert squat_detail["price_confirmed"] is False
    assert squat_confirmed is False

    confirm_confirmed, confirm_detail = check_breakout(df, df["Volume"], pivot, index=n + 3)
    assert confirm_detail["price_confirmed"] is True
    assert confirm_detail["volume_confirmed"] is True
    assert confirm_confirmed is True


# ---- Fixture 7 ----

def _fixture7_data():
    warmup = [60.0] * 25
    leg_up0 = ramp(60, 100, 10)
    leg_dn1 = ramp(100, 70.2, 10)
    leg_up1 = ramp(70.2, 85, 10)
    leg_dn2 = ramp(85, 73.78, 8)
    leg_up2 = ramp(73.78, 90, 8)
    leg_dn3 = ramp(90, 75.03, 8)
    settle = ramp(75.03, 100, 10)
    closes = warmup + leg_up0 + leg_dn1 + leg_up1 + leg_dn2 + leg_up2 + leg_dn3 + settle
    return build_df(closes)


def test_fixture7_swdy_boundary():
    df = _fixture7_data()
    peaks, troughs = detect_swings(df["Close"], df["High"], df["Low"], df["Volume"],
                                   vd.ATR_PERIOD, vd.ATR_MULTIPLIER, vd.SMOOTHING_WINDOW, vd.DISTANCE_DAYS)
    bases = identify_bases(peaks, troughs, df["High"])
    assert len(bases) == 1

    v_150 = validate_base(bases[0], df, df.index)
    depths = [round(c["depth"] * 100, 2) for c in v_150.get("contractions", [])]
    assert abs(depths[0] - 25.04) < 0.01
    assert abs(depths[1] - 9.86) < 0.01
    assert abs(depths[2] - 12.56) < 0.01
    assert MONOTONICITY_RULE_B_TOLERANCE == 1.50
    assert v_150["valid"] is True

    original = vd.MONOTONICITY_RULE_B_TOLERANCE
    try:
        vd.MONOTONICITY_RULE_B_TOLERANCE = 1.10
        v_110 = validate_base(bases[0], df, df.index)
    finally:
        vd.MONOTONICITY_RULE_B_TOLERANCE = original
    assert v_110["valid"] is False
    assert v_110["rejection_reason"] == "MONOTONICITY_FAILED"


# ---- Fixture 8 ----

def test_fixture8_tick_quantized():
    tick_values = [0.030, 0.031, 0.032, 0.033, 0.034, 0.035, 0.036, 0.037, 0.038]
    closes = list(itertools.islice(itertools.cycle(tick_values), 300))
    df = build_df(closes, hl_pct=0.0)
    df["Close"] = closes
    assert df["Close"].nunique() == 9

    real_detect = vd.detect_swings
    call_count = {"n": 0}

    def spy(*args, **kwargs):
        call_count["n"] += 1
        return real_detect(*args, **kwargs)

    et.detect_swings = spy
    try:
        result = et.evaluate_entry_timing(df)
    finally:
        et.detect_swings = real_detect

    assert result["reason"] == "TICK_QUANTIZED"
    assert result["price_ready"] is False
    assert call_count["n"] == 0


# ---- Fixture 9 ----

def test_fixture9_dual_timeframe_weekly_gate():
    n = 100
    trend = [400.0 - 1.0 * i for i in range(n)]
    spike = [0.0] * n
    spike_start, rise_len, fall_len = 40, 8, 8
    for i in range(rise_len):
        spike[spike_start + i] = 70.0 * (i + 1) / rise_len
    for i in range(fall_len):
        spike[spike_start + rise_len + i] = 70.0 * (1 - (i + 1) / fall_len)
    closes = [trend[i] + spike[i] for i in range(n)]
    for i in range(4, n, 5):
        closes[i] = trend[i]
    df = build_df(closes)

    weekly = et.to_weekly(df)
    assert bool((weekly["Close"].diff().dropna() < 0).all())

    w_peaks, w_troughs = detect_swings(weekly["Close"], weekly["High"], weekly["Low"], weekly["Volume"],
                                       vd.ATR_PERIOD, vd.ATR_MULTIPLIER, vd.DISTANCE_WEEKS, vd.DISTANCE_WEEKS)
    assert list(w_peaks) == []
    assert list(w_troughs) == []

    d_peaks, d_troughs = detect_swings(df["Close"], df["High"], df["Low"], df["Volume"],
                                       vd.ATR_PERIOD, vd.ATR_MULTIPLIER, vd.SMOOTHING_WINDOW, vd.DISTANCE_DAYS)
    assert list(d_peaks) == [49]
    assert list(d_troughs) == [40]

    real_detect = vd.detect_swings
    call_count = {"n": 0}

    def spy(*args, **kwargs):
        call_count["n"] += 1
        return real_detect(*args, **kwargs)

    et.detect_swings = spy
    try:
        result = et.evaluate_entry_timing(df)
    finally:
        et.detect_swings = real_detect

    assert result["reason"] == "NO_WEEKLY_BASE"
    assert result["price_ready"] is False
    assert call_count["n"] == 1


# ==================================================================
# EGX FIXTURES A-D -- weekly-primary architecture (Fix 3)
# ==================================================================
#
# Daily data is built so that when resampled to weekly via to_weekly():
#   - Weeks 1-5: flat warmup at 100 (establishes ATR baseline)
#   - Weeks 6-10: rally to 140
#   - Weeks 11-14: single contraction: peak ~140, trough ~120
#   - Weeks 15-18: recovery + breakout above pivot
#
# For volume dry-up tests, the contraction weeks get LOW volume vs.
# the base average.  Fixture B inverts this (HIGH volume in contraction).
#
# Total ~90 daily bars (18 weeks * 5).
#
# --------------------------------------------------------------------------
# CONSTRUCTION NOTE -- CONTRACTION_COUNT_MIN default
# --------------------------------------------------------------------------
# The non-EGX path (Fixture D) calls validate_base on DAILY bars with the
# default CONTRACTION_COUNT_MIN=2.  A daily series built from these weekly
# swings will have exactly 1 daily contraction (the same one, just on daily
# resolution) and will be rejected with CONTRACTION_COUNT_OUT_OF_RANGE.
# This is the precise blocker Fix 3 solves for EGX.

def _egx_fixture_daily(contraction_volume=40000, base_volume=100000):
    """Build ~170 daily bars producing a 1-contraction weekly VCP base.

    Shape (weekly): drift up 80→100 (10 wk warmup) → dip to 90 (2 wk,
    creates a TROUGH so the base includes the rally) → rally to 140 (5 wk)
    → contraction to 120 (3 wk, LOW volume) → recovery 120→135 (2 wk)
    → flat 135→136 (5 wk) → breakout above pivot (3 wk, HIGH volume).

    The dip-then-rally gives identify_bases() a preceding trough, so the
    base spans trough(90)→peak(140)→trough(120).  Base average volume
    includes the rally weeks (high vol) and contraction weeks (low vol),
    making the dry-up ratio meaningful."""
    closes = (
        ramp(80, 100, 50)      # 10 wk: warmup drift
        + ramp(100, 90, 10)    #  2 wk: dip (creates preceding trough)
        + ramp(90, 140, 25)    #  5 wk: rally to peak
        + ramp(140, 120, 15)   #  3 wk: contraction (low volume)
        + ramp(120, 135, 10)   #  2 wk: recovery
        + ramp(135, 136, 25)   #  5 wk: flat (diversity)
        + ramp(136, 150, 15)   #  3 wk: breakout
    )

    volumes = (
        [base_volume] * 50          # warmup
        + [base_volume] * 10        # dip
        + [base_volume] * 25        # rally
        + [contraction_volume] * 15 # contraction
        + [base_volume] * 10        # recovery
        + [base_volume] * 25        # flat
        + [int(base_volume * 2.0)] * 15  # breakout
    )
    return build_df(closes, volumes)


def test_fixture_egx_a_weekly_primary_dryup_passes():
    """EGX weekly-primary: 1 contraction + volume dry-up → PRICE_READY."""
    df = _egx_fixture_daily(contraction_volume=40000, base_volume=100000)
    result = et.evaluate_entry_timing(df, market="EGX")

    assert result["price_ready"] is True
    assert result["reason"] == "PRICE_READY"
    assert result["pivot_price"] is not None
    assert result["base_details"] is not None
    assert result["base_details"]["contraction_count"] == 1


def test_fixture_egx_b_no_volume_dryup_rejected():
    """EGX weekly-primary: 1 contraction but HIGH volume in contraction → rejected."""
    df = _egx_fixture_daily(contraction_volume=150000, base_volume=100000)
    result = et.evaluate_entry_timing(df, market="EGX")

    assert result["price_ready"] is False
    assert "NO_VOLUME_DRYUP" in result["reason"]


def test_fixture_egx_c_no_weekly_base_short_circuits():
    """EGX: if weekly has no base, short-circuit before any daily work."""
    n = 100
    trend = [400.0 - 1.0 * i for i in range(n)]
    closes = trend
    df = build_df(closes)

    real_detect = vd.detect_swings
    call_count = {"n": 0}

    def spy(*args, **kwargs):
        call_count["n"] += 1
        return real_detect(*args, **kwargs)

    et.detect_swings = spy
    try:
        result = et.evaluate_entry_timing(df, market="EGX")
    finally:
        et.detect_swings = real_detect

    assert result["price_ready"] is False
    assert result["reason"] == "NO_WEEKLY_BASE"
    assert call_count["n"] == 1


def test_fixture_egx_d_non_egx_still_requires_two_contractions():
    """Non-EGX path: same 1-contraction data → daily rejected for count."""
    df = _egx_fixture_daily(contraction_volume=40000, base_volume=100000)
    result = et.evaluate_entry_timing(df, market=None)

    assert result["price_ready"] is False
    assert "CONTRACTION_COUNT" in result["reason"] or "NO_DAILY_BASE" in result["reason"]


# ==========================================================================
# SINGLE-CONTRACTION VOLUME DRY-UP ALLOWANCE
#
# Predictions hand-derived from validate_base()'s filter ORDER before running:
# tick-quantize (a) -> max duration (b) -> correction depth (c) -> min
# duration flag (d) -> monotonicity (e, skipped at 1 contraction) -> count (f,
# where the allowance lives) -> volume dry-up (g). Because (c) precedes (f), an
# over-deep base is rejected as CORRECTION_TOO_DEEP and never reaches the
# allowance at all -- that ordering is what fixture SC4 pins.
# ==========================================================================

PRE_BASE_BARS = 60          # >= 50, so the pre-base volume window is full
BASE_START = 60
CONTRACTION_PEAK = 80
BASE_END = 100
TOTAL_BARS = 130


def _sc_prices(contraction_volume, pre_base_volume, trough_low=80.0, peak_high=100.0):
    """
    Price/volume frame for the allowance fixtures.

    Closes are all distinct (clears the tick-quantized pre-filter). High/Low
    are pinned at the contraction's peak and trough so correction depth is
    exactly (peak_high - trough_low) / peak_high. Volume is `pre_base_volume`
    everywhere except bars CONTRACTION_PEAK..BASE_END, which carry
    `contraction_volume`.
    """
    closes = [50.0 + 0.37 * i for i in range(TOTAL_BARS)]
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]
    highs[CONTRACTION_PEAK] = peak_high
    lows[BASE_END] = trough_low

    volumes = [float(pre_base_volume)] * TOTAL_BARS
    for i in range(CONTRACTION_PEAK, BASE_END + 1):
        volumes[i] = float(contraction_volume)

    idx = pd.date_range("2024-01-01", periods=TOTAL_BARS, freq="B")
    return pd.DataFrame(
        {"Open": closes, "High": highs, "Low": lows, "Close": closes, "Volume": volumes},
        index=idx,
    )


def _sc_base_one_contraction():
    return {"start_trough_idx": BASE_START, "end_trough_idx": BASE_END,
            "contractions": [{"peak_idx": CONTRACTION_PEAK, "trough_idx": BASE_END}]}


def _sc_base_two_contractions(prices):
    """
    Two contractions with decreasing depth, so monotonicity rules A and B both
    pass and the base is valid on its own merits with the flag off.
    """
    p1, t1, p2, t2 = 66, 74, 82, 90
    hi = prices.columns.get_loc("High")
    lo = prices.columns.get_loc("Low")
    prices.iloc[p1, hi] = 100.0
    prices.iloc[t1, lo] = 75.0     # depth 0.25
    prices.iloc[p2, hi] = 98.0
    prices.iloc[t2, lo] = 88.2     # depth 0.10  (0.10 <= 0.25 * 0.75)
    return {"start_trough_idx": BASE_START, "end_trough_idx": t2,
            "contractions": [{"peak_idx": p1, "trough_idx": t1},
                             {"peak_idx": p2, "trough_idx": t2}]}


def test_fixture_sc1_two_contractions_identical_either_way():
    """
    SC1 -- PREDICTION: a 2-contraction base is outside the allowance's reach
    entirely (it only fires at count == 1), so validity, contraction count,
    correction depth and rejection reason are identical with the flag on and
    off, and no allowance flag is ever attached.
    """
    off_prices = _sc_prices(40000, 100000)
    base_off = _sc_base_two_contractions(off_prices)
    on_prices = _sc_prices(40000, 100000)
    base_on = _sc_base_two_contractions(on_prices)

    off = validate_base(base_off, off_prices, off_prices.index,
                        single_contraction_dryup_allowance=False)
    on = validate_base(base_on, on_prices, on_prices.index,
                       single_contraction_dryup_allowance=True)

    assert off["valid"] is True and on["valid"] is True
    assert off["contraction_count"] == on["contraction_count"] == 2
    assert off["rejection_reason"] is None and on["rejection_reason"] is None
    assert abs(off["correction_depth"] - on["correction_depth"]) < TOL
    assert not any("SINGLE_CONTRACTION_DRYUP_ALLOWANCE" in f for f in on["flags"])
    assert off["flags"] == on["flags"]


def test_fixture_sc2_one_contraction_dried_up_flag_on_allowed():
    """
    SC2 -- PREDICTION: 1 contraction, median contraction volume 40,000 against
    a pre-base 50-bar average of 100,000, depth (100-80)/100 = 20% (inside the
    60% ceiling). With the flag on the base is now VALID, count stays honestly
    reported as 1, and the allowance is recorded in flags.
    """
    prices = _sc_prices(contraction_volume=40000, pre_base_volume=100000)
    res = validate_base(_sc_base_one_contraction(), prices, prices.index,
                        single_contraction_dryup_allowance=True)

    assert res["valid"] is True
    assert res["rejection_reason"] is None
    assert res["contraction_count"] == 1
    assert abs(res["correction_depth"] - 0.20) < TOL
    allowance = [f for f in res["flags"] if f.startswith("SINGLE_CONTRACTION_DRYUP_ALLOWANCE")]
    assert len(allowance) == 1
    assert "40000" in allowance[0] and "100000" in allowance[0]


def test_fixture_sc3_one_contraction_no_dryup_still_rejected():
    """
    SC3 -- PREDICTION: same base, but contraction median volume 150,000 against
    the same 100,000 pre-base average -- volume EXPANDED. The allowance does
    not apply and the base is rejected as CONTRACTION_COUNT_OUT_OF_RANGE,
    exactly as with the flag off.
    """
    prices = _sc_prices(contraction_volume=150000, pre_base_volume=100000)
    res = validate_base(_sc_base_one_contraction(), prices, prices.index,
                        single_contraction_dryup_allowance=True)

    assert res["valid"] is False
    assert res["rejection_reason"] == "CONTRACTION_COUNT_OUT_OF_RANGE"


def test_fixture_sc3b_equal_volume_is_not_a_dryup():
    """
    SC3b -- PREDICTION: the test is a strict `<`. Contraction volume exactly
    equal to the pre-base average is not a dry-up and must still be rejected.
    """
    prices = _sc_prices(contraction_volume=100000, pre_base_volume=100000)
    res = validate_base(_sc_base_one_contraction(), prices, prices.index,
                        single_contraction_dryup_allowance=True)
    assert res["valid"] is False
    assert res["rejection_reason"] == "CONTRACTION_COUNT_OUT_OF_RANGE"


def test_fixture_sc4_depth_ceiling_still_rejects():
    """
    SC4 -- PREDICTION: 1 contraction WITH a genuine dry-up, but depth
    (100 - 35)/100 = 65% > the 60% ceiling. The depth filter (c) runs BEFORE
    the count filter (f), so this is rejected as CORRECTION_TOO_DEEP -- not
    CONTRACTION_COUNT_OUT_OF_RANGE -- and the allowance is never consulted. The
    add-on relaxes one filter, not the others.
    """
    prices = _sc_prices(contraction_volume=40000, pre_base_volume=100000,
                        trough_low=35.0, peak_high=100.0)
    res = validate_base(_sc_base_one_contraction(), prices, prices.index,
                        single_contraction_dryup_allowance=True)

    assert res["valid"] is False
    assert res["rejection_reason"] == "CORRECTION_TOO_DEEP"


def test_fixture_sc5_flag_off_always_rejects_one_contraction():
    """
    SC5 -- PREDICTION: with the flag off, a 1-contraction base is rejected
    regardless of volume. This is the fixture that proves the DEFAULT path is
    completely unchanged -- every Run A result depends on it.
    """
    for contraction_vol in (10000, 40000, 100000, 150000, 500000):
        prices = _sc_prices(contraction_volume=contraction_vol, pre_base_volume=100000)
        res = validate_base(_sc_base_one_contraction(), prices, prices.index,
                            single_contraction_dryup_allowance=False)
        assert res["valid"] is False, f"contraction_vol={contraction_vol}"
        assert res["rejection_reason"] == "CONTRACTION_COUNT_OUT_OF_RANGE"


def test_fixture_sc6_default_argument_is_off():
    """
    SC6 -- PREDICTION: callers that never pass the parameter get the old
    behaviour. Every existing call site relies on this.
    """
    prices = _sc_prices(contraction_volume=40000, pre_base_volume=100000)
    res = validate_base(_sc_base_one_contraction(), prices, prices.index)
    assert res["valid"] is False
    assert res["rejection_reason"] == "CONTRACTION_COUNT_OUT_OF_RANGE"


def test_fixture_sc7_weekly_path_unaffected():
    """
    SC7 -- PREDICTION: the weekly path passes min_contractions=1, so count == 1
    is already inside its range and the allowance is never reached. A weekly
    1-contraction base is therefore valid with the flag EITHER way, and carries
    no allowance flag in either case.
    """
    prices = _sc_prices(contraction_volume=150000, pre_base_volume=100000)
    off = validate_base(_sc_base_one_contraction(), prices, prices.index,
                        min_contractions=1, single_contraction_dryup_allowance=False)
    on = validate_base(_sc_base_one_contraction(), prices, prices.index,
                       min_contractions=1, single_contraction_dryup_allowance=True)
    assert off["valid"] is True and on["valid"] is True
    assert off["flags"] == on["flags"]
    assert not any("SINGLE_CONTRACTION_DRYUP_ALLOWANCE" in f for f in on["flags"])


def test_fixture_sc8_no_pre_base_history_rejects():
    """
    SC8 -- PREDICTION: with the base starting at bar 0 there are no pre-base
    bars to form a 50-day average, so the test returns False and the base is
    rejected. Absent evidence must not read as a dry-up.
    """
    prices = _sc_prices(contraction_volume=40000, pre_base_volume=100000)
    base = {"start_trough_idx": 0, "end_trough_idx": BASE_END,
            "contractions": [{"peak_idx": CONTRACTION_PEAK, "trough_idx": BASE_END}]}
    res = validate_base(base, prices, prices.index,
                        single_contraction_dryup_allowance=True)
    assert res["valid"] is False
    assert res["rejection_reason"] == "CONTRACTION_COUNT_OUT_OF_RANGE"


def test_fixture_sc9_pre_base_window_is_50_bars():
    """
    SC9 -- PREDICTION: the reference is the 50 bars BEFORE base start, not the
    whole prior history. Bars 0-9 carry a huge volume that must be EXCLUDED, so
    a 90,000 contraction still reads as a dry-up against the 100,000 fifty-bar
    average. The negative half is what pins the window: lowering only bars
    10-59 to 80,000 flips the outcome to rejected.
    """
    prices = _sc_prices(contraction_volume=90000, pre_base_volume=100000)
    prices.iloc[0:10, prices.columns.get_loc("Volume")] = 9_000_000.0
    res = validate_base(_sc_base_one_contraction(), prices, prices.index,
                        single_contraction_dryup_allowance=True)
    assert res["valid"] is True

    prices2 = _sc_prices(contraction_volume=90000, pre_base_volume=100000)
    prices2.iloc[10:BASE_START, prices2.columns.get_loc("Volume")] = 80_000.0
    res2 = validate_base(_sc_base_one_contraction(), prices2, prices2.index,
                         single_contraction_dryup_allowance=True)
    assert res2["valid"] is False
    assert res2["rejection_reason"] == "CONTRACTION_COUNT_OUT_OF_RANGE"


def test_fixture_sc10_median_not_mean_for_contraction():
    """
    SC10 -- PREDICTION: the contraction statistic is the MEDIAN. One climactic
    bar of 5,000,000 inside an otherwise quiet 40,000 contraction lifts the
    MEAN above the 100,000 pre-base average but leaves the median at 40,000, so
    the base is still allowed. A mean-based test would reject it -- this
    fixture is what distinguishes the two.
    """
    prices = _sc_prices(contraction_volume=40000, pre_base_volume=100000)
    prices.iloc[CONTRACTION_PEAK + 5, prices.columns.get_loc("Volume")] = 5_000_000.0
    c_slice = prices["Volume"].iloc[CONTRACTION_PEAK:BASE_END + 1]
    assert c_slice.mean() > 100000        # a mean-based test would reject
    assert c_slice.median() < 100000      # the median-based test allows

    res = validate_base(_sc_base_one_contraction(), prices, prices.index,
                        single_contraction_dryup_allowance=True)
    assert res["valid"] is True


def test_fixture_sc11_module_flag_default_off():
    """
    SC11 -- PREDICTION: the module-level flag defaults False, so an ordinary
    import produces the unchanged daily path.
    """
    assert et.EGX_SINGLE_CONTRACTION_VOLUME_DRYUP_ALLOWANCE is False
