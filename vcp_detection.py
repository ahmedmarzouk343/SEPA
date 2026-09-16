"""
vcp_detection.py -- Feature 5 (Entry Timing / VCP Detection), numeric core.

Implements: detect_swings() [feature-05-entry-timing-rules.md Section 3,
locked calibration parameters], identify_bases() [Section 4.1],
validate_base() [Section 4.2-4.3 hard filters + monotonicity],
find_pivot()/check_breakout()/check_post_breakout_health() [Sections 5-6],
score_vcp_quality() [Section 7].

Does not fetch data, does not touch backtrader, does not decide category/
fundamentals/catalyst. Pure functions over already-fetched OHLCV DataFrames
(capitalized Open/High/Low/Close/Volume columns, matching KashifStrategy's
history-buffer convention -- see kashif_strategy.py's own module docstring
on this translation boundary).

--------------------------------------------------------------------------
MONOTONICITY TOLERANCE DECISION (Section 4.3's rule_b, JSON's
contraction_sequence_monotonicity_filter.tolerance_open_item) -- RESOLVED
--------------------------------------------------------------------------
130%, not 110%. Both worked calibration examples that SHOULD accept
(COMI_base_6, SWDY_base_1) pass at 130%; the one that should reject
(TMGH_base_2, a 192%-of-prior oscillation) is rejected at EITHER value --
110% buys nothing extra there. The only practical effect of choosing 110%
over 130% is wrongly rejecting SWDY's base, which the calibration charts
already confirmed by eye is a real VCP (29.8%->13.2%->16.7%, a modest
16.7/13.2=126% uptick on the final leg). 130% is also closer to the book's
own "roughly halving" framing than 110% is (110% is nearly strict
monotonicity with almost no slack). Recorded here, in the JSON
(entry_timing.vcp_detection.conditions.contraction_sequence_monotonicity_
filter.tolerance), and in test_feature5_known_answer.py's Fixture 7
prediction -- three places, so it can't silently drift.

--------------------------------------------------------------------------
FLAGGED DEVIATIONS from the literal build instructions, not silently
resolved
--------------------------------------------------------------------------
1. detect_swings()'s `volume` parameter (per feature-05.md Section 3's
   exact signature: close, high, low, volume, ...) is accepted but UNUSED
   inside the function -- ATR/smoothing/find_peaks only ever touch
   high/low/close. This matches the spec's own literal signature exactly
   rather than dropping the parameter; vcp_calibration_explorer.py flagged
   the same situation for its own unused `price_series` parameter.

2. identify_bases()'s signature takes an ADDITIONAL `raw_high` parameter
   beyond the bare (peaks, troughs) the task description named. This is
   necessary, not optional: grouping a flat peak/trough sequence into
   MULTIPLE distinct bases (as opposed to one giant trough-to-trough span)
   requires knowing which peaks make a fresh high above the current base's
   own starting peak -- pure index arithmetic cannot answer that. This is
   also the exact rule vcp_calibration_explorer.py's group_into_bases()
   already used to produce the COMI_base_6/TMGH_base_2/SWDY_base_1 results
   feature-05.md's own worked_checks cite by name -- reproducing those
   specific, spec-cited results requires the same rule, which requires
   price data. Confirmed by reproduction: this implementation's output on
   those three tickers matches the spec's worked_checks exactly (see
   test_feature5_known_answer.py's docstring for the verification).

3. detect_swings() implements the spec's literal steps 5-6 ("map indices
   back to original (pre-dropna) index") rather than
   vcp_calibration_explorer.py's simpler min_periods=1 approach (which
   avoided the remapping question entirely by never producing leading
   NaNs). The spec's pseudocode explicitly calls out this remapping step,
   so it is implemented here even though it is more code than the
   calibration script needed -- see detect_swings()'s docstring for the
   exact mechanism.

4. score_vcp_quality()'s base_count_modifier ("which numbered base is this
   across the ticker's whole Stage 2 run") accepts an optional
   `base_number` argument, defaulting to None (treated as neutral,
   3rd-base-equivalent, modifier=0.0). The JSON's own base_count_modifier
   block says this outright: the SCORING rule is defined, but the
   DETECTION of which base number a given setup actually is has "nowhere
   to get its input from yet" -- that detection is not part of this
   feature's build list (identify_bases/validate_base find and validate
   ONE base at a time; counting a ticker's Nth base across its whole
   trend history is separate, unbuilt state-tracking). Defaulting to
   neutral rather than silently assuming best-case (1st/2nd, +0.05) or
   worst-case (4th+, -0.05).
"""

