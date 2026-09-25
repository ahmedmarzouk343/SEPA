"""
entry_timing.py -- Feature 5, dual-timeframe orchestrator.

Wires vcp_detection.py's functions into the weekly-then-daily sequence
required by feature-05-entry-timing-rules.md Section 2: identify and
validate the macro base on WEEKLY bars first; only if that succeeds, refine
the internal contraction sequence and locate the pivot on DAILY bars,
windowed to the weekly base's own date range.

Does not fetch data itself -- takes an already-built daily OHLCV DataFrame
(capitalized Open/High/Low/Close/Volume columns, matching KashifStrategy's
history-buffer convention) and does everything else in-process.

--------------------------------------------------------------------------
WEEKLY-FIRST IS A HARD GATE, not a preference
--------------------------------------------------------------------------
Section 2.1: "If no valid base is found on the weekly chart, don't proceed
to the daily -- a stock with no macro structure on the weekly is not a VCP
candidate regardless of what the daily looks like." evaluate_entry_timing()
returns immediately (price_ready=False) the moment the weekly stage fails,
before detect_swings() is ever called on the daily bars. Fixture 9 is the
regression test for this specific short-circuit.
"""

import os

import pandas as pd

from vcp_detection import (
    detect_swings, identify_bases, validate_base, find_pivot, check_breakout,
    check_post_breakout_health, score_vcp_quality,
    TICK_QUANTIZED_MIN_UNIQUE_CLOSES, ATR_PERIOD, ATR_MULTIPLIER,
    SMOOTHING_WINDOW, DISTANCE_DAYS, DISTANCE_WEEKS,
)


# ---------------------------------------------------------------------------
# SINGLE-CONTRACTION VOLUME DRY-UP ALLOWANCE
#
# Off by default: with the flag False the daily path behaves EXACTLY as it does
# today — same call, same rejections, no change at all.
#
# Scope note. This is an EGX accommodation in intent: EGX's daily price limits
# compress multi-week oscillations into single bars, so a large share of EGX
# daily bases carry exactly one contraction and are rejected on count alone.
# It is NOT additionally gated on market == "EGX", because the default entry
# market was reverted to None on 2026-09-05 after the paired test found the
# "EGX" branch harmful — an extra market=="EGX" condition would mean the
# allowance could never fire in the configuration the EGX backtest actually
# runs, making any test of it a no-op. The flag alone is the switch; the whole
# backtest universe is EGX.
#
# Unlike Fix 1, this does NOT bypass daily validation. The daily base must
# still clear tick-quantization, the 325-day maximum duration, the 60%
# correction-depth ceiling, monotonicity, pivot detection, breakout volume
# confirmation, and post-breakout health. The allowance relaxes exactly one
# filter, for count == 1 only, and only when the contraction's median volume
# came in below the pre-base 50-day average.
EGX_SINGLE_CONTRACTION_VOLUME_DRYUP_ALLOWANCE = (
    os.environ.get("KASHIF_SINGLE_CONTRACTION_ALLOWANCE", "").strip().lower()
    in ("1", "true", "yes", "on")
)


def to_weekly(daily_df):
    """
    Standard pandas resample, per spec Section 2.1 / matches
    vcp_calibration_explorer.py's to_weekly() and kashif_strategy.py's own
    dual-timeframe framing exactly -- not a new convention invented here.
    """
    return daily_df.resample("W").agg({
        "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum",
    }).dropna()


