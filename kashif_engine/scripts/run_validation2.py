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
REMOTE = "https://github.com/ahmedmarzouk343/SEPA.git"
DEV_PROV = X.OUT / "dev_provenance.json"          # written when the dev grid is final
REHEARSAL = X.OUT / "REHEARSAL.json"
REHEARSAL_WINDOW = ("2024-01-02", "2024-06-28")   # inside the dev window
# Code that decides validation results. Between the dev grid's commit and the
# validation it must not change (review F6). Runner/report/test files are not
# on the trading path.
RESULT_PATHS = ["kashif_engine", "us_fundamentals/*.py", *RULE_FILES, *DATA_FILES,
                ":(exclude)kashif_engine/scripts/run_validation2.py",
                ":(exclude)kashif_engine/scripts/run_exp2_dev.py",
                ":(exclude)kashif_engine/scripts/report_exp2.py",
                ":(exclude)kashif_engine/tests"]


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def _git_remote(*args):
    """git against the GitHub remote with the gh CLI's token (no stored config)."""
    return _git("-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential", *args)


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
        shadow = line.startswith("??") and "/" not in path and path.endswith(".py")   # shadows a module on sys.path
        if line[:2].strip() and (code or data or rule or shadow):
            bad.append(path)
    hidden = [ln[2:] for ln in _git("ls-files", "-v").stdout.splitlines() if ln[:1] in ("h", "S")]
    return bad + [f"{h} (assume-unchanged/skip-worktree)" for h in hidden]


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
    # The claim commit must be able to happen (F3).
    for f in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"):
        if (ROOT / ".git" / f).exists():
            problems.append(f"git operation in progress (.git/{f})")
    if not _git("config", "user.email").stdout.strip():
        problems.append("no git user.email: the lock claim could not be committed")
    # The remote must not hold a claim from another clone (F4).
    fetch = _git_remote("fetch", "-q", REMOTE, "main")
    if fetch.returncode != 0:
        problems.append(f"cannot fetch the remote to check for another clone's claim: {fetch.stderr.strip()[:200]}")
    elif _git("log", "--oneline", "FETCH_HEAD", "--", LOCK_REL).stdout.strip():
        problems.append("the remote already holds a validation lock")
    # The dev grid must be complete, error-free, and tied to this bundle and code (F5, F6).
    grid = pd.read_csv(X.OUT / "dev_grid.csv")
    n_jobs = len(list(X.combos()))
    if len(grid) != n_jobs or grid["error"].notna().any():
        problems.append(f"dev grid has {len(grid)}/{n_jobs} rows and {int(grid['error'].notna().sum())} errors")
    if not DEV_PROV.exists():
        problems.append("dev_provenance.json missing")
    else:
        dp = json.loads(DEV_PROV.read_text())
        if dp.get("bundle_sha256") != sha_file(ROOT / "kashif_data" / "signals" / "bundle_exp2_dev.pkl"):
            problems.append("the dev bundle file changed since the dev grid ran")
        if _git("diff", "--quiet", dp["grid_code_commit"], "HEAD", "--", *RESULT_PATHS).returncode != 0:
            problems.append(f"result-deciding code changed since the dev grid's commit {dp['grid_code_commit'][:8]}")
    # The exact validation code path must have run once, on dev data, at this commit (F2).
    head = _git("rev-parse", "HEAD").stdout.strip()
    if not REHEARSAL.exists():
        problems.append("no rehearsal: run `run_validation2.py --rehearse` first")
    else:
        rh = json.loads(REHEARSAL.read_text())
        if rh.get("git_commit") != head or rh.get("content") != fingerprint.content() or not rh.get("ok"):
            problems.append("rehearsal record is stale or failed")
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
    c = _git("-c", "commit.gpgsign=false", "commit", "--no-verify", "-m",
             "Experiment 2 validation window claimed (run_validation2.py)", "--", LOCK_REL)
    if c.returncode != 0:                          # nothing has run: undo the claim and stop
        _git("reset", "-q", "--", LOCK_REL)
        X.LOCK.unlink()
        sys.exit(f"REFUSED: could not commit the lock claim (nothing ran; claim undone): {c.stderr.strip()}")
    push = _git_remote("push", "-q", REMOTE, "HEAD:main")
    if push.returncode != 0:                       # another clone must see the claim before anything runs
        _git("reset", "-q", "--soft", "HEAD~1")
        _git("reset", "-q", "--", LOCK_REL)
        X.LOCK.unlink()
        sys.exit(f"REFUSED: could not push the lock claim (nothing ran; claim undone): {push.stderr.strip()[:300]}")
    return nonce


