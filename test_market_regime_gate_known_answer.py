"""
Known-answer regression test for Feature 3 (Market Regime Gate):
market_regime_gate.py, covering all 5 fixtures from
feature-03-market-regime-gate-rules.md Section 3.

Imports and calls the REAL project functions -- not re-typed copies of their
formulas.

--------------------------------------------------------------------------
BUG FIX -- _days_since_max() tie-breaking (found via independent testing)
--------------------------------------------------------------------------
market_regime_gate.py's compute_pullback_metrics() originally computed
days_since_local_high as len(w)-1 - w.values.argmax(). np.argmax() breaks
ties by returning the FIRST occurrence, so a stock sitting flat at its local
high for several consecutive days had its "days since the local high" measured
from the OLDEST day of that plateau. Fixed to use reversed argmax.
Fixture 2D below is the regression test for this specific case.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from market_regime_gate import (  # noqa: E402
    compute_new_high_low_ratio, new_high_low_ratio_favorable,
    compute_pullback_metrics, leader_pullback_shallow,
    compute_higher_low, leader_divergence,
    market_regime_gate, get_leader_tickers,
)

TOL = 1e-6


# ---- Fixture 2 helpers (leader pullback series builders) ----

def _build_2a():
    ramp = list(np.linspace(70, 99, 24))
    decline = [99, 98, 97, 96, 95]
    return pd.Series(ramp + [100] + decline, index=pd.RangeIndex(1, 31))


def _build_2b():
    ramp = list(np.linspace(70, 99, 24))
    decline = list(np.linspace(97, 85, 5))
    return pd.Series(ramp + [100] + decline, index=pd.RangeIndex(1, 31))


def _build_2c():
    ramp = list(np.linspace(70, 99, 14))
    decline = list(np.linspace(99, 92, 15))
    return pd.Series(ramp + [100] + decline, index=pd.RangeIndex(1, 31))


def _build_2d():
    ramp = list(np.linspace(70, 99, 15))
    plateau = [100.0] * 7
    decline = list(np.linspace(99, 93, 8))
    return pd.Series(ramp + plateau + decline, index=pd.RangeIndex(1, 31))


# ==================================================================
# FIXTURE 1 -- new_high_low_ratio_favorable
# ==================================================================

def test_fixture1_ratio_favorable():
    days = pd.RangeIndex(1, 25)
    count_high = pd.Series([10] * 21 + [20, 3, 8], index=days)
    count_low = pd.Series([5] * 21 + [0, 12, 0], index=days)
    ratio = compute_new_high_low_ratio(count_high, count_low)
    favorable = new_high_low_ratio_favorable(ratio)

    assert abs(ratio[22] - 20.0) < TOL
    assert abs(ratio[24] - 8.0) < TOL
    assert pd.notna(ratio[22]) and ratio[22] != float("inf")
    assert bool(favorable[22]) is True
    assert bool(favorable[23]) is False
    assert bool(favorable[24]) is True


def test_fixture1_early_days_not_evaluable():
    days = pd.RangeIndex(1, 25)
    count_high = pd.Series([10] * 21 + [20, 3, 8], index=days)
    count_low = pd.Series([5] * 21 + [0, 12, 0], index=days)
    ratio = compute_new_high_low_ratio(count_high, count_low)
    assert pd.isna(ratio.shift(21)[21])


# ==================================================================
# FIXTURE 2 -- leader_pullback_shallow
# ==================================================================

def test_fixture2a_passes_both():
    pass_2a, diag_2a = leader_pullback_shallow({"L1": _build_2a()})
    assert abs(diag_2a["avg_pullback_depth"] - 0.05) < 0.001
    assert diag_2a["avg_days_since_local_high"] == 5.0
    assert bool(pass_2a) is True


def test_fixture2b_fails_depth():
    pass_2b, diag_2b = leader_pullback_shallow({"L1": _build_2b()})
    assert abs(diag_2b["avg_pullback_depth"] - 0.15) < 0.001
    assert diag_2b["avg_days_since_local_high"] == 5.0
    assert bool(pass_2b) is False


def test_fixture2c_boundary_duration():
    pass_2c, diag_2c = leader_pullback_shallow({"L1": _build_2c()})
    assert abs(diag_2c["avg_pullback_depth"] - 0.08) < 0.001
    assert diag_2c["avg_days_since_local_high"] == 15.0
    assert bool(pass_2c) is True


def test_fixture2d_plateau_tie_breaking():
    pass_2d, diag_2d = leader_pullback_shallow({"L1": _build_2d()})
    assert abs(diag_2d["avg_pullback_depth"] - 0.07) < 0.001
    assert diag_2d["avg_days_since_local_high"] == 8.0
    assert bool(pass_2d) is True


# ==================================================================
# FIXTURE 3 -- leader_divergence
# ==================================================================

def test_fixture3a_both_favorable():
    leader_60 = [True] * 6 + [False] * 4
    universe_35 = [True] * 7 + [False] * 13
    pass_3a, diag_3a = leader_divergence(leader_60, universe_35)
    assert abs(diag_3a["leader_pct_higher_low"] - 0.6) < TOL
    assert abs(diag_3a["universe_pct_higher_low"] - 0.35) < TOL
    assert pass_3a is True


def test_fixture3b_leader_pivot_c5():
    leader_45 = [True] * 9 + [False] * 11
    universe_35 = [True] * 7 + [False] * 13
    pass_3b, diag_3b = leader_divergence(leader_45, universe_35)
    assert abs(diag_3b["leader_pct_higher_low"] - 0.45) < TOL
    # C5 pivot change: leader pivot 0.50 -> 0.40, so 45% now passes
    assert pass_3b is True


def test_fixture3c_unfavorable_universe():
    leader_60 = [True] * 6 + [False] * 4
    universe_55 = [True] * 11 + [False] * 9
    pass_3c, diag_3c = leader_divergence(leader_60, universe_55)
    assert abs(diag_3c["universe_pct_higher_low"] - 0.55) < TOL
    assert pass_3c is False


# ==================================================================
# FIXTURE 4 -- full gate OR-logic
# ==================================================================

def test_fixture4_all_true():
    gate, diag = market_regime_gate(True, True, True)
    assert gate is True


def test_fixture4_two_of_three():
    assert market_regime_gate(True, True, False)[0] is True
    assert market_regime_gate(False, True, True)[0] is True
    assert market_regime_gate(True, False, True)[0] is True


def test_fixture4_one_of_three_or_gate():
    assert market_regime_gate(True, False, False)[0] is True
    assert market_regime_gate(False, True, False)[0] is True
    assert market_regime_gate(False, False, True)[0] is True


def test_fixture4_none_true():
    gate, _ = market_regime_gate(False, False, False)
    assert gate is False


def test_fixture4_diagnostics():
    _, diag = market_regime_gate(True, True, False)
    assert diag["conditions_met"] == 2
    assert diag["min_conditions_required"] == 1


def test_fixture4_min_conditions_override():
    assert market_regime_gate(False, True, False, min_conditions=2)[0] is False
    assert market_regime_gate(True, True, False, min_conditions=3)[0] is False


# ==================================================================
# FIXTURE 5 -- leader basket freshness (statelessness)
# ==================================================================

def test_fixture5_leader_basket_stateless():
    cycle1 = {"A": 95, "B": 92, "C": 88, "D": 60, "E": 30}
    cycle2 = {"A": 70, "B": 40, "C": 96, "D": 93, "E": 91}

    basket1 = get_leader_tickers(cycle1)
    basket2 = get_leader_tickers(cycle2)
    basket1_again = get_leader_tickers(cycle1)

    assert basket1 == ["A", "B"]
    assert basket2 == ["C", "D", "E"]
    assert basket1_again == ["A", "B"]
