import json

import numpy as np
import pandas as pd

from trend_template_test import compute_rs_percentile  # reuse tt_9's canonical RS ranking

from kashif_config import CONFIG_PATH

# Regime gate strictness — how many of the three conditions must hold.
#
# DELIBERATE DEVIATION from feature-03-market-regime-gate-rules.md and from
# kashif-implementation-plan.md, whose "What Does NOT Change" list names
# "Regime gate OR logic" explicitly. Recorded here rather than buried.
#
# Measured on the IS run: the gate opened on 510 of 518 evaluated bars
# (98.5%), with the per-condition counts ratio=260, pullback=499,
# divergence=88. Under an OR gate, `pullback` alone accounted for almost
# every open bar, so the other two conditions changed nothing and the gate
# was effectively decorative — it was not filtering any market state out.
# Requiring 2 of 3 makes it a real gate again.
#
# Set back to 1 to restore the v0.27 OR behaviour exactly.
# 1 == the OR gate: any single condition opens the regime.
#
# This was briefly set to 2 after the IS review (the gate opened on 510/518
# bars, so under OR it was barely filtering). REVERTED to 1 because:
#   a) the Fix 3 spec states the OR gate is correct and is to be kept, and
#   b) the follow-up diagnostic showed the strategy is UNDER-invested — 68
#      days holding nothing, 148 days at 0-1 positions, and only 28
#      QUEUED_INSUFFICIENT_SLOTS events. Entry starvation is candidate
#      supply (99.87% die at entry_timing/VCP), not an over-permissive gate.
#      Tightening here would have worsened the real problem.
# Set to 2 or 3 to re-test 2-of-3 / AND behaviour; both are covered by tests.
REGIME_GATE_MIN_CONDITIONS = 1

# Section 2.2: t-21 comparison window, reusing tt_4's SLOPE_MIN_DURATION convention exactly.
RATIO_LOOKBACK_WINDOW = 21

# Section 2.3: leader definition and pullback thresholds.
RS_LEADER_THRESHOLD = 90
PULLBACK_DEPTH_MAX = 0.10
PULLBACK_DURATION_MAX_DAYS = 15   # C6: 10->15 trading days (~3 calendar weeks)

# Section 2.3's "local high" window. RESOLVED as 20, NOT the JSON's literal "rolling 21-day
# local high" text -- the spec doc (feature-03-market-regime-gate-rules.md Section 2.3)
# explicitly instructs reusing leader_divergence's existing 20-day rolling-stat pattern
# ("don't invent a third window convention"), which only makes sense as 20, matching
# leader_divergence's low_20d window below. Treated as a stale JSON drafting artifact
# (likely conflated with the OTHER condition's 21-day t-21 lookback) and corrected in
# the JSON alongside this code, per this project's "keep the two files in sync" standard.
LOCAL_HIGH_WINDOW = 20

# Section 2.4: leader_divergence's rolling-low window and majority pivot.
DIVERGENCE_WINDOW = 20
# C5: the leader threshold drops 0.50 -> 0.40, but the UNIVERSE threshold must
# stay at 0.50. Both sides previously read one DIVERGENCE_PIVOT, and the two
# comparisons point in opposite directions:
#     leader_condition   = leader_pct   > pivot   (lower pivot = LOOSER)
#     universe_condition = universe_pct < pivot   (lower pivot = STRICTER)
# Lowering a single shared constant to 0.40 would therefore have tightened the
# universe side and made divergence fire LESS often — the opposite of C5's
# stated intent ("regime gate opens more often"). Split into two constants so
# the intended loosening is what actually happens.
DIVERGENCE_PIVOT_LEADER = 0.40     # C5: 0.50 -> 0.40
DIVERGENCE_PIVOT_UNIVERSE = 0.50   # unchanged — breadth-weakness definition
DIVERGENCE_PIVOT = DIVERGENCE_PIVOT_LEADER  # back-compat alias


def load_market_regime_gate():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg["market_regime_gate"]


# ---------------------------------------------------------------------------
# Condition 1: new_high_low_ratio_favorable (Section 2.2)
# ---------------------------------------------------------------------------

def compute_new_high_low_ratio(count_52wk_high, count_52wk_low):
    """
    count_52wk_high, count_52wk_low: same-indexed Series of daily counts across
    the EGX universe (how many stocks made a new 52-week high/low that day).

    ratio[t] = count(52wk_high)[t] / (count(52wk_low)[t] + 1)

    The +1 in the denominator (Section 2.2) is a deliberate fix, not a book
    approximation: count(52wk_low) can legitimately be zero on a strong day,
    which would otherwise make the ratio undefined (division by zero) --
    exactly the case Fixture 1 tests explicitly, not just in theory.
    """
    return count_52wk_high / (count_52wk_low + 1)