def evaluate_entry_timing(daily_df, base_number=None, breakout_index=-1, market=None,
                          volume_multiplier=None):
    """
    Full weekly-then-daily VCP pipeline for one ticker's OHLCV history.

    `daily_df`: DataFrame, capitalized OHLCV columns, DatetimeIndex.
    `base_number`: passed through to score_vcp_quality() -- see
      vcp_detection.py's module docstring deviation #4 (defaults to
      neutral, not auto-detected by this feature).
    `breakout_index`: which daily bar to evaluate check_breakout() on,
      default -1 (today / most recent bar). Exposed as a parameter so test
      fixtures can check a SPECIFIC historical bar (e.g. Fixture 6's squat
      day vs. its confirmation day 3 bars later) without needing to slice
      daily_df down to that point themselves.
    `volume_multiplier`: breakout volume threshold passed to check_breakout().
      None keeps vcp_detection.PIVOT_BREAKOUT_VOLUME_MULTIPLIER (1.4). Added so
      the tunable breakout multiple actually reaches the check -- before this,
      check_breakout() always used its def-time default.

    Returns a dict:
      {
        "price_ready": bool,
        "pivot_price": float or None,
        "vcp_quality_score": float,
        "base_details": dict or None,   # the validated daily base
        "reason": str,                  # short machine-readable status
        "breakout_detail": dict or None,
      }
    """
    result = {
        "price_ready": False,
        "pivot_price": None,
        "vcp_quality_score": 0.0,
        "base_details": None,
        "reason": None,
        "breakout_detail": None,
    }

    # --- Pre-filter: tick-quantized stocks never even reach detect_swings().
    # JSON: "Applied BEFORE detect_swings() runs -- discard ineligible
    # stocks without spending computation on VCP logic." validate_base()
    # repeats this same check as defense-in-depth for direct callers (e.g.
    # tests) that skip this orchestrator.
    if daily_df["Close"].nunique() < TICK_QUANTIZED_MIN_UNIQUE_CLOSES:
        result["reason"] = "TICK_QUANTIZED"
        return result

    # --- Weekly stage: identify and validate the macro base. ---
    weekly_df = to_weekly(daily_df)
    if len(weekly_df) < ATR_PERIOD + 1:
        result["reason"] = "INSUFFICIENT_WEEKLY_HISTORY"
        return result

    w_peaks, w_troughs = detect_swings(
        weekly_df["Close"], weekly_df["High"], weekly_df["Low"], weekly_df["Volume"],
        ATR_PERIOD, ATR_MULTIPLIER, DISTANCE_WEEKS, DISTANCE_WEEKS,
    )
    w_bases = identify_bases(w_peaks, w_troughs, weekly_df["High"])
    if not w_bases:
        # HARD GATE -- do not proceed to daily. Section 2.1 / Fixture 9.
        result["reason"] = "NO_WEEKLY_BASE"
        return result

    weekly_base = w_bases[-1]  # most recent candidate base
    is_egx = market == "EGX"
    weekly_validated = validate_base(
        weekly_base, weekly_df, weekly_df.index,
        min_contractions=1, require_volume_dryup=is_egx,
    )
    if not weekly_validated["valid"]:
        result["reason"] = f"WEEKLY_BASE_REJECTED:{weekly_validated['rejection_reason']}"
        return result

    if is_egx:
        # --- EGX weekly-primary architecture: skip daily contraction
        # re-validation. Use the weekly base's pivot directly; confirm
        # breakout on daily bars. Rationale: EGX +/-10%/20% daily price
        # limits compress multi-week oscillations into single bars, so
        # 90% of daily bases have exactly 1 contraction and fail the
        # standard CONTRACTION_COUNT_MIN=2 gate. The weekly base (which
        # already passed validation with volume dry-up) is the structural
        # authority; the daily chart supplies only pivot and breakout.
        pivot_price = find_pivot(weekly_validated, weekly_df)
        quality = score_vcp_quality(weekly_validated, base_number=base_number)
        result["base_details"] = weekly_validated
        result["pivot_price"] = pivot_price
        result["vcp_quality_score"] = quality["vcp_quality_score"]

        if pivot_price is None:
            result["reason"] = "NO_PIVOT"
            return result

        breakout_confirmed, breakout_detail = check_breakout(
            daily_df, daily_df["Volume"], pivot_price, index=breakout_index,
            **({} if volume_multiplier is None else {"volume_multiplier": volume_multiplier}),
        )
        result["breakout_detail"] = breakout_detail

        if not breakout_confirmed:
            result["reason"] = "AWAITING_BREAKOUT"
            return result

        breakout_date = daily_df.index[breakout_index if breakout_index >= 0 else len(daily_df) + breakout_index]
        healthy, health_detail = check_post_breakout_health(daily_df, breakout_date)
        result["post_breakout_health"] = health_detail
        if not healthy:
            result["reason"] = "POST_BREAKOUT_UNHEALTHY"
            return result

        result["price_ready"] = True
        result["reason"] = "PRICE_READY"
        return result

    # --- Daily stage (non-EGX): window OPENS at the weekly base's start
    # trough and runs to the evaluation date.
    #
    # Section 2.2 originally closed this window at the weekly base's LAST
    # TROUGH ("only detect sub-swings within that window"). Measured, that
    # window ended a median of 175-197 days before the evaluation date, so
    # the daily detector searched a stale slice while the stock was breaking
    # out today. See kashif-vcp-window-diagnostic.md Defect 1.
    #
    # Window extends to evaluation date — confirmed in paired backtest
    # 2026-08-30. Mode B: +35.92% vs Mode A: +14.00%.
    # DO NOT revert to weekly_end_date without a new paired backtest.
    weekly_start_date = weekly_df.index[weekly_validated["start_trough_idx"]]
    daily_window = daily_df.loc[weekly_start_date:]
    if len(daily_window) < ATR_PERIOD + 1:
        result["reason"] = "INSUFFICIENT_DAILY_WINDOW"
        return result

    d_peaks, d_troughs = detect_swings(
        daily_window["Close"], daily_window["High"], daily_window["Low"], daily_window["Volume"],
        ATR_PERIOD, ATR_MULTIPLIER, SMOOTHING_WINDOW, DISTANCE_DAYS,
    )
    d_bases = identify_bases(d_peaks, d_troughs, daily_window["High"])
    if not d_bases:
        result["reason"] = "NO_DAILY_BASE_WITHIN_WEEKLY_WINDOW"
        return result

    daily_base = d_bases[-1]
    daily_validated = validate_base(
        daily_base, daily_window, daily_window.index,
        single_contraction_dryup_allowance=EGX_SINGLE_CONTRACTION_VOLUME_DRYUP_ALLOWANCE,
    )
    if not daily_validated["valid"]:
        result["reason"] = f"DAILY_BASE_REJECTED:{daily_validated['rejection_reason']}"
        return result

    pivot_price = find_pivot(daily_validated, daily_window)
    quality = score_vcp_quality(daily_validated, base_number=base_number)
    result["base_details"] = daily_validated
    result["pivot_price"] = pivot_price
    result["vcp_quality_score"] = quality["vcp_quality_score"]

    if pivot_price is None:
        result["reason"] = "NO_PIVOT"
        return result

    # --- Buy trigger: pivot breakout on confirming volume, evaluated
    # against the FULL daily_df (not the windowed daily_window) since a
    # breakout attempt happens AFTER the base's own end_trough, outside
    # the base window itself.
    breakout_confirmed, breakout_detail = check_breakout(
        daily_df, daily_df["Volume"], pivot_price, index=breakout_index,
        **({} if volume_multiplier is None else {"volume_multiplier": volume_multiplier}),
    )
    result["breakout_detail"] = breakout_detail

    if not breakout_confirmed:
        result["reason"] = "AWAITING_BREAKOUT"
        return result

    breakout_date = daily_df.index[breakout_index if breakout_index >= 0 else len(daily_df) + breakout_index]
    healthy, health_detail = check_post_breakout_health(daily_df, breakout_date)
    result["post_breakout_health"] = health_detail
    if not healthy:
        result["reason"] = "POST_BREAKOUT_UNHEALTHY"
        return result

    result["price_ready"] = True
    result["reason"] = "PRICE_READY"
    return result
