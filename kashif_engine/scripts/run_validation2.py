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


def verdict(metrics: dict, eq: pd.Series, audit_passed) -> dict:
    if audit_passed is not True:
        return {"verdict": "INVALID", "reason": "independent auditor did not match the ledger"}
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


RULE_FILES = ("market_regime_gate.py", "trend_template_test.py", "entry_timing.py", "vcp_detection.py",
              "fundamentals_screen.py", "minervini_sepa_v1_strategy_config.json", "kashif_config.py")
# Tracked non-code files that change decisions (review M11).
DATA_FILES = ("us_fundamentals/sp_universe.json", "us_fundamentals/scaled_fundamentals.csv",
              "kashif_engine/data/history_breaks.csv")
LOCK_REL = "kashif_data/experiment2/VALIDATION_LOCK"


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def dirty_code() -> list:
    """Files whose uncommitted state would make the lock's commit unable to rebuild
    every input: code under kashif_engine/ and us_fundamentals/ (untracked .py
    too: committed code could import it), the root rule files, the universe,
    the store and the history breaks."""
    st = _git("status", "--porcelain", "--untracked-files=all").stdout
    bad = []
    for line in st.splitlines():
        path = line[3:].strip().strip('"').split(" -> ")[-1]
        code = path.startswith(("kashif_engine/", "us_fundamentals/")) and path.endswith(".py")
        data = path in DATA_FILES or path.startswith("us_fundamentals/scaled_fundamentals_parquet/")
        rule = path in RULE_FILES and not line.startswith("??")
        if line[:2].strip() and (code or data or rule):
            bad.append(path)
    return bad


def preflight() -> tuple:
    """Every refusal, before anything is claimed or written. Returns (problems, sel)."""
    import os
    from kashif_engine.data import fingerprint
    problems = []
    if X.LOCK.exists():
        problems.append(f"lock exists: {X.LOCK.read_text()[:200]}")
    if _git("log", "--all", "--oneline", "--", LOCK_REL).stdout.strip():
        problems.append("git history already holds a validation lock: the window was claimed before")
    if list((ROOT / "kashif_data" / "runs").glob("VAL2_*")):
        problems.append("kashif_data/runs/VAL2_* exist: a validation arm already ran")
    dirty = dirty_code()
    if dirty:
        problems.append(f"uncommitted decision-changing files: {dirty}")
    # A stale kill switch or KASHIF_* flag would void or change the one run (M12).
    if (ROOT / "kashif_data" / "KILL_SWITCH").exists():
        problems.append("kashif_data/KILL_SWITCH exists")
    flags = sorted(k for k in os.environ if k.startswith("KASHIF_"))
    if flags:
        problems.append(f"KASHIF_* environment flags set: {flags}")
    import kashif_config
    if getattr(kashif_config, "KILL_SWITCH", False):
        problems.append("kashif_config.KILL_SWITCH is on")
    problems += [f"store: {p}" for p in fingerprint.store_integrity()]        # M4
    # The pick must be what the pre-registered rule selects from the dev grid (M10).
    sel = json.loads((X.OUT / "selection2.json").read_text())
    from kashif_engine.scripts.run_exp2_dev import select
    scored = select(pd.read_csv(X.OUT / "dev_grid.csv"))
    if scored:
        r = scored[0][2]
        expect = {k: r[k] for k in X.GRID} | X.VARIANTS[r["variant"]]
        if sel.get("pick") != expect:
            problems.append(f"selection2.json pick {sel.get('pick')} != re-derived {expect}")
    elif sel.get("pick"):
        problems.append("selection2.json has a pick but the dev grid meets no constraint")
    # The validation must run on the data the development bundle was built on (M3).
    import pickle
    with open(ROOT / "kashif_data" / "signals" / "bundle_exp2_dev.pkl", "rb") as f:
        prov = pickle.load(f).get("provenance", {})
    now = fingerprint.content()
    diff = [k for k, v in now.items() if prov.get("content", {}).get(k) != v]
    if diff:
        problems.append(f"data differ from the dev bundle's: {diff}")
    return problems, sel


def claim_lock() -> str:
    """Atomically create the lock and commit it at once: a deleted file, a fresh
    clone or a second launch can no longer re-open the window (M9)."""
    import os
    import secrets
    X.OUT.mkdir(parents=True, exist_ok=True)
    nonce = secrets.token_hex(16)
    fd = os.open(X.LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)       # fails if a racer got here first
    with os.fdopen(fd, "w") as f:
        json.dump({"claimed_utc": datetime.now(timezone.utc).isoformat(), "nonce": nonce}, f)
    _git("add", "-f", LOCK_REL)
    c = _git("commit", "-m", "Experiment 2 validation window claimed (run_validation2.py)", "--", LOCK_REL)
    if c.returncode != 0:
        raise RuntimeError(f"could not commit the lock claim: {c.stderr}")
    return nonce