import numpy as np
import pandas as pd
import pandas_ta as ta
from scipy.signal import find_peaks

# ==========================================================================
# LOCKED calibration parameters -- feature-05-entry-timing-rules.md Section 3.
# Confirmed from two rounds of visual calibration (vcp_calibration_explorer.py
# runs 1 and 2), NOT starting points to re-tune casually -- if these need to
# change, that is a new calibration round, not a one-line edit here.
# ==========================================================================
ATR_PERIOD = 14
ATR_MULTIPLIER = 1.0
SMOOTHING_WINDOW = 5          # daily bars
DISTANCE_DAYS = 3             # daily bars
DISTANCE_WEEKS = 2            # weekly bars

# ==========================================================================
# Base validation constants -- JSON entry_timing.vcp_detection, v0.19+.
# ==========================================================================
TICK_QUANTIZED_MIN_UNIQUE_CLOSES = 20     # Section 4.2 pre-filter
BASE_DURATION_MAX_TRADING_DAYS = 325      # Section 4.2, 65 weeks
BASE_DURATION_MIN_TRADING_DAYS = 15       # Section 4.2, 3 weeks -- FLAG not reject
CORRECTION_DEPTH_MAX = 0.60               # Section 4.2 / JSON avoid_above
CORRECTION_DEPTH_CAUTION_ABOVE = 0.35      # JSON caution_above -- flag, not reject
CONTRACTION_COUNT_MIN = 2                 # Section 4.3 / JSON contraction_count.min
CONTRACTION_COUNT_MAX = 6                 # Section 4.3 / JSON contraction_count.max
# Lookback for the SINGLE-CONTRACTION VOLUME DRY-UP ALLOWANCE (see
# _single_contraction_volume_dried_up). "50-day average volume at base start"
# means the 50 bars immediately BEFORE the base begins — the reference level
# the contraction has to come in under.
SINGLE_CONTRACTION_PRE_BASE_VOLUME_WINDOW = 50

VOLUME_DRYUP_RATIO = 0.80                # EGX adaptation: final contraction avg vol
                                           # must be <= this fraction of base avg vol
                                           # when accepting single-contraction bases.
MONOTONICITY_RULE_A_MAX_RATIO = 0.75      # final <= first * 0.75
MONOTONICITY_RULE_B_TOLERANCE = 1.50      # C4: 1.30->1.50, "roughly halving" allows
                                           # more variation. See module docstring.

# Section 5-6 -- pivot / breakout / post-breakout health.
PIVOT_BREAKOUT_VOLUME_MULTIPLIER = 1.4  # A5: restored 1.2->1.4; ch10 "volume meaningfully
                                           # above average". Calibration parameter.
BREAKOUT_VOLUME_WINDOW = 50               # trailing bars, INCLUDING today -- same
                                           # convention as kashif_strategy.py's
                                           # _avg_volume() and kashif_sizer.py's
                                           # _compute_addv(), kept consistent
                                           # across the project rather than
                                           # silently choosing a different one here.
SQUAT_TOLERANCE_DAYS = 10                 # see check_breakout()'s docstring
POST_BREAKOUT_SMA_WINDOW = 20


# ==========================================================================
# detect_swings() -- Section 3, exact algorithm. Same function called on
# both daily and weekly bars (spec's central requirement).
# ==========================================================================

