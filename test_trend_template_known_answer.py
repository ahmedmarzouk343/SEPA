"""
Known-answer regression test for the Trend Template hard_filter logic.

Purpose: prove the AND-gate condition logic in trend_template_test.py is
actually correct, using a synthetic price series with a KNOWN, independently
derived correct answer -- not just "does it look plausible on real stocks."

This test imports and calls the REAL project functions (compute_indicators,
evaluate_conditions) from trend_template_test.py. It does not re-type the
condition formulas -- if it did, it would only be testing a copy of the logic,
not the logic itself.

--------------------------------------------------------------------------
FIXTURE DESIGN NOTE -- read before trusting the predictions below
--------------------------------------------------------------------------
A naive "flat/declining for 260 days, then a sharp rally for exactly the last
20 days" fixture does NOT work: it was tried first (see project notes) and
confirmed, by independent scratch calculation, that a 150-day and 200-day
trailing SMA cannot invert their multi-month relationship in just 20 days no
matter how steep the rally is -- tt_3 (sma_150 > sma_200) and tt_4 (sma_200's
21-day slope) both require real elapsed time, not just price magnitude. This
is a real, correct property of the underlying moving averages, not a fixture
bug -- and it's the same reason a freshly-started rally can never validly
satisfy the full Trend Template on day 1.

So the price recovery here begins at day 241 (not day 261), giving the slow
SMA-based conditions the ~20 trading days of runway they mechanically need to
fully invert. The Trend Template's own output (all_pass) is verified, via an
independent from-scratch pandas calculation done BEFORE writing this file, to
stay FALSE for every single day through day 260 despite price already having
turned upward from day 241 -- i.e. the filter is expected to show correct,
deliberate lag/conservatism during days 241-260, not an early false-positive.
Only days 261-280 are expected to be a clean, unanimous PASS.

A second, perfectly flat comparison ticker is included solely so tt_9
(relative strength percentile) is computable at all -- with only 2 names, the
top-returning one always lands at the 100th percentile (passes the >=70 bar)
and the other at the 50th (fails it), which is enough to exercise tt_9's real
logic without needing a full universe.

--------------------------------------------------------------------------
PREDICTION (written BEFORE running evaluate_conditions on this fixture)
--------------------------------------------------------------------------
- Days 1-252 (of the TEST series): NOT EVALUABLE -- fewer than 252 trailing
  days exist yet for the 52-week range / RS return calculation. Excluded from
  scoring, not counted as a fail.
- Days 253-260 (the only evaluable days in the nominal "should fail" range):
  ALL_PASS = False. Price has begun recovering (day 241 onward) but the SMA
  ordering/slope conditions have not yet caught up.
- Days 261-280 (all 20 trading days): ALL_PASS = True, unanimously, with no
  exceptions.
"""

import sys
import os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trend_template_test import compute_indicators, evaluate_conditions, RS_THRESHOLD  # noqa: E402


def build_fixture():
    n = 280
    dates = pd.bdate_range("2024-01-01", periods=n)

    test_price = np.empty(n)
    test_price[0:240] = np.linspace(105, 95, 240)
    test_price[240:280] = np.linspace(95, 220, 40)
    test_close = pd.Series(test_price, index=dates, name="Close")

    comp_price = np.full(n, 100.0)
    comp_close = pd.Series(comp_price, index=dates, name="Close")

    def to_ohlc(close_series):
        return pd.DataFrame({"Close": close_series, "High": close_series, "Low": close_series})

    return to_ohlc(test_close), to_ohlc(comp_close)


def _run_fixture():
    test_raw, comp_raw = build_fixture()
    test_df = compute_indicators(test_raw)
    comp_df = compute_indicators(comp_raw)
    ret_wide = pd.DataFrame({"TEST": test_df["ret_252"], "COMP": comp_df["ret_252"]})
    rs_pct = ret_wide.rank(axis=1, pct=True, method="average", na_option="keep") * 100
    cond, evaluable, all_pass = evaluate_conditions(test_df, rs_pct["TEST"])
    day_num = pd.Series(range(1, len(test_df) + 1), index=test_df.index)
    return cond, evaluable, all_pass, day_num


def test_days_1_252_not_evaluable():
    _, evaluable, _, day_num = _run_fixture()
    early_mask = day_num <= 252
    assert not evaluable[early_mask].any(), "No day before 253 should be evaluable"


def test_days_253_260_evaluable_but_fail():
    _, evaluable, all_pass, day_num = _run_fixture()
    mask = (day_num >= 253) & (day_num <= 260)
    assert evaluable[mask].sum() == 8, "All 8 days 253-260 should be evaluable"
    passing = all_pass[mask & evaluable]
    assert not passing.any(), "No day in 253-260 should pass all conditions"


def test_days_261_280_all_pass():
    _, evaluable, all_pass, day_num = _run_fixture()
    mask = (day_num >= 261) & (day_num <= 280)
    assert evaluable[mask].sum() == 20, "All 20 days 261-280 should be evaluable"
    n_pass = int(all_pass[mask & evaluable].sum())
    assert n_pass == 20, f"All 20 days 261-280 should pass, got {n_pass}"