def new_high_low_ratio_favorable(ratio, window=RATIO_LOOKBACK_WINDOW):
    """
    ratio: Series (output of compute_new_high_low_ratio), date-indexed.

    condition[t] = ratio[t] > ratio[t-window]

    An exact two-point comparison (Section 2.2), NOT a monotonic-increase-
    every-day check -- same clarification tt_4 needed for its own sma_200
    slope check, and the same pattern (`series > series.shift(window)`)
    reused here deliberately for consistency.
    """
    return ratio > ratio.shift(window)


# ---------------------------------------------------------------------------
# Leader basket (Section 2.3 leader definition, Section 2.5 freshness requirement)
# ---------------------------------------------------------------------------

def get_leader_tickers(rs_percentile_snapshot, threshold=RS_LEADER_THRESHOLD):
    """
    rs_percentile_snapshot: dict or Series of {ticker: RS percentile}, a
    SINGLE POINT-IN-TIME snapshot (e.g. one row of compute_rs_percentile()'s
    output, or the output of that same function called fresh on the current
    cycle's return data).

    Returns the list of tickers with RS >= threshold (top decile at RS>=90).

    Section 2.5 freshness requirement, by construction: this function is pure
    and stateless -- it holds no cache, no memory of any prior call, and
    returns purely a function of whatever snapshot it's given right now.
    Calling it twice with two different snapshots (e.g. two different
    "cycles" of RS data, as in Fixture 5) necessarily returns two
    independently-correct baskets; there is no code path by which a prior
    cycle's membership could leak into or bias the current call. This
    function reuses trend_template_test.compute_rs_percentile() (imported
    above) for the actual ranking -- it does not reimplement RS ranking
    itself, per the project's "one canonical implementation" standard
    already established for tt_9.
    """
    s = pd.Series(rs_percentile_snapshot, dtype="float64")
    return sorted(s[s >= threshold].index.tolist())


# ---------------------------------------------------------------------------
# Condition 2: leader_pullback_shallow (Section 2.3)
# ---------------------------------------------------------------------------

def compute_pullback_metrics(price_series, window=LOCAL_HIGH_WINDOW):
    """
    price_series: one stock's Close price Series, date-indexed.

    Returns a DataFrame with columns:
      local_high        -- rolling window-day max of price (the "local high")
      pullback_depth     -- (local_high - price) / local_high, in [0, 1)
      days_since_local_high -- how many trading days back, WITHIN the window,
                            the current window's max actually occurred
                            (0 if today IS the local high). On a tie (price
                            flat at the local high for multiple consecutive
                            days), counts from the MOST RECENT day at the
                            peak, not the first -- see the tie-breaking note
                            inside _days_since_max() below.

    "Local high" (Section 2.3) uses the same rolling-window-stat pattern as
    leader_divergence's low_20d (Section 2.4), just a rolling max instead of
    a rolling min, and reading "days since" off the same window rather than
    a separate, unbounded lookback.
    """
    local_high = price_series.rolling(window).max()
    pullback_depth = (local_high - price_series) / local_high

    def _days_since_max(w):
        # w is the rolling window's values, oldest-first.
        #
        # CORRECTED (real bug, found via independent testing outside the
        # delivered fixture suite -- not caught by the original test file,
        # since none of its cases had a tied/flat-topped peak): the previous
        # version computed len(w)-1 - w.values.argmax(). np.argmax() breaks
        # ties by returning the FIRST occurrence, so if a stock sat flat at
        # its local high for several consecutive days before pulling back,
        # this counted from the OLDEST day of that plateau instead of the
        # most recent one -- overstating days_since_local_high and letting a
        # genuinely recent, shallow pullback fail the <=10-day check purely
        # from this artifact. Confirmed relevant to this project specifically:
        # STATUS-technical-thread.md documents NDRL as a thin/flat-trading
        # EGX ticker, exactly the condition that triggers this.
        #
        # Fix: reverse the window (w.values[::-1], now newest-first) before
        # taking argmax(). Ties then resolve to the FIRST occurrence when
        # scanning from today backward -- i.e. the most recent day at the
        # peak -- and the reversed index IS the offset-from-end directly, no
        # further len(w)-1-... arithmetic needed.
        offset_from_end = np.argmax(w.values[::-1])
        return offset_from_end

    days_since_local_high = price_series.rolling(window).apply(_days_since_max, raw=False)

    return pd.DataFrame({
        "local_high": local_high,
        "pullback_depth": pullback_depth,
        "days_since_local_high": days_since_local_high,
    })