def detect_swings(close, high, low, volume,
                   atr_period=ATR_PERIOD, atr_multiplier=ATR_MULTIPLIER,
                   smoothing_window=SMOOTHING_WINDOW, distance=DISTANCE_DAYS):
    """
    1. ATR(atr_period) via pandas_ta -- handles any bar frequency (only
       depends on H/L/C values, not their timeframe).
    2. Smooth close with a rolling median of `smoothing_window` bars,
       trailing/right-aligned (center=False, pandas' default -- stated
       explicitly per spec Section 3's pseudocode). NOTE: unlike
       vcp_calibration_explorer.py's min_periods=1 (which avoided NaN
       entirely), this uses pandas' default min_periods=smoothing_window,
       matching the spec's literal pseudocode -- the first
       (smoothing_window - 1) bars are NaN and must be mapped back out
       (steps 5-6 below), not silently smoothed with a partial window.
    3. find_peaks() on the smoothed series (NaNs dropped first),
       prominence = atr_multiplier * ATR[-1] (scalar, last bar of the
       FULL, non-dropna'd ATR series), distance = distance.
    4. Troughs: find_peaks() on the inverted smoothed series, same params.
    5-6. Map the dropna'd array's positions back to the ORIGINAL series'
       integer positions (not just "subtract smoothing_window-1", in case
       of any other NaN gaps -- uses the actual positions of non-NaN
       values, so it's correct regardless of where the NaNs are).

    Returns: (peak_indices, trough_indices) -- np.ndarray of int positions
    into the ORIGINAL close/high/low/volume series (iloc-compatible).
    Per spec Section 3's literal declared return (peak_indices,
    trough_indices only) -- callers needing the smoothed/ATR series for
    their own purposes (e.g. charting) compute those themselves, same as
    identify_bases()/validate_base() below take raw price data directly
    rather than threading it through this function's return.

    `volume` is accepted but unused inside this function -- see module
    docstring deviation #1 (matches the spec's literal Section 3 signature
    exactly, flagged rather than silently dropped).
    """
    atr = ta.atr(high, low, close, length=atr_period)
    last_atr = atr.iloc[-1]

    empty = np.array([], dtype=int)
    if pd.isna(last_atr) or last_atr <= 0:
        # Not enough history yet for a real ATR reading, or a degenerate
        # all-identical-H/L/C window (ATR pre-filter, JSON
        # pre_filters.atr_sanity) -- fail closed rather than let
        # prominence=NaN/0 silently disable the threshold.
        return empty, empty

    prominence_threshold = atr_multiplier * last_atr

    smoothed = close.rolling(smoothing_window, center=False).median()

    valid_mask = smoothed.notna().values
    valid_positions = np.flatnonzero(valid_mask)
    if len(valid_positions) == 0:
        return empty, empty
    smoothed_values = smoothed.values[valid_positions]

    peaks_local, _ = find_peaks(smoothed_values, prominence=prominence_threshold, distance=distance)
    troughs_local, _ = find_peaks(-smoothed_values, prominence=prominence_threshold, distance=distance)

    peak_indices = valid_positions[peaks_local]
    trough_indices = valid_positions[troughs_local]

    return peak_indices, trough_indices


# ==========================================================================
# identify_bases() -- Section 4.1. Groups a flat peak/trough index array
# into distinct trough->peak->trough base structures.
# ==========================================================================

def _build_swing_sequence(peak_idx, trough_idx):
    """
    Merge peak and trough indices into one time-ordered, strictly
    alternating sequence of ('P', idx) / ('T', idx) tuples. Same rule as
    vcp_calibration_explorer.py's build_swing_sequence(): if two same-type
    points occur consecutively, keep only the more extreme one (this is
    purely an index-ordering cleanup, not a price comparison, so it is
    safe to do without raw price data).
    """
    points = [("P", int(i)) for i in peak_idx] + [("T", int(i)) for i in trough_idx]
    points.sort(key=lambda p: p[1])

    cleaned = []
    for kind, idx in points:
        if cleaned and cleaned[-1][0] == kind:
            cleaned.pop()
        cleaned.append((kind, idx))
    return cleaned