def run_arms(arms: dict, start, end, token, out_root: Path) -> dict:
    """The arm code the validation runs -- shared with --rehearse so the one-shot
    path has run once, on development data, before the window is claimed."""
    results = {}
    for name, params in arms.items():
        out_dir = out_root / name
        out = run_one(start, end, params, run_id=name, tickers=X.index_universe(),
                      allow_validation2=token, out_dir=out_dir)
        eq = pd.read_csv(out_dir / "equity.csv", index_col=0, parse_dates=True)["equity"]
        out["verdict"] = verdict(out["metrics"], eq, out.get("audit_passed"))
        ks = json.loads((out_dir / "run.json").read_text()).get("kill_switch", {})
        if ks.get("halted_days") or ks.get("tripped_reason"):
            out["verdict"] = {"verdict": "INVALID", "reason": f"kill switch halted the run: {ks}"}
        results[name] = out
    # Amendment 2: the changes get credit only if A beats B significantly.
    ea, eb = (pd.read_csv(out_root / n / "equity.csv", index_col=0, parse_dates=True)["equity"]
              for n in ("VAL2_A_pick", "VAL2_B_exp1_frozen"))
    diff = (ea.pct_change() - eb.pct_change()).dropna().to_numpy()
    ab = {"bootstrap_p": stationary_bootstrap_p(diff),
          "cagr_diff": results["VAL2_A_pick"]["metrics"]["strategy"]["cagr"]
          - results["VAL2_B_exp1_frozen"]["metrics"]["strategy"]["cagr"]}
    ab["changes_get_credit"] = bool(ab["bootstrap_p"] < 0.10 and ab["cagr_diff"] > 0)
    results["A_minus_B"] = ab
    return results


def _arms(sel):
    return {"VAL2_A_pick": sel["pick"] | X.BASE_PARAMS,
            "VAL2_B_exp1_frozen": dict(X.EXP1_FROZEN) | X.VARIANTS["V0"] | X.BASE_PARAMS}


def rehearse():
    """Run the exact arm code on a slice of the DEVELOPMENT window, no lock."""
    from kashif_engine import panel as PANEL
    from kashif_engine.data import fingerprint
    sel = json.loads((X.OUT / "selection2.json").read_text())
    PANEL.build(X.index_universe(), "US", name="US_idx", log=lambda *a: None)
    rec = {"window": list(REHEARSAL_WINDOW), "git_commit": _git("rev-parse", "HEAD").stdout.strip(),
           "content": fingerprint.content(), "started_utc": datetime.now(timezone.utc).isoformat()}
    try:
        res = run_arms(_arms(sel), *REHEARSAL_WINDOW, None, ROOT / "kashif_data" / "rehearsal")
        rec |= {"ok": all(v["verdict"]["verdict"] != "INVALID" for k, v in res.items() if k != "A_minus_B"),
                "summary": {k: (v["verdict"] if k != "A_minus_B" else v) for k, v in res.items()}}
    except BaseException as e:  # noqa: BLE001 -- a rehearsal failure is exactly what it is for
        rec |= {"ok": False, "error": repr(e), "traceback": traceback.format_exc()}
    REHEARSAL.write_text(json.dumps(rec, indent=2, default=str))
    print(json.dumps({k: v for k, v in rec.items() if k != "content"}, indent=2, default=str)[:3000])


