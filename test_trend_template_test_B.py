"""
Test B -- known-answer regression test for tt_9 (relative strength percentile),
tested separately from Test A since it needs a multi-stock universe rather than
a single self-contained series.

Imports and calls the REAL project function compute_rs_percentile() from
trend_template_test.py -- not a re-typed copy of its rank/percentile formula.

--------------------------------------------------------------------------
FIXTURE
--------------------------------------------------------------------------
9 synthetic series (S1..S9), each a pure constant-daily-growth-rate path:
  close_i(t) = 100 * (1 + r_i) ** t
with 9 distinct, strictly increasing daily rates r_i (from -0.20% to +0.40%
per day). This was chosen and verified (via an independent scratch
calculation, before writing this file) to make each series' trailing-252-day
return exactly TIME-STABLE once past the 252-day warmup -- identical at every
evaluable day (253, 260, 270, 280 all produced identical ret_252 per series
in the pre-check) -- so the predicted rank order isn't a one-day fluke, it's
structural, and the test checks it across every evaluable day, not just the
last one.

--------------------------------------------------------------------------
WRITTEN PREDICTIONS -- BEFORE running the real code
--------------------------------------------------------------------------
Per the task's own instruction: only the RELATIVE ranking is predicted here
(S1 lowest ... S9 highest, stable across every evaluable day), not precise
percentile values -- 9 series only gives ~11%-wide resolution
(100/9 = 11.11 percentage points per rank step), so claiming exact percentile
figures to more precision than that would be overstating what this fixture
can actually prove.

  Rank order, lowest to highest (every evaluable day): S1 < S2 < S3 < S4 <
  S5 < S6 < S7 < S8 < S9, with no ties and no exceptions on any day.

  Consequence for tt_9 (>=70 percentile threshold, RS_THRESHOLD in the real
  code): with 9 evenly-ranked series and no ties, ranks map to pct =
  rank/9 * 100 = 11.1, 22.2, 33.3, 44.4, 55.6, 66.7, 77.8, 88.9, 100.0.
  The three highest -- S7, S8, S9 -- clear the >=70 bar; S1 through S6 do
  not. (I initially mis-estimated this as "top 2 of 9" before actually
  computing it -- rank 7/9 = 77.8%, which already clears 70, so it's the
  top THREE, not two. Recorded here as a reminder that arithmetic estimates
  should be checked, not trusted, even for something this simple.)

IMPORTANT SCOPE NOTE (required by the task): this test confirms the RANKING
MATH is directionally correct -- it does NOT validate that the 70th-percentile
cutoff itself is a well-calibrated threshold for real markets. That would
need a much larger synthetic universe (or the real ~224-ticker universe) to
stress-test properly; 9 series is only enough to prove the rank/percentile
computation orders things correctly, nothing about where the cutoff should
sit in practice.

--------------------------------------------------------------------------
CORRECTION -- caught when compute_rs_percentile() was later fixed
--------------------------------------------------------------------------
compute_rs_percentile() originally used dropna(how="any") internally, which
meant its OUTPUT was already pre-filtered to only the 28 genuinely-evaluable
days (253-280) -- so this test's original code could get away with treating
`len(rs_pct)` and "iterate every row of rs_pct" as synonymous with "every
evaluable day." That assumption broke the moment compute_rs_percentile() was
corrected to use na_option='keep' (see trend_template_test.py's own docstring
for why that correction was necessary at production scale): the function no
longer drops the 252 non-evaluable warmup rows, it returns all 280 rows with
NaN in the non-evaluable ones. Rerunning this test against the corrected
function immediately surfaced the gap -- "Evaluable days: 280" and "252
rank-order violations" -- because the old NaN-comparison-resolves-to-False
gotcha (documented elsewhere in this project) made every all-NaN warmup row
register as a fake "violation." This was a bug in THIS test's own filtering
logic, never present in compute_rs_percentile() itself or in any of its
outputs -- fixed below by explicitly restricting to rows where every series
has a real value before checking rank order, instead of assuming the
DataFrame's row count already meant that.
"""

import sys
import os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trend_template_test import compute_rs_percentile, RS_THRESHOLD  # noqa: E402

