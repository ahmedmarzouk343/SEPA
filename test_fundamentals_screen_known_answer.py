"""
Known-answer regression test for Feature 2 (Fundamentals Screen) -- v3 REBUILD.

Tests evaluate_fundamentals() -- the 3-question fundamentals screen per
feature-02-fundamentals-screen-rules.md v3. Replaces the old composite-scoring
test fixtures entirely.

--------------------------------------------------------------------------
WRITTEN PREDICTIONS -- hand-calculated BEFORE running the real code
--------------------------------------------------------------------------

FIXTURE 1 -- Clean pass.
  EPS: [0.20, 0.25, 0.28, 0.35], Revenue: [0.22].
  Q1: 35% >= 20% -> PASS. Q2: avg(0.28,0.35)=0.315 > avg(0.20,0.25)=0.225 -> PASS. Q3: 22% > 0 -> PASS.
  PREDICTED: PASS.

FIXTURE 2 -- Q1 fails (below 20% floor).
  EPS: [0.15], Revenue: [0.10].
  Q1: 15% < 20% -> FAIL. Q2/Q3 not evaluated.
  PREDICTED: FAIL.

FIXTURE 3 -- Q2 fails (deceleration).
  EPS: [0.55, 0.50, 0.48, 0.35], Revenue: [0.20].
  Q1: 35% >= 20% -> PASS. Q2: avg(0.48,0.35)=0.415 < avg(0.55,0.50)=0.525 -> FAIL.
  PREDICTED: FAIL.

FIXTURE 4 -- Q3 fails (revenue declining).
  EPS: [0.20, 0.25, 0.30, 0.40], Revenue: [-0.05].
  Q1: 40% >= 20% -> PASS. Q2: avg(0.30,0.40)=0.35 > avg(0.20,0.25)=0.225 -> PASS. Q3: -5% <= 0 -> FAIL.
  PREDICTED: FAIL.

FIXTURE 5 -- Q2 skipped (only 1 quarter of data).
  EPS: [0.25], Revenue: [0.10].
  Q1: 25% >= 20% -> PASS. Q2: SKIPPED (1 quarter). Q3: 10% > 0 -> PASS.
  PREDICTED: PASS.

FIXTURE 6 -- Q3 skipped (no revenue data).
  EPS: [0.15, 0.18, 0.22, 0.30], Revenue: None.
  Q1: 30% >= 20% -> PASS. Q2: avg(0.22,0.30)=0.26 > avg(0.15,0.18)=0.165 -> PASS. Q3: SKIPPED.
  PREDICTED: PASS.

FIXTURE 7 -- Turnaround override, fails.
  category=turnaround, EPS: [0.85].
  Q1: 85% < 100% turnaround threshold -> FAIL. Q2/Q3 not evaluated.
  PREDICTED: FAIL.

FIXTURE 8 -- Turnaround override, passes.
  category=turnaround, EPS: [0.70, 0.80, 0.90, 1.20], Revenue: [0.15].
  Q1: 120% >= 100% -> PASS. Q2: avg(0.90,1.20)=1.05 > avg(0.70,0.80)=0.75 -> PASS. Q3: 15% > 0 -> PASS.
  PREDICTED: PASS.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fundamentals_screen import evaluate_fundamentals  # noqa: E402


def test_fixture1_clean_pass():
    f1 = evaluate_fundamentals({
        "eps_yoy_growth_by_quarter": [0.20, 0.25, 0.28, 0.35],
        "revenue_yoy_growth_by_quarter": [0.22],
    })
    assert f1["pass"] is True
    assert f1["q1"]["status"] == "PASS"
    assert f1["q2"]["status"] == "PASS"
    assert f1["q3"]["status"] == "PASS"


def test_fixture2_q1_fails():
    f2 = evaluate_fundamentals({
        "eps_yoy_growth_by_quarter": [0.15],
        "revenue_yoy_growth_by_quarter": [0.10],
    })
    assert f2["pass"] is False
    assert f2["q1"]["status"] == "FAIL"
    assert f2["q2"]["status"] == "NOT_EVALUATED"
    assert f2["q3"]["status"] == "NOT_EVALUATED"


def test_fixture3_q2_deceleration():
    f3 = evaluate_fundamentals({
        "eps_yoy_growth_by_quarter": [0.55, 0.50, 0.48, 0.35],
        "revenue_yoy_growth_by_quarter": [0.20],
    })
    assert f3["pass"] is False
    assert f3["q1"]["status"] == "PASS"
    assert f3["q2"]["status"] == "FAIL"


def test_fixture4_q3_revenue_declining():
    f4 = evaluate_fundamentals({
        "eps_yoy_growth_by_quarter": [0.20, 0.25, 0.30, 0.40],
        "revenue_yoy_growth_by_quarter": [-0.05],
    })
    assert f4["pass"] is False
    assert f4["q1"]["status"] == "PASS"
    assert f4["q2"]["status"] == "PASS"
    assert f4["q3"]["status"] == "FAIL"


def test_fixture5_q2_skipped_one_quarter():
    f5 = evaluate_fundamentals({
        "eps_yoy_growth_by_quarter": [0.25],
        "revenue_yoy_growth_by_quarter": [0.10],
    })
    assert f5["pass"] is True
    assert f5["q1"]["status"] == "PASS"
    assert f5["q2"]["status"] == "SKIPPED"
    assert f5["q3"]["status"] == "PASS"


def test_fixture6_q3_skipped_no_revenue():
    f6 = evaluate_fundamentals({
        "eps_yoy_growth_by_quarter": [0.15, 0.18, 0.22, 0.30],
        "revenue_yoy_growth_by_quarter": None,
    })
    assert f6["pass"] is True
    assert f6["q1"]["status"] == "PASS"
    assert f6["q2"]["status"] == "PASS"
    assert f6["q3"]["status"] == "SKIPPED"


def test_fixture7_turnaround_fails():
    f7 = evaluate_fundamentals({
        "eps_yoy_growth_by_quarter": [0.85],
        "revenue_yoy_growth_by_quarter": [0.20],
    }, category="turnaround")
    assert f7["pass"] is False
    assert f7["q1"]["status"] == "FAIL"
    assert f7["q1"]["threshold"] == 1.00


def test_fixture8_turnaround_passes():
    f8 = evaluate_fundamentals({
        "eps_yoy_growth_by_quarter": [0.70, 0.80, 0.90, 1.20],
        "revenue_yoy_growth_by_quarter": [0.15],
    }, category="turnaround")
    assert f8["pass"] is True
    assert f8["q1"]["status"] == "PASS"
    assert f8["q1"]["threshold"] == 1.00
    assert f8["q2"]["status"] == "PASS"
    assert f8["q3"]["status"] == "PASS"


def test_edge_no_eps_data():
    f = evaluate_fundamentals({"eps_yoy_growth_by_quarter": None})
    assert f["pass"] is False
    assert f["q1"]["status"] == "SKIPPED"


def test_edge_empty_eps_list():
    f = evaluate_fundamentals({"eps_yoy_growth_by_quarter": []})
    assert f["pass"] is False


def test_edge_equal_growth_q2_fails():
    f = evaluate_fundamentals({
        "eps_yoy_growth_by_quarter": [0.30, 0.30, 0.30, 0.30],
        "revenue_yoy_growth_by_quarter": [0.10],
    })
    assert f["q2"]["status"] == "FAIL"
    assert f["pass"] is False


def test_edge_zero_revenue_q3_fails():
    f = evaluate_fundamentals({
        "eps_yoy_growth_by_quarter": [0.20, 0.30],
        "revenue_yoy_growth_by_quarter": [0.0],
    })
    assert f["q3"]["status"] == "FAIL"


def test_edge_exact_threshold_q1_passes():
    f = evaluate_fundamentals({
        "eps_yoy_growth_by_quarter": [0.20],
        "revenue_yoy_growth_by_quarter": [0.05],
    })
    assert f["q1"]["status"] == "PASS"
