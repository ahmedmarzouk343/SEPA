"""Experiment 2 constants and guards (see backtest_results/experiment2/PREREGISTRATION.md)."""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEV = ("2022-01-03", "2026-09-24")
DEV_HALVES = (("2022-01-03", "2024-06-28"), ("2024-07-01", "2026-09-24"))
VALIDATION = ("2017-01-03", "2021-12-31")
OUT = ROOT / "kashif_data" / "experiment2"
LOCK = OUT / "VALIDATION_LOCK"
PREREG = ROOT / "backtest_results" / "experiment2" / "PREREGISTRATION.md"

VARIANTS = {
    "V0": {"defensive_mode": "full", "regime_min_conditions": 1},
    "V1": {"defensive_mode": "off", "regime_min_conditions": 1},
    "V2": {"defensive_mode": "size_only", "regime_min_conditions": 1},
    "V3": {"defensive_mode": "full", "regime_min_conditions": 2},
    "V4": {"defensive_mode": "off", "regime_min_conditions": 2},
}
GRID = {"rs_threshold": [70, 80, 90], "breakout_volume": [1.2, 1.4, 1.6],
        "stop_max_pct": [0.06, 0.08, 0.10], "max_positions": [4, 6, 8, 12]}
MIN_TRADES = 60
MAX_DD = 0.25
EXP1_FROZEN = {"rs_threshold": 70, "breakout_volume": 1.6, "stop_max_pct": 0.10, "max_positions": 6}


def combos():
    keys = list(GRID)
    for vid, vp in VARIANTS.items():
        for vals in itertools.product(*GRID.values()):
            yield vid, dict(zip(keys, vals)) | vp


def overlaps_validation(start, end) -> bool:
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    return not (e < pd.Timestamp(VALIDATION[0]) or s > pd.Timestamp(VALIDATION[1]))


def validation_finished() -> bool:
    return LOCK.exists() and "finished_utc" in json.loads(LOCK.read_text())


def index_universe():
    """Amendment 1: current S&P 400 + S&P 600 members with a price series."""
    from kashif_engine.data import prices as P
    u = json.load(open(ROOT / "us_fundamentals" / "sp_universe.json"))
    cached = set(P.cached_tickers("US"))
    return sorted((set(u["sp400"]) | set(u["sp600"])) & cached)


BASE_PARAMS = {"panel": "US_idx"}