def identify_bases(peaks, troughs, raw_high):
    """
    Groups peak/trough indices into bases (spec Section 4.1: "a base is a
    trough -> peak -> trough sequence"). See module docstring deviation #2
    for why `raw_high` is required beyond the bare (peaks, troughs) the
    task's build-order list named.

    Rule (identical to vcp_calibration_explorer.py's group_into_bases(),
    the rule the spec's own worked_checks were generated from): a new base
    starts whenever a contraction's peak makes a fresh high ABOVE the
    current base's own starting peak -- price broke out above where this
    base began, so the prior base is resolved and a new one begins from
    the breakout peak.

    Returns a list of bases, each a dict:
      {
        "start_trough_idx": int,   # trough preceding the base's first peak
        "end_trough_idx": int,     # the base's LAST contraction's trough
        "contractions": [{"peak_idx": int, "trough_idx": int}, ...],
      }
    Depths are NOT computed here -- detected LOCATION (this function) vs.
    measured VALUE (validate_base(), from raw prices) are different things
    per spec Section 3; keeping that split here too, not collapsing it.
    """
    swing_seq = _build_swing_sequence(peaks, troughs)

    contractions = []
    for i in range(len(swing_seq) - 1):
        kind1, idx1 = swing_seq[i]
        kind2, idx2 = swing_seq[i + 1]
        if kind1 == "P" and kind2 == "T":
            preceding_trough = swing_seq[i - 1][1] if i > 0 and swing_seq[i - 1][0] == "T" else None
            contractions.append({"peak_idx": idx1, "trough_idx": idx2, "preceding_trough_idx": preceding_trough})

    if not contractions:
        return []

    grouped = [[contractions[0]]]
    base_reference_high = raw_high.iloc[contractions[0]["peak_idx"]]
    for c in contractions[1:]:
        this_peak_high = raw_high.iloc[c["peak_idx"]]
        if this_peak_high > base_reference_high:
            grouped.append([c])
            base_reference_high = this_peak_high
        else:
            grouped[-1].append(c)

    bases = []
    for group in grouped:
        start_trough_idx = group[0]["preceding_trough_idx"]
        if start_trough_idx is None:
            # No trough detected before this base's first peak -- the very
            # first swing point in the whole series was itself a peak (a
            # real, common case: TMGH's own history starts this way,
            # peak@10 -> trough@18, with no trough recorded before index
            # 10 since detect_swings() only starts finding swings once
            # enough history exists for ATR/smoothing).
            #
            # [CORRECTED -- logic error, caught by reproducing feature-05's
            # own worked_checks against real TMGH data] the first version
            # fell back to the contraction's OWN trough_idx as "start,"
            # which for a single-contraction group made start_trough_idx
            # == end_trough_idx (both equal to that one trough) -- a
            # degenerate ZERO-WIDTH base. validate_base()'s window slice
            # prices["Close"].iloc[start:end+1] then covered exactly one
            # bar, so unique_closes was trivially 1 and the base was
            # spuriously rejected as TICK_QUANTIZED -- not a real
            # tick-quantization finding, an artifact of the zero-width
            # window. Fixed to fall back to the contraction's PEAK index
            # instead: the peak is the earliest point this base actually
            # has on record, giving a real (if slightly truncated) window
            # instead of a single bar. Reproducing TMGH now correctly
            # yields base 1 = peak(10)->trough(18), depth 6.3%, matching
            # what vcp_calibration_explorer.py found independently.
            start_trough_idx = group[0]["peak_idx"]
        bases.append({
            "start_trough_idx": int(start_trough_idx),
            "end_trough_idx": int(group[-1]["trough_idx"]),
            "contractions": [{"peak_idx": c["peak_idx"], "trough_idx": c["trough_idx"]} for c in group],
        })
    return bases


# ==========================================================================
# validate_base() -- Section 4.2 hard filters (in order) + Section 4.3
# monotonicity filter.
# ==========================================================================

def _rejected(base, reason, detail, contractions=None):
    return {
        "valid": False,
        "rejection_reason": reason,
        "rejection_detail": detail,
        "flags": [],
        "contractions": contractions if contractions is not None else [],
        "start_trough_idx": base["start_trough_idx"],
        "end_trough_idx": base["end_trough_idx"],
    }


def _single_contraction_volume_dried_up(prices, start_idx, contraction):
    """
    The SINGLE-CONTRACTION VOLUME DRY-UP ALLOWANCE test.

    A base with exactly one contraction is normally rejected outright by the
    contraction-count filter. EGX's +/-10%/20% daily price limits compress what
    would be a multi-week oscillation elsewhere into a single bar, so a large
    share of otherwise well-formed EGX daily bases show only one contraction.
    This test asks whether that single contraction at least shows the volume
    signature a real VCP contraction has — supply drying up — rather than
    admitting every 1-contraction base on structure alone.

      contraction_volume = MEDIAN volume across the contraction
                           (peak_idx .. trough_idx inclusive)
      pre_base_volume    = MEAN volume over the 50 bars BEFORE base start
      dried up  <=>  contraction_volume < pre_base_volume

    Median for the contraction (a single climactic bar inside a short window
    would drag a mean up and mask a genuine dry-up); mean for the pre-base
    reference, which is the conventional 50-day average volume.

    Deliberately NOT the same test as require_volume_dryup above: that one
    compares the final contraction's MEAN against the BASE's own mean at an
    0.80 ratio. This one compares against pre-base volume at a strict
    less-than. They answer different questions and are kept separate.

    Returns (dried_up: bool, detail: str). Returns False — reject — when there
    is no pre-base history to measure against, rather than admitting a base on
    absent evidence.
    """
    vol = prices["Volume"]
    c_lo, c_hi = contraction["peak_idx"], contraction["trough_idx"]
    c_slice = vol.iloc[c_lo:c_hi + 1]
    if len(c_slice) == 0:
        return False, "contraction window empty"
    contraction_volume = float(c_slice.median())

    pre_start = max(0, start_idx - SINGLE_CONTRACTION_PRE_BASE_VOLUME_WINDOW)
    pre_slice = vol.iloc[pre_start:start_idx]
    if len(pre_slice) == 0:
        return False, "no pre-base bars available to measure 50-day average volume"
    pre_base_volume = float(pre_slice.mean())
    if not (pre_base_volume > 0):
        return False, f"pre-base average volume is {pre_base_volume:.0f}"

    dried = contraction_volume < pre_base_volume
    detail = (f"contraction median vol {contraction_volume:.0f} "
              f"{'<' if dried else '>='} pre-base {len(pre_slice)}-bar avg {pre_base_volume:.0f}")
    return dried, detail


