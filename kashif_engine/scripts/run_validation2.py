"""Experiment 2: the ONE validation run on 2017-01-03 .. 2021-12-31.

Written and committed BEFORE the first development run (PREREGISTRATION.md,
amendment 1). Reads the pick from kashif_data/experiment2/selection2.json,
runs arm A (the pick) and arm B (experiment-1 frozen params, v1 behaviour),
writes the verdict with the pre-declared rule, and locks itself: every later
invocation refuses to run.

    python kashif_engine/scripts/run_validation2.py
"""
import hashlib
import json
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kashif_engine import experiment2 as X  # noqa: E402
from kashif_engine import reports  # noqa: E402
from kashif_engine.run_backtest import run_one  # noqa: E402


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def sha_tree(root, pattern):
    h = hashlib.sha256()
    for p in sorted(Path(root).rglob(pattern)):
        h.update(str(p.relative_to(root)).encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def stationary_bootstrap_p(excess: np.ndarray, block=20, n=10_000, seed=7) -> float:
    """One-sided p-value for mean(excess) > 0: Politis-Romano stationary bootstrap
    of the null-centred series (vectorised per resample)."""
    rng = np.random.default_rng(seed)
    x = np.asarray(excess, dtype=float)
    obs, x0, T = x.mean(), x - x.mean(), len(x)
    t = np.arange(T)
    count = 0
    for _ in range(n):
        jumps = rng.random(T) < 1.0 / block
        jumps[0] = True
        group = np.cumsum(jumps) - 1
        starts = rng.integers(T, size=int(jumps.sum()))
        first = np.flatnonzero(jumps)
        idx = (starts[group] + (t - first[group])) % T
        count += x0[idx].mean() >= obs
    return (count + 1) / (n + 1)


def verdict(metrics: dict, eq: pd.Series) -> dict:
    s = metrics["strategy"]
    blend, ew = metrics["MDY_IJR_5050"], metrics["EW_sp400_sp600_monthly"]
    beats = all(s[k] > b[k] for b in (blend, ew) for k in ("cagr", "sharpe"))
    ew_curve = reports.ew_index_members(eq.index[0], eq.index[-1]).reindex(eq.index).ffill()
    excess = (eq.pct_change() - ew_curve.pct_change()).dropna().to_numpy()
    p = stationary_bootstrap_p(excess)
    if beats and p < 0.10:
        v = "PASS"
    elif s["cagr"] < blend["cagr"]:
        v = "FAIL"
    else:
        v = "INCONCLUSIVE"
    return {"verdict": v, "beats_blend_and_ew_on_cagr_and_sharpe": beats, "bootstrap_p_vs_ew": p}


def main():
    if X.LOCK.exists():
        sys.exit(f"REFUSED: experiment-2 validation already run ({X.LOCK.read_text()[:300]})")
    sel_p = X.OUT / "selection2.json"
    sel = json.loads(sel_p.read_text())
    if not sel.get("pick"):
        sys.exit("no pick in selection2.json -- nothing met the constraints; report that instead")
    arms = {"VAL2_A_pick": sel["pick"] | X.BASE_PARAMS,
            "VAL2_B_exp1_frozen": dict(X.EXP1_FROZEN) | X.VARIANTS["V0"] | X.BASE_PARAMS}
    frozen = {"selection2.json": sha_file(sel_p), "PREREGISTRATION.md": sha_file(X.PREREG),
              "strategy_config.json": sha_file(ROOT / "minervini_sepa_v1_strategy_config.json"),
              "price_cache": sha_tree(ROOT / "kashif_data" / "prices" / "US", "*.parquet"),
              "fundamentals_store": sha_tree(ROOT / "us_fundamentals" / "scaled_fundamentals_parquet", "*.parquet"),
              "git_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                           text=True).stdout.strip()}
    X.OUT.mkdir(parents=True, exist_ok=True)
    lock = {"started_utc": datetime.now(timezone.utc).isoformat(), "arms": arms, "frozen_inputs": frozen}
    X.LOCK.write_text(json.dumps(lock, indent=2, default=str))
    results = {}
    try:
        for name, params in arms.items():
            out = run_one(X.VALIDATION[0], X.VALIDATION[1], params, run_id=name, tickers=X.index_universe(),
                          allow_validation2=True, out_dir=ROOT / "kashif_data" / "runs" / name)
            eq = pd.read_csv(ROOT / "kashif_data" / "runs" / name / "equity.csv", index_col=0,
                             parse_dates=True)["equity"]
            out["verdict"] = verdict(out["metrics"], eq)
            results[name] = out
    except Exception as e:  # noqa: BLE001 -- recorded; a failed run is reported, not silently retried
        lock |= {"failed_utc": datetime.now(timezone.utc).isoformat(), "error": repr(e),
                 "traceback": traceback.format_exc(), "completed_arms": list(results)}
        X.LOCK.write_text(json.dumps(lock, indent=2, default=str))
        raise
    lock |= {"finished_utc": datetime.now(timezone.utc).isoformat(),
             "verdicts": {k: v["verdict"] for k, v in results.items()},
             "audit_passed": {k: v.get("audit_passed") for k, v in results.items()}}
    X.LOCK.write_text(json.dumps(lock, indent=2, default=str))
    (X.OUT / "validation2_results.json").write_text(json.dumps(results, indent=2, default=str))
    print(json.dumps({k: {"verdict": v["verdict"], "strategy": v["metrics"]["strategy"]} for k, v in results.items()},
                     indent=2, default=str))


if __name__ == "__main__":
    main()