def main():
    problems, sel = preflight()
    if problems:
        sys.exit("REFUSED:\n  " + "\n  ".join(problems))
    if not sel.get("pick"):
        sys.exit("no pick in selection2.json -- nothing met the constraints; report that instead")
    nonce = claim_lock()
    # Rebuild the panel from the current price cache right here, so the run can never
    # trade on a panel older than the prices the lock hashes (review finding [2]).
    from kashif_engine import panel as PANEL
    PANEL.build(X.index_universe(), "US", name="US_idx", log=lambda *a: None)
    sel_p = X.OUT / "selection2.json"
    arms = {"VAL2_A_pick": sel["pick"] | X.BASE_PARAMS,
            "VAL2_B_exp1_frozen": dict(X.EXP1_FROZEN) | X.VARIANTS["V0"] | X.BASE_PARAMS}
    frozen = {"selection2.json": sha_file(sel_p), "PREREGISTRATION.md": sha_file(X.PREREG),
              "strategy_config.json": sha_file(ROOT / "minervini_sepa_v1_strategy_config.json"),
              "price_cache": sha_tree(ROOT / "kashif_data" / "prices" / "US", "*.parquet"),
              "fundamentals_store": sha_tree(ROOT / "us_fundamentals" / "scaled_fundamentals_parquet", "*.parquet"),
              "panel_US_idx": sha_tree(ROOT / "kashif_data" / "panels" / "US_idx", "*.parquet"),
              "history_breaks.csv": sha_file(ROOT / "kashif_engine" / "data" / "history_breaks.csv"),
              "git_status_porcelain": subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                                     capture_output=True, text=True).stdout,
              "git_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                           text=True).stdout.strip()}
    X.OUT.mkdir(parents=True, exist_ok=True)
    lock = json.loads(X.LOCK.read_text()) | {"started_utc": datetime.now(timezone.utc).isoformat(),
                                              "arms": arms, "frozen_inputs": frozen}
    X.LOCK.write_text(json.dumps(lock, indent=2, default=str))
    results = {}
    try:
        for name, params in arms.items():
            out = run_one(X.VALIDATION[0], X.VALIDATION[1], params, run_id=name, tickers=X.index_universe(),
                          allow_validation2=nonce, out_dir=ROOT / "kashif_data" / "runs" / name)
            eq = pd.read_csv(ROOT / "kashif_data" / "runs" / name / "equity.csv", index_col=0,
                             parse_dates=True)["equity"]
            out["verdict"] = verdict(out["metrics"], eq, out.get("audit_passed"))
            ks = json.loads((ROOT / "kashif_data" / "runs" / name / "run.json").read_text()).get("kill_switch", {})
            if ks.get("halted_days") or ks.get("tripped_reason"):
                out["verdict"] = {"verdict": "INVALID", "reason": f"kill switch halted the run: {ks}"}
            results[name] = out
        # Amendment 2: the changes get credit only if A beats B significantly.
        ea = pd.read_csv(ROOT / "kashif_data" / "runs" / "VAL2_A_pick" / "equity.csv", index_col=0, parse_dates=True)["equity"]
        eb = pd.read_csv(ROOT / "kashif_data" / "runs" / "VAL2_B_exp1_frozen" / "equity.csv", index_col=0, parse_dates=True)["equity"]
        diff = (ea.pct_change() - eb.pct_change()).dropna().to_numpy()
        results["A_minus_B"] = {"bootstrap_p": stationary_bootstrap_p(diff),
                                "cagr_diff": results["VAL2_A_pick"]["metrics"]["strategy"]["cagr"]
                                - results["VAL2_B_exp1_frozen"]["metrics"]["strategy"]["cagr"]}
        results["A_minus_B"]["changes_get_credit"] = bool(results["A_minus_B"]["bootstrap_p"] < 0.10
                                                          and results["A_minus_B"]["cagr_diff"] > 0)
    except Exception as e:  # noqa: BLE001 -- recorded; a failed run is reported, not silently retried
        lock |= {"failed_utc": datetime.now(timezone.utc).isoformat(), "error": repr(e),
                 "traceback": traceback.format_exc(), "completed_arms": list(results)}
        X.LOCK.write_text(json.dumps(lock, indent=2, default=str))
        _git("add", "-f", LOCK_REL)
        _git("commit", "-m", "Experiment 2 validation FAILED (lock records the error)", "--", LOCK_REL)
        raise
    lock |= {"finished_utc": datetime.now(timezone.utc).isoformat(),
             "verdicts": {k: v["verdict"] for k, v in results.items() if k != "A_minus_B"},
             "A_minus_B": results["A_minus_B"],
             "audit_passed": {k: v.get("audit_passed") for k, v in results.items() if k != "A_minus_B"}}
    X.LOCK.write_text(json.dumps(lock, indent=2, default=str))
    (X.OUT / "validation2_results.json").write_text(json.dumps(results, indent=2, default=str))
    res_rel = "kashif_data/experiment2/validation2_results.json"
    _git("add", "-f", LOCK_REL, res_rel)
    _git("commit", "-m", "Experiment 2 validation finished: lock and results", "--", LOCK_REL, res_rel)
    print(json.dumps({k: ({"verdict": v["verdict"], "strategy": v["metrics"]["strategy"]} if k != "A_minus_B" else v)
                      for k, v in results.items()}, indent=2, default=str))


if __name__ == "__main__":
    main()