NAMES = [f"S{i+1}" for i in range(9)]
RATES = [-0.0020, -0.0010, 0.0000, 0.0005, 0.0010, 0.0015, 0.0020, 0.0030, 0.0040]
PREDICTED_PASSERS = {"S7", "S8", "S9"}


def build_fixture():
    n = 280
    idx = pd.RangeIndex(1, n + 1)
    closes = {name: pd.Series(100 * (1 + r) ** np.arange(n), index=idx)
              for name, r in zip(NAMES, RATES)}
    ret_wide = pd.DataFrame({name: c / c.shift(252) - 1 for name, c in closes.items()})
    return ret_wide


def main():
    ret_wide = build_fixture()
    rs_pct = compute_rs_percentile(ret_wide)  # the REAL project function

    # compute_rs_percentile() (na_option='keep') returns one row per input date,
    # NaN on days it can't compute -- it does NOT pre-filter to evaluable-only
    # rows the way the old dropna(how="any") version did. Must filter explicitly
    # here rather than assume rs_pct's row count already means "evaluable."
    evaluable = rs_pct[NAMES].notna().all(axis=1)
    rs_pct_eval = rs_pct[evaluable]

    print(f"Total dates in table: {len(rs_pct)}. Evaluable (valid 252d return for all 9 series): "
          f"{len(rs_pct_eval)} (predicted: 28)")
    if len(rs_pct_eval) > 0:
        print(f"  Evaluable range: day {rs_pct_eval.index.min()} -> day {rs_pct_eval.index.max()}")
    print()

    failures = []
    if len(rs_pct_eval) != 28:
        failures.append(f"Expected exactly 28 evaluable days, got {len(rs_pct_eval)}")

    # --- Rank order must hold on EVERY evaluable day, not just the last one ---
    order_violations = 0
    for d, row in rs_pct_eval.iterrows():
        ordered = row[NAMES].values
        if not np.all(np.diff(ordered) > 0):  # strictly increasing S1..S9
            order_violations += 1
    print(f"Days where S1<S2<...<S9 rank order did NOT hold: {order_violations} "
          f"(predicted: 0, out of {len(rs_pct_eval)} evaluable days)")
    if order_violations > 0:
        failures.append(f"Rank order violated on {order_violations} evaluable day(s)")

    # --- Spot-check the exact percentile values at the last evaluable day ---
    last_day = rs_pct_eval.index.max()
    actual_pct = rs_pct_eval.loc[last_day, NAMES].round(1)
    expected_pct = pd.Series([round((i + 1) / 9 * 100, 1) for i in range(9)], index=NAMES)
    print(f"\nPercentiles at day {last_day} (predicted vs actual):")
    cmp = pd.DataFrame({"predicted": expected_pct, "actual": actual_pct})
    print(cmp)
    mismatches = cmp[(cmp["predicted"] - cmp["actual"]).abs() > 0.1]
    if len(mismatches) > 0:
        failures.append(f"Percentile mismatch beyond rounding tolerance:\n{mismatches}")

    # --- tt_9 pass/fail at the threshold ---
    passers = set(rs_pct_eval.loc[last_day][rs_pct_eval.loc[last_day] >= RS_THRESHOLD].index)
    print(f"\ntt_9 passers at day {last_day} (RS_THRESHOLD={RS_THRESHOLD}): {sorted(passers)}")
    print(f"Predicted passers: {sorted(PREDICTED_PASSERS)}")
    if passers != PREDICTED_PASSERS:
        failures.append(f"tt_9 passer set mismatch: predicted {PREDICTED_PASSERS}, got {passers}")

    print()
    print("=" * 70)
    if failures:
        print(f"RESULT: MISMATCH -- {len(failures)} prediction(s) violated:")
        for f in failures:
            print(f"  - {f}")
    else:
        print("RESULT: MATCH -- rank order and threshold behavior confirmed exactly.")
    print("NOTE: this confirms ranking math is directionally correct. It does NOT")
    print("validate the 70th-percentile cutoff's real-world calibration -- see")
    print("module docstring scope note.")
    print("=" * 70)
    return len(failures) == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
