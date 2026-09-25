"""Experiment 2 development runs and the pre-registered selection.

540 backtests (5 variants x 108 combos) on 2022-01-03 .. 2026-09-24 over the
S&P 400+600 member universe, then the selection rule of PREREGISTRATION.md:
neighbour-median Sharpe within each variant (failing neighbours = -inf),
>= 60 trades, maxDD <= 25%, auditor passed, positive total return in both
halves. Writes kashif_data/experiment2/{dev_grid.csv, selection2.json}.
"""
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kashif_engine import experiment2 as X  # noqa: E402

BUNDLE = str(ROOT / "kashif_data" / "signals" / "bundle_exp2_dev.pkl")


def _run(args):
    vid, params = args
    from kashif_engine.run_backtest import run_one
    rid = f"x2_{vid}_" + "_".join(f"{k[:3]}{params[k]}" for k in X.GRID)
    out_dir = X.OUT / "runs" / rid
    try:
        out = run_one(X.DEV[0], X.DEV[1], params | X.BASE_PARAMS, run_id=rid, bundle=BUNDLE, benchmarks=False,
                      log=lambda *a: None, out_dir=out_dir)
        m = out["metrics"]["strategy"]
        eq = pd.read_csv(out_dir / "equity.csv", index_col=0, parse_dates=True)["equity"]
        halves = [float(eq.loc[a:b].iloc[-1] / eq.loc[a:b].iloc[0] - 1) for a, b in X.DEV_HALVES]
        return {"variant": vid, **{k: params[k] for k in X.GRID}, "trades": m.get("trades", 0),
                "sharpe": m["sharpe"], "cagr": m["cagr"], "max_dd": m["max_drawdown"],
                "total_return": m["total_return"], "win_rate": m.get("win_rate"),
                "wl_ratio": m.get("win_loss_ratio"), "exposure": m["exposure"],
                "half1_return": halves[0], "half2_return": halves[1],
                "audit_passed": out.get("audit_passed"), "run_id": rid, "error": None}
    except Exception as e:  # noqa: BLE001
        return {"variant": vid, **{k: params[k] for k in X.GRID}, "error": f"{type(e).__name__}: {e}", "run_id": rid}


def objective(r):
    if (isinstance(r.get("error"), str) and r["error"]) or r.get("audit_passed") is not True:
        return -math.inf
    if r["trades"] < X.MIN_TRADES or r["max_dd"] < -X.MAX_DD or not np.isfinite(r["sharpe"]):
        return -math.inf
    if not (r["half1_return"] > 0 and r["half2_return"] > 0):
        return -math.inf
    return r["sharpe"]


def select(df):
    key = lambda r: (r["variant"],) + tuple(r[k] for k in X.GRID)  # noqa: E731
    recs = df.to_dict("records")
    obj = {key(r): objective(r) for r in recs}
    scored = []
    for r in recs:
        if obj[key(r)] == -math.inf:
            continue
        vals = [obj[key(r)]]
        for k, grid in X.GRID.items():
            i = grid.index(r[k])
            for j in (i - 1, i + 1):
                if 0 <= j < len(grid):
                    vals.append(obj.get(key(r | {k: grid[j]}), -math.inf))
        scored.append((float(np.median(vals)), obj[key(r)], r))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return scored


def deflated_sharpe(sr_annual, n_trials, T_days, skew=0.0, kurt=3.0):
    """Bailey & Lopez de Prado DSR on daily returns (annual Sharpe converted)."""
    from scipy.stats import norm
    sr = sr_annual / math.sqrt(252)
    var_sr = 1.0 / (T_days - 1)          # iid approximation of the trial-SR variance
    e_max = math.sqrt(var_sr) * ((1 - 0.5772) * norm.ppf(1 - 1 / n_trials) + 0.5772 * norm.ppf(1 - 1 / (n_trials * math.e)))
    denom = math.sqrt((1 - skew * sr + (kurt - 1) / 4 * sr ** 2) / (T_days - 1))
    return float(norm.cdf((sr - e_max) / denom))


def main(workers=6):
    X.OUT.mkdir(parents=True, exist_ok=True)
    jobs = list(X.combos())
    t0, rows = time.time(), []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for i, r in enumerate(ex.map(_run, jobs)):
            rows.append(r)
            if (i + 1) % 30 == 0:
                print(f"  {i + 1}/{len(jobs)} runs, {time.time() - t0:.0f}s", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(X.OUT / "dev_grid.csv", index=False)
    scored = select(df)
    pick = None
    if scored:
        med, own, r = scored[0]
        pick = {k: r[k] for k in X.GRID} | X.VARIANTS[r["variant"]]
        eq = pd.read_csv(X.OUT / "runs" / r["run_id"] / "equity.csv", index_col=0, parse_dates=True)["equity"]
        ret = eq.pct_change().dropna()
        dsr = {n: deflated_sharpe(own, n, len(ret), float(ret.skew()), float(ret.kurt() + 3)) for n in (540, 50)}
    sel = {"pick": pick, "pick_variant": scored[0][2]["variant"] if scored else None,
           "pick_dev_sharpe": scored[0][1] if scored else None,
           "pick_neighbour_median": scored[0][0] if scored else None,
           "deflated_sharpe_ratio": dsr if scored else None,
           "n_runs": len(df), "n_meeting_constraints": len(scored), "errors": int(df["error"].notna().sum()),
           "top10": [{"median": m, "own": o, **{k: r[k] for k in ["variant", *X.GRID, "trades", "cagr", "max_dd",
                                                                   "half1_return", "half2_return"]}}
                     for m, o, r in scored[:10]]}
    (X.OUT / "selection2.json").write_text(json.dumps(sel, indent=2, default=str))
    print(json.dumps(sel, indent=2, default=str))


if __name__ == "__main__":
    main()