def validate_base(base, prices, dates=None, min_contractions=None, require_volume_dryup=False,
                  single_contraction_dryup_allowance=False):
    """
    Applies the Section 4.2/4.3 hard filters IN ORDER -- if any fails, the
    base is discarded (order matters: see feature-05.md Section 4.2's own
    note about TMGH's 2-year-spanning base needing the duration cutoff
    BEFORE contraction analysis, or the max-duration filter must run
    before wasting effort counting a nonsensical contraction sequence):
      (a) tick-quantized pre-filter (< 20 unique closes)
      (b) 325-trading-day maximum duration -- hard reject
      (c) 60% correction depth -- hard reject
      (d) 15-trading-day minimum duration -- FLAG, do not reject
      (e) monotonicity filter (rule_a AND rule_b)
      (f) contraction count 2-6

    `base`: one entry from identify_bases()'s returned list.
    `prices`: DataFrame with "Open"/"High"/"Low"/"Close"/"Volume" columns,
      INTEGER-positioned to match base's peak_idx/trough_idx (i.e. accessed
      via .iloc[idx], not label-based lookups).
    `dates`: optional DatetimeIndex/Series aligned the same way as
      `prices` -- used only for human-readable reporting in the returned
      dict (start_date/end_date), NOT for the numeric duration checks,
      which count BARS (trading days), matching the fixtures' literal "15
      trading days"/"326 trading days" framing exactly.

    Returns a dict (see _rejected() for the rejected shape; the accepted
    shape adds duration_trading_days/correction_depth/contraction_count
    and sets valid=True, rejection_reason=None).
    """
    start_idx = base["start_trough_idx"]
    end_idx = base["end_trough_idx"]
    contractions_raw = base["contractions"]

    flags = []

    # (a) tick-quantized pre-filter -- defense-in-depth. entry_timing.py's
    # orchestrator already screens this out before calling detect_swings()
    # at all (see that module), but repeating it here means validate_base()
    # is safe to call directly (e.g. from tests) without depending on the
    # orchestrator having run first.
    #
    # [CORRECTED -- logic error, caught by reproducing feature-05's own
    # worked_checks against real TMGH data] the first version scoped this
    # check to the BASE's own window (prices.iloc[start:end+1]), which for
    # any short base (e.g. an 8-9 trading-day base) can never have >= 20
    # unique closes no matter how liquid the stock is -- a 9-bar window
    # has at most 9 possible unique values. This spuriously rejected a
    # real, non-tick-quantized TMGH base as TICK_QUANTIZED. The spec is
    # explicit this check is meant "over the lookback window" (JSON:
    # "fewer than 20 unique closing prices over 2 years"), i.e. the whole
    # price history passed in, not the short base sub-window -- matching
    # exactly what entry_timing.py's orchestrator already checks over the
    # full daily_df before detect_swings() is even called. Fixed to check
    # the full `prices["Close"]` series here too, so this defense-in-depth
    # copy actually agrees with the orchestrator's primary check instead
    # of silently applying a stricter, wrong rule of its own.
    unique_closes = int(prices["Close"].nunique())
    if unique_closes < TICK_QUANTIZED_MIN_UNIQUE_CLOSES:
        return _rejected(base, "TICK_QUANTIZED",
                          f"only {unique_closes} unique closing prices over the full lookback "
                          f"(< {TICK_QUANTIZED_MIN_UNIQUE_CLOSES} minimum)")

    # (b) 325-trading-day maximum duration.
    duration = end_idx - start_idx
    if duration > BASE_DURATION_MAX_TRADING_DAYS:
        return _rejected(base, "BASE_TOO_LONG",
                          f"duration {duration} trading days > {BASE_DURATION_MAX_TRADING_DAYS} maximum")

    # No contractions at all -- degenerate, cannot compute correction depth
    # or run the monotonicity math below (would index/divide by nothing).
    # Not one of the 9 required fixtures, but guarded rather than left to
    # crash.
    if not contractions_raw:
        return _rejected(base, "CONTRACTION_COUNT_OUT_OF_RANGE",
                          f"0 contractions, need {CONTRACTION_COUNT_MIN}-{CONTRACTION_COUNT_MAX}")

    # Measure contraction depths from RAW prices now (detected LOCATION
    # already came from the smoothed series in detect_swings(); measured
    # VALUE uses raw High/Low here -- spec Section 3's "these are
    # different things").
    contractions = []
    for c in contractions_raw:
        peak_high = float(prices["High"].iloc[c["peak_idx"]])
        trough_low = float(prices["Low"].iloc[c["trough_idx"]])
        depth = (peak_high - trough_low) / peak_high if peak_high > 0 else 0.0
        contractions.append({"peak_idx": c["peak_idx"], "trough_idx": c["trough_idx"], "depth": depth})

    # (c) 60% correction depth -- measured from the base's OWN highest
    # swing peak down to its OWN lowest swing trough (a stock "down more
    # than 60% from its highs" per the JSON's stated meaning), not a
    # blanket max/min over every bar in the window (which could pick up an
    # intraday spike unrelated to the detected swing structure).
    base_high = max(prices["High"].iloc[c["peak_idx"]] for c in contractions_raw)
    base_low = min(prices["Low"].iloc[c["trough_idx"]] for c in contractions_raw)
    correction_depth = (base_high - base_low) / base_high if base_high > 0 else 0.0
    if correction_depth > CORRECTION_DEPTH_MAX:
        return _rejected(base, "CORRECTION_TOO_DEEP",
                          f"correction depth {correction_depth:.1%} > {CORRECTION_DEPTH_MAX:.0%} maximum",
                          contractions=contractions)
    elif correction_depth > CORRECTION_DEPTH_CAUTION_ABOVE:
        # JSON correction_depth_pct.caution_above: 0.35 -- "0.35-0.60 is
        # caution, not disqualifying." Not in the user's literal
        # build-order wording for filter (c) (which only names the 60%
        # hard-reject), but Fixture 4 explicitly requires this flag to
        # exist ("59% ... should pass with caution flag") and the JSON
        # already defines the threshold -- added rather than left silently
        # unimplemented.
        flags.append(f"CORRECTION_DEPTH_CAUTION: {correction_depth:.1%} "
                      f"(above {CORRECTION_DEPTH_CAUTION_ABOVE:.0%}, below {CORRECTION_DEPTH_MAX:.0%} hard limit)")

    # (d) 15-trading-day minimum duration -- FLAG, do not reject.
    #
    # [CORRECTED -- boundary error, caught while scratch-verifying Fixture
    # 3] first version used strict `<` here, so a base at EXACTLY the
    # 15-day minimum was treated as already clearing the bar (no flag).
    # Fixture 3 is explicit that "one base of exactly 15 trading days
    # (minimum threshold)" should still get the flag -- 15 is presented as
    # the floor of the caution zone, not outside it. Fixed to `<=`.
    if duration <= BASE_DURATION_MIN_TRADING_DAYS:
        flags.append(f"SHORT_DURATION: {duration} trading days <= {BASE_DURATION_MIN_TRADING_DAYS} minimum")

    # (e) monotonicity filter -- rule_a AND rule_b.
    # T0-B fix: with only 1 contraction, depths[-1] == depths[0] so rule_a
    # (final <= first * 0.75) is structurally impossible.  A single contraction
    # has no "first vs last" to compare — skip both rules in that case.
    depths = [c["depth"] for c in contractions]
    if len(depths) >= 2:
        rule_a_pass = depths[-1] <= depths[0] * MONOTONICITY_RULE_A_MAX_RATIO
        rule_b_pass = all(depths[i] <= depths[i - 1] * MONOTONICITY_RULE_B_TOLERANCE for i in range(1, len(depths)))
        if not (rule_a_pass and rule_b_pass):
            detail = (f"rule_a(final<=first*0.75)={'pass' if rule_a_pass else 'FAIL'}, "
                      f"rule_b(no step>prior*{MONOTONICITY_RULE_B_TOLERANCE:.0%})={'pass' if rule_b_pass else 'FAIL'}")
            return _rejected(base, "MONOTONICITY_FAILED", detail, contractions=contractions)

    # (f) contraction count — default 2-6, overridable for weekly bases.
    effective_min = min_contractions if min_contractions is not None else CONTRACTION_COUNT_MIN
    count = len(contractions)
    if not (effective_min <= count <= CONTRACTION_COUNT_MAX):
        # SINGLE-CONTRACTION VOLUME DRY-UP ALLOWANCE. Narrow by construction:
        # it only ever fires for count == 1 against a minimum above 1, so a
        # base with 2+ contractions and a base above the maximum are both
        # untouched, and the weekly path (min_contractions=1) never consults
        # it because count == 1 is already inside its range.
        #
        # Every other filter still applies. Note the ORDER above: correction
        # depth (c) and max duration (b) have already run and returned by this
        # point, so an over-deep or over-long 1-contraction base is rejected on
        # those grounds and never reaches this allowance at all.
        allowed = False
        if single_contraction_dryup_allowance and count == 1 and count < effective_min:
            allowed, dryup_detail = _single_contraction_volume_dried_up(
                prices, start_idx, contractions[0])
            if allowed:
                flags.append(f"SINGLE_CONTRACTION_DRYUP_ALLOWANCE: {dryup_detail}")
        if not allowed:
            return _rejected(base, "CONTRACTION_COUNT_OUT_OF_RANGE",
                              f"{count} contractions, need {effective_min}-{CONTRACTION_COUNT_MAX}",
                              contractions=contractions)

    # (g) volume dry-up — required for EGX single-contraction bases.
    if require_volume_dryup:
        base_avg_vol = float(prices["Volume"].iloc[start_idx:end_idx + 1].mean())
        if base_avg_vol > 0:
            last_c = contractions[-1]
            final_avg_vol = float(prices["Volume"].iloc[last_c["peak_idx"]:last_c["trough_idx"] + 1].mean())
            if final_avg_vol > base_avg_vol * VOLUME_DRYUP_RATIO:
                return _rejected(base, "NO_VOLUME_DRYUP",
                                  f"final contraction avg vol {final_avg_vol:.0f} "
                                  f"> {VOLUME_DRYUP_RATIO:.0%} of base avg {base_avg_vol:.0f}",
                                  contractions=contractions)

    result = {
        "valid": True,
        "rejection_reason": None,
        "rejection_detail": None,
        "flags": flags,
        "contractions": contractions,
        "start_trough_idx": start_idx,
        "end_trough_idx": end_idx,
        "duration_trading_days": duration,
        "correction_depth": correction_depth,
        "contraction_count": count,
    }
    if dates is not None:
        result["start_date"] = str(dates[start_idx]) if start_idx < len(dates) else None
        result["end_date"] = str(dates[end_idx]) if end_idx < len(dates) else None
    return result