def leader_pullback_shallow(leader_prices, as_of=None, window=LOCAL_HIGH_WINDOW,
                             depth_max=PULLBACK_DEPTH_MAX, duration_max=PULLBACK_DURATION_MAX_DAYS):
    """
    leader_prices: dict of {ticker: price_series}, ALREADY filtered to the
    current cycle's leader basket (i.e. the caller already ran
    get_leader_tickers() fresh and is passing only those tickers' prices --
    this function does not re-derive the basket itself).
    as_of: the date to evaluate at (defaults to each series' last date; all
    series must share the same index for a single as_of to make sense).

    Rule (Section 2.3): AVG pullback depth across the leader basket <= 10%
    AND AVG days-since-local-high across the basket <= 10 trading days.
    Both averaged the same way, since the spec explicitly says "avg pullback
    %" for depth and doesn't separately describe a different aggregation
    for duration -- this project's resolution, documented here rather than
    left implicit.

    Returns (passed: bool, diagnostics: dict).
    """
    depths = []
    durations = []
    for tkr, prices in leader_prices.items():
        metrics = compute_pullback_metrics(prices, window=window)
        row = metrics.loc[as_of] if as_of is not None else metrics.iloc[-1]
        depths.append(row["pullback_depth"])
        durations.append(row["days_since_local_high"])

    avg_depth = sum(depths) / len(depths) if depths else float("nan")
    avg_duration = sum(durations) / len(durations) if durations else float("nan")

    passed = (avg_depth <= depth_max) and (avg_duration <= duration_max)
    return passed, {
        "avg_pullback_depth": avg_depth,
        "avg_days_since_local_high": avg_duration,
        "n_leaders": len(leader_prices),
        "per_ticker_depth": dict(zip(leader_prices.keys(), depths)),
        "per_ticker_duration": dict(zip(leader_prices.keys(), durations)),
    }


# ---------------------------------------------------------------------------
# Condition 3: leader_divergence (Section 2.4)
# ---------------------------------------------------------------------------

def compute_higher_low(price_series, window=DIVERGENCE_WINDOW):
    """
    per-stock higher_low[t] = low_Nd[t] > low_Nd[t-N]
    Same "compare a rolling stat to itself N days earlier" pattern as tt_4's
    sma_200 slope check and new_high_low_ratio_favorable above -- rolling
    MIN here (a "low"), not a moving average or a max.
    """
    low_nd = price_series.rolling(window).min()
    return low_nd > low_nd.shift(window)


def leader_divergence(leader_higher_low_flags, universe_higher_low_flags,
                       pivot=DIVERGENCE_PIVOT_LEADER,
                       universe_pivot=DIVERGENCE_PIVOT_UNIVERSE):
    """
    leader_higher_low_flags: iterable of bool, one per leader-basket ticker,
      each ticker's higher_low[t] as of the date being evaluated.
    universe_higher_low_flags: same, but for the full EGX universe.

    leader_condition   = (% of leader basket with higher_low=True) > 40%   (C5)
    universe_condition = (% of full universe with higher_low=True) < 50%
    leader_divergence  = leader_condition AND universe_condition

    Section 2.4's "general index" clause is proxied by full-universe breadth
    here (a deliberate v1 simplification -- no separate EGX benchmark index
    series in the current data pipeline; documented, not silently done).
    50% is a majority/plurality pivot, not an invented magnitude gap (the
    prior 15-percentage-point gap version is explicitly superseded per
    Section 2.6 -- if you see that version anywhere else, it's stale).

    Returns (passed: bool, diagnostics: dict).
    """
    leader_list = list(leader_higher_low_flags)
    universe_list = list(universe_higher_low_flags)

    leader_pct = sum(leader_list) / len(leader_list) if leader_list else float("nan")
    universe_pct = sum(universe_list) / len(universe_list) if universe_list else float("nan")

    leader_condition = leader_pct > pivot
    universe_condition = universe_pct < universe_pivot
    passed = leader_condition and universe_condition

    return passed, {
        "leader_pct_higher_low": leader_pct,
        "universe_pct_higher_low": universe_pct,
        "leader_condition": leader_condition,
        "universe_condition": universe_condition,
        "leader_pivot": pivot,
        "universe_pivot": universe_pivot,
    }


# ---------------------------------------------------------------------------
# AND-gate combinator (Section 2.1 -- the corrected OR-to-AND fix)
# ---------------------------------------------------------------------------

def market_regime_gate(ratio_favorable, pullback_shallow, divergence,
                        min_conditions=None):
    """
    ratio_favorable, pullback_shallow, divergence: bool, the three already-
    evaluated condition results for the cycle being checked.

    gate = (number of TRUE conditions) >= REGIME_GATE_MIN_CONDITIONS

    HISTORY, so this is not silently re-litigated later:
      - original: AND (all three) — too restrictive, gate almost never opened
      - v0.27:    OR  (any one)   — "profit-first" loosening
      - 2 of 3 was tried after the IS review and REVERTED; REGIME_GATE_MIN_CONDITIONS = 1 (OR) is current

    Setting min_conditions=1 reproduces the v0.27 OR gate exactly, and
    min_conditions=3 reproduces the original AND gate.

    Returns (passed: bool, diagnostics: dict).
    """
    if min_conditions is None:
        min_conditions = REGIME_GATE_MIN_CONDITIONS
    conditions = {
        "new_high_low_ratio_favorable": bool(ratio_favorable),
        "leader_pullback_shallow": bool(pullback_shallow),
        "leader_divergence": bool(divergence),
    }
    n_true = sum(conditions.values())
    passed = n_true >= min_conditions
    return passed, {
        **conditions,
        "conditions_met": n_true,
        "min_conditions_required": min_conditions,
        "gate_open": passed,
    }
