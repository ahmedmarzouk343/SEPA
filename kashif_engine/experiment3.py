"""Experiment 3 historical tests: the frozen arm definitions and windows.

The arms are the model-book hypotheses committed in 7857cac (before experiment 2
opened 2017-2021), with every open detail fixed here, BEFORE any run:
  B1 = experiment-2 pick's non-entry settings + H1 (close above the prior
       50-session closing high, volume >= 1.2x the 50-day average) + H2 (RS floor
       95, ranked by RS);
  B2 = B1 + H3 (a single Q2 or Q4 fundamentals failure is a rank penalty,
       ranked after every strict pass);
  B3 = B2 + H5 (early path: at RS >= 95, close above the 50/150/200-day lines
       stands in for the full trend template).
See backtest_results/experiment3/TESTS_NOW_PREREG.md.
"""
from __future__ import annotations

from kashif_engine import experiment2 as X2

PICK = {"rs_threshold": 90, "breakout_volume": 1.2, "stop_max_pct": 0.10, "max_positions": 4,
        "defensive_mode": "off", "regime_min_conditions": 1}          # = selection2.json pick (V1)
ARMS = {
    "B1": PICK | {"entry_mode": "high50", "rs_threshold": 95, "rank_by": "rs"},
    "B2": PICK | {"entry_mode": "high50", "rs_threshold": 95, "rank_by": "rs", "fund_mode": "soft_single"},
    "B3": PICK | {"entry_mode": "high50", "rs_threshold": 95, "rank_by": "rs", "fund_mode": "soft_single",
                  "early_path": True},
}
# References (in-sample window only; on 2017-2021 they were already run once by experiment 2).
REFS = {"EXP1_frozen": dict(X2.EXP1_FROZEN) | X2.VARIANTS["V0"], "EXP2_pick": dict(PICK)}
BASE = {"panel": "US_idx"}

INSAMPLE = ("2024-01-02", "2026-09-24")    # owner's request; the hypotheses were derived on 2022-2026
EXP3A = X2.VALIDATION                      # 2017-01-03 .. 2021-12-31: unseen by these hypotheses