# ==========================================================================
# find_pivot() -- Section 5.
# ==========================================================================

def find_pivot(base, daily_prices):
    """
    pivot_price = high of the final/tightest contraction's peak (spec
    Section 5). `base` is a validate_base() result (or anything with a
    "contractions" list of {peak_idx, ...} dicts); `daily_prices` supplies
    the raw High to read at that index. Returns None if there are no
    contractions (nothing to pivot from).

    The JSON's pivot_point.definition also mentions a "flat-base variant"
    fallback (high of the whole base, when there's no clear tightest
    contraction) -- NOT implemented here, since it is not in this
    feature's literal build-order list. Flagged, not silently added.
    """
    contractions = base.get("contractions", [])
    if not contractions:
        return None
    final_peak_idx = contractions[-1]["peak_idx"]
    return float(daily_prices["High"].iloc[final_peak_idx])


# ==========================================================================
# check_breakout() -- Section 5, buy trigger.
# ==========================================================================

def check_breakout(prices, volumes, pivot_price, index=-1,
                    volume_window=BREAKOUT_VOLUME_WINDOW,
                    volume_multiplier=PIVOT_BREAKOUT_VOLUME_MULTIPLIER):
    """
    buy_trigger = close > pivot_price AND volume >= volume_multiplier *
    trailing volume_window-bar average volume (INCLUDING today -- see
    module-level constant comment on BREAKOUT_VOLUME_WINDOW for why).

    `index`: bar to evaluate, default -1 (most recent). Accepts a
    negative or positive integer position into `prices`/`volumes`.

    SQUAT TOLERANCE (spec Section 5/6, Fixture 6): a bar where HIGH pierces
    the pivot intraday but CLOSE does not is, under this close-based check,
    simply NOT a breakout (price_confirmed=False) -- it is not specially
    flagged as a rejection either, because this function is stateless and
    evaluated one bar at a time. The caller (entry_timing.py) naturally
    gets the "give it up to 10 days to re-attempt" behavior for free: a
    squat day returns False, and a later qualifying bar still returns True
    when checked. squat_tolerance_days=10 (JSON
    post_breakout_health_check.squat_tolerance_days) is therefore a
    caller-side "don't give up watching this pivot" policy, not something
    this function tracks internally -- flagged here since the JSON
    attaches that figure to post_breakout_health_check, not to this
    function, and no state is threaded between calls to enforce a 10-day
    cutoff on stale squats. Not exercised by any of the 9 required
    fixtures (Fixture 6 only needs "squat now" vs "confirmed 3 days
    later" behavior, both covered by this stateless per-bar design).

    Returns (breakout_confirmed: bool, detail: dict).
    """
    n = len(prices)
    idx = index if index >= 0 else n + index

    close = float(prices["Close"].iloc[idx])
    window_start = max(0, idx - volume_window + 1)
    vol_window = volumes.iloc[window_start:idx + 1]
    avg_volume = float(vol_window.mean()) if len(vol_window) > 0 else None
    today_volume = float(volumes.iloc[idx])

    price_confirmed = close > pivot_price
    volume_confirmed = bool(avg_volume is not None and avg_volume > 0
                             and today_volume >= volume_multiplier * avg_volume)

    breakout = bool(price_confirmed and volume_confirmed)
    detail = {
        "price_confirmed": bool(price_confirmed),
        "volume_confirmed": volume_confirmed,
        "close": close,
        "pivot_price": float(pivot_price),
        "today_volume": today_volume,
        "avg_volume": avg_volume,
        "volume_ratio": (today_volume / avg_volume) if avg_volume else None,
    }
    return breakout, detail


