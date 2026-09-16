"""
Known-answer tests for JOB 2 — the share-count-scaled floor in
independent_auditor.trade_tolerance().

The five cases below are the exact fills the IS run flagged as discrepancies
(trade_log_EGX_IS_20260904.csv). Each was pure sub-cent rounding compounding
across a large share count, not an accounting fault. Predictions hand-derived
before running.
"""

import pytest

from independent_auditor import (
    TOLERANCE_PCT_OF_POSITION,
    TOLERANCE_PER_SHARE,
    trade_tolerance,
)

# ticker, shares, entry_price, observed discrepancy, tolerance under the OLD formula
FLAGGED_FILLS = [
    ("DSCW", 6024, 0.5653, 0.5521, 0.3405),
    ("MOIL", 10548, 0.2492, 0.5208, 0.2629),
    ("MOIL", 11378, 0.2703, 0.3394, 0.3075),
    ("MOIL", 12073, 0.2550, 0.3609, 0.3079),
    ("MOIL", 14006, 0.2242, 0.3440, 0.3140),
]


@pytest.mark.parametrize(
    "ticker, shares, price, diff, old_tol",
    FLAGGED_FILLS,
    ids=[f"{t}-{s}sh" for t, s, _, _, _ in FLAGGED_FILLS],
)
def test_f1_flagged_fills_now_pass(ticker, shares, price, diff, old_tol):
    """
    PREDICTION: the per-share term (shares x 0.0001) is 0.6024 for DSCW and
    1.05-1.40 for the four MOIL fills, in every case above the observed
    discrepancy — so all five clear. Each also failed under the old formula,
    which is asserted here so the test proves the fix did the work.
    """
    assert diff > old_tol, "case must have failed under the old formula"
    new_tol = trade_tolerance(price, shares)
    assert diff <= new_tol, f"{ticker} {shares}sh: diff {diff} > tol {new_tol}"


def test_f1b_per_share_term_is_what_rescues_them():
    """
    PREDICTION: for all five, the per-share term strictly dominates the
    value term — these are low-price / high-share-count positions, the exact
    regime where position value understates accumulated rounding.
    """
    for _, shares, price, _, _ in FLAGGED_FILLS:
        value_term = price * shares * TOLERANCE_PCT_OF_POSITION
        share_term = shares * TOLERANCE_PER_SHARE
        assert share_term > value_term


def test_f2_dscw_exact_values():
    """
    PREDICTION: DSCW 6,024 sh @ 0.5653.
      value term = 0.5653 x 6024 x 0.0001 = 0.34053...
      share term = 6024 x 0.0001         = 0.60240
      tolerance  = 0.60240, and 0.5521 <= 0.60240.
    Tightest of the five — the one that pins the constant.
    """
    tol = trade_tolerance(0.5653, 6024)
    assert tol == pytest.approx(0.6024, abs=1e-6)
    assert 0.5521 <= tol
    assert tol - 0.5521 == pytest.approx(0.0503, abs=1e-4)


def test_f3_normal_priced_names_unchanged():
    """
    PREDICTION: at 166.00 x 100 sh the value term is 1.66 and the share term
    only 0.01, so the value term still governs — the fix does not loosen
    tolerance on ordinary positions.
    """
    assert trade_tolerance(166.0, 100) == pytest.approx(1.66, abs=1e-9)
    assert trade_tolerance(50.0, 500) == pytest.approx(2.50, abs=1e-9)


def test_f4_absolute_floor_still_holds():
    """PREDICTION: tiny positions floor at 0.01 EGP, unchanged."""
    assert trade_tolerance(1.0, 1) == 0.01
    assert trade_tolerance(0.01, 10) == 0.01
    assert trade_tolerance(0.0, 0) == 0.01


def test_f5_monotonic_in_shares_and_price():
    """PREDICTION: tolerance never decreases as shares or price grow."""
    tols = [trade_tolerance(0.50, n) for n in (100, 1000, 10000, 100000)]
    assert tols == sorted(tols)
    tols = [trade_tolerance(p, 1000) for p in (0.1, 1.0, 10.0, 100.0)]
    assert tols == sorted(tols)


def test_f6_bad_input_falls_back_to_floor():
    """PREDICTION: unparseable inputs return the 0.01 floor, never raise."""
    assert trade_tolerance(None, 100) == 0.01
    assert trade_tolerance("abc", 100) == 0.01
    assert trade_tolerance(1.0, None) == 0.01


def test_f7_negative_inputs_use_magnitude():
    """PREDICTION: a short/negative share count is taken by magnitude."""
    assert trade_tolerance(0.5653, -6024) == pytest.approx(0.6024, abs=1e-6)
    assert trade_tolerance(-0.5653, 6024) == pytest.approx(0.6024, abs=1e-6)
