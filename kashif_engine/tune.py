"""Phase 4: honest tuning inside the defined strategy.

Declared BEFORE any tuning result was seen (and not changed afterwards):
  * tuning window 2022-01-03 .. 2024-06-28; holdout 2024-07-01 .. 2026-09-24,
    run ONCE, after the final parameters are frozen (see holdout.py);
  * grid = the existing config parameters the brief allows, over book-grounded
    ranges -- RS percentile {70, 80, 90}, breakout volume {1.2, 1.4, 1.6},
    max stop {6%, 8%, 10%}, max positions {4, 6, 8, 12}: 108 combinations;
  * objective = daily Sharpe (rf = 0) with hard constraints >= 30 closed trades
    and max drawdown <= 25% (graduation_criteria); a combination that fails a
    constraint scores -inf;
  * stability: the final pick maximises the MEDIAN objective over the
    combination and its grid neighbours (one step in one parameter), so a
    lone spike cannot win;
  * walk-forward: anchored folds inside the tuning window, 6-month tests,
    the same selection rule on each train window (trade floor scaled to
    the window length).
Every combination run is appended to kashif_data/tuning/trials.csv.
"""
from __future__ import annotations

import itertools
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TUNE = ("2022-01-03", "2024-06-28")
HOLDOUT = ("2024-07-01", "2026-09-24")
GRID = {"rs_threshold": [70, 80, 90], "breakout_volume": [1.2, 1.4, 1.6],
        "stop_max_pct": [0.06, 0.08, 0.10], "max_positions": [4, 6, 8, 12]}
FOLDS = [(("2022-01-03", "2022-12-30"), ("2023-01-03", "2023-06-30")),
         (("2022-01-03", "2023-06-30"), ("2023-07-03", "2023-12-29")),
         (("2022-01-03", "2023-12-29"), ("2024-01-02", "2024-06-28"))]
MIN_TRADES_FULL = 30
MAX_DD = 0.25
OUT = ROOT / "kashif_data" / "tuning"


def combos():
    keys = list(GRID)
    return [dict(zip(keys, v)) for v in itertools.product(*GRID.values())]


def _run(args):
    start, end, params, bundle, tag = args
    from kashif_engine.run_backtest import run_one
    rid = f"{tag}_" + "_".join(f"{k[:3]}{v}" for k, v in params.items())
    try:
        out = run_one(start, end, params, run_id=rid, bundle=bundle, benchmarks=False,
                      log=lambda *a: None, out_dir=OUT / "runs" / rid)
        m = out["metrics"]["strategy"]
        return {"tag": tag, "start": start, "end": end, **params, "trades": m.get("trades", 0),
                "sharpe": m["sharpe"], "cagr": m["cagr"], "max_dd": m["max_drawdown"],
                "total_return": m["total_return"], "win_rate": m.get("win_rate"),
                "wl_ratio": m.get("win_loss_ratio"), "exposure": m["exposure"],
                "audit_passed": out.get("audit_passed"), "run_id": rid, "error": None}
    except Exception as e:  # noqa: BLE001 -- recorded, and the run counts as failed
        return {"tag": tag, "start": start, "end": end, **params, "error": f"{type(e).__name__}: {e}",
                "run_id": rid}


def run_batch(jobs, workers=6, log=print):
    OUT.mkdir(parents=True, exist_ok=True)
    rows, t0 = [], time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for i, r in enumerate(ex.map(_run, jobs)):
            rows.append(r)
            if (i + 1) % 10 == 0:
                log(f"  {i + 1}/{len(jobs)} runs, {time.time() - t0:.0f}s")
    df = pd.DataFrame(rows)
    trials = OUT / "trials.csv"
    df.to_csv(trials, mode="a", header=not trials.exists(), index=False)
    return df


def objective(row, min_trades):
    err = row.get("error")
    if (isinstance(err, str) and err) or row.get("audit_passed") is not True:
        return -math.inf
    if row["trades"] < min_trades or row["max_dd"] < -MAX_DD or not np.isfinite(row["sharpe"]):
        return -math.inf
    return row["sharpe"]


def neighbours(p):
    out = []
    for k, vals in GRID.items():
        i = vals.index(p[k])
        for j in (i - 1, i + 1):
            if 0 <= j < len(vals):
                out.append({**p, k: vals[j]})
    return out


def select(df, min_trades):
    """Most stable good region: median objective over the combo and its neighbours."""
    key = lambda p: tuple(p[k] for k in GRID)  # noqa: E731
    obj = {key(r): objective(r, min_trades) for r in df.to_dict("records")}
    scored = []
    for r in df.to_dict("records"):
        p = {k: r[k] for k in GRID}
        if obj[key(p)] == -math.inf:
            continue
        vals = [obj[key(p)]] + [obj.get(key(n), -math.inf) for n in neighbours(p)]
        # Failing neighbours stay -inf so they pull the median DOWN; ignoring them
        # (nanmedian) let a lone spike with dead neighbours score its own value.
        scored.append((float(np.median(vals)), obj[key(p)], p))
    if not scored:
        return None, []
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return scored[0][2], scored