# ==========================================================================
# check_post_breakout_health() -- Section 6.
# ==========================================================================

def check_post_breakout_health(prices, breakout_date, sma_window=POST_BREAKOUT_SMA_WINDOW):
    """
    close < sma_20 on the most recent bar strictly AFTER breakout_date ->
    invalidated (price_ready should be reset False by the caller).
    `breakout_date`: a label present in (or comparable to) prices.index;
    rows with index > breakout_date are "post-breakout".

    Returns (healthy: bool, detail: dict). healthy=True (with an
    explanatory detail) when there simply isn't a post-breakout bar yet,
    or not enough history for sma_20 -- "not yet falsified" rather than
    "invalidated", same not-evaluable-vs-failed convention already
    established in Features 1-3 (evaluable/all_pass split) and Feature 4
    (regime_evaluation_error defaults).
    """
    sma = prices["Close"].rolling(sma_window).mean()
    post_breakout = prices.loc[prices.index > breakout_date]
    if post_breakout.empty:
        return True, {"reason": "no bars yet after breakout_date"}

    latest_label = post_breakout.index[-1]
    latest_close = float(post_breakout["Close"].iloc[-1])
    latest_sma = sma.loc[latest_label]
    if pd.isna(latest_sma):
        return True, {"reason": "insufficient history for sma_20"}

    healthy = latest_close >= float(latest_sma)
    return bool(healthy), {"close": latest_close, "sma_20": float(latest_sma)}