def _record(lock, msg):
    X.LOCK.write_text(json.dumps(lock, indent=2, default=str))
    _git("add", "-f", LOCK_REL)
    _git("-c", "commit.gpgsign=false", "commit", "--no-verify", "-m", msg, "--", LOCK_REL)
    _git_remote("push", "-q", REMOTE, "HEAD:main")


def main():
    problems, sel = preflight()
    if problems:
        sys.exit("REFUSED:" + "".join("\n  " + x for x in problems))
    if not sel.get("pick"):
        sys.exit("no pick in selection2.json -- nothing met the constraints; report that instead")
    # Everything that is not a window result happens BEFORE the claim (review F1):
    # the panel rebuild (features only, as build_exp2_bundle does) and the hashes.
    from kashif_engine import panel as PANEL
    from kashif_engine.data import fingerprint
    PANEL.build(X.index_universe(), "US", name="US_idx", log=lambda *a: None)
    arms = _arms(sel)
    frozen = {"selection2.json": sha_file(X.OUT / "selection2.json"), "PREREGISTRATION.md": sha_file(X.PREREG),
              "dev_grid.csv": sha_file(X.OUT / "dev_grid.csv"),
              "dev_provenance.json": json.loads(DEV_PROV.read_text()),
              "strategy_config.json": sha_file(ROOT / "minervini_sepa_v1_strategy_config.json"),
              "data": fingerprint.content(),
              "panel_US_idx": sha_tree(ROOT / "kashif_data" / "panels" / "US_idx", "*.parquet"),
              "history_breaks.csv": sha_file(ROOT / "kashif_engine" / "data" / "history_breaks.csv"),
              "rehearsal": json.loads(REHEARSAL.read_text())["summary"],
              "git_status_porcelain": _git("status", "--porcelain").stdout,
              "git_commit": _git("rev-parse", "HEAD").stdout.strip()}
    nonce = claim_lock()
    lock = json.loads(X.LOCK.read_text())
    results = {}
    try:        # BaseException: Ctrl-C or SystemExit must also be recorded (review F7)
        lock |= {"started_utc": datetime.now(timezone.utc).isoformat(), "arms": arms, "frozen_inputs": frozen}
        X.LOCK.write_text(json.dumps(lock, indent=2, default=str))
        results = run_arms(arms, X.VALIDATION[0], X.VALIDATION[1], nonce, ROOT / "kashif_data" / "runs")
    except BaseException as e:  # noqa: BLE001 -- recorded; a failed run is reported, never retried
        lock |= {"failed_utc": datetime.now(timezone.utc).isoformat(), "error": repr(e),
                 "traceback": traceback.format_exc(), "completed_arms": list(results)}
        _record(lock, "Experiment 2 validation FAILED (lock records the error)")
        raise
    lock |= {"finished_utc": datetime.now(timezone.utc).isoformat(),
             "verdicts": {k: v["verdict"] for k, v in results.items() if k != "A_minus_B"},
             "A_minus_B": results["A_minus_B"],
             "audit_passed": {k: v.get("audit_passed") for k, v in results.items() if k != "A_minus_B"}}
    (X.OUT / "validation2_results.json").write_text(json.dumps(results, indent=2, default=str))
    _git("add", "-f", "kashif_data/experiment2/validation2_results.json")
    _git("-c", "commit.gpgsign=false", "commit", "--no-verify", "-q", "-m",
         "Experiment 2 validation results", "--", "kashif_data/experiment2/validation2_results.json")
    _record(lock, "Experiment 2 validation finished: lock")
    print(json.dumps({k: ({"verdict": v["verdict"], "strategy": v["metrics"]["strategy"]} if k != "A_minus_B" else v)
                      for k, v in results.items()}, indent=2, default=str))


if __name__ == "__main__":
    rehearse() if "--rehearse" in sys.argv else main()