# ==========================================================================
# score_vcp_quality() -- Section 7.
# ==========================================================================

def score_vcp_quality(base, base_number=None):
    """
    vcp_quality_score = base_count_modifier + depth_score +
                         contraction_count_score

    `base`: a validate_base() result dict (needs "contractions").
    `base_number`: which numbered base this is across the ticker's whole
    Stage 2 run (1st/2nd/3rd/4th+). Defaults to None -> treated as neutral
    (same as 3rd base, modifier 0.0) -- see module docstring deviation #4
    for why this isn't auto-detected here.

    depth_score bucket boundaries (spec gives "10-20%" etc. without
    stating open/closed ends explicitly -- read here as left-inclusive,
    right-exclusive: [0,10%)->1.0, [10%,20%)->0.7, [20%,35%)->0.4,
    [35%,inf)->0.0):

    Returns a dict: {vcp_quality_score, base_count_modifier, depth_score,
    contraction_count_score} -- component breakdown kept visible, not just
    the total, so a Decision Receipt or test fixture can check each part.
    """
    if base_number in (1, 2):
        base_count_modifier = 0.05
    elif base_number == 3 or base_number is None:
        base_count_modifier = 0.0
    else:
        base_count_modifier = -0.05

    contractions = base.get("contractions", [])
    final_depth = contractions[-1]["depth"] if contractions else None
    if final_depth is None:
        depth_score = 0.0
    elif final_depth < 0.10:
        depth_score = 1.0
    elif final_depth < 0.20:
        depth_score = 0.7
    elif final_depth < 0.35:
        depth_score = 0.4
    else:
        depth_score = 0.0

    count = len(contractions)
    if 2 <= count <= 4:
        contraction_count_score = 1.0
    elif 5 <= count <= 6:
        contraction_count_score = 0.5
    else:
        contraction_count_score = 0.0

    total = base_count_modifier + depth_score + contraction_count_score
    return {
        "vcp_quality_score": total,
        "base_count_modifier": base_count_modifier,
        "depth_score": depth_score,
        "contraction_count_score": contraction_count_score,
    }
