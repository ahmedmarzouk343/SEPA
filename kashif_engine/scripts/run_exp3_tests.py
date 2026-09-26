"""Experiment 3 historical tests of the frozen arms B1-B3 (kashif_engine/experiment3.py).

    python kashif_engine/scripts/run_exp3_tests.py insample   # 2024-01-02..2026-09-24, owner's request
    python kashif_engine/scripts/run_exp3_tests.py exp3a      # 2017-01-03..2021-12-31, ONCE, under a lock

Both run on real historical bars with the engine's costs and the independent
auditor. "insample" is labelled in-sample: the hypotheses were derived from
2022-2026. "exp3a" is the kill screen of backtest_results/experiment3/
TESTS_NOW_PREREG.md: an arm is KILLED if its swept CAGR (idle cash held in the
equal-weight member basket) does not beat that basket's CAGR.

Swept return: r_swept(t) = r_arm(t) + cash_weight(t-1) * r_benchmark(t) -- the
arm's daily return with its idle cash (which earns nothing in the engine)
held in the benchmark instead.
"""
import json
import math
import os
import secrets
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kashif_engine import experiment2 as X2  # noqa: E402
from kashif_engine import experiment3 as X3  # noqa: E402
from kashif_engine import reports  # noqa: E402
from kashif_engine.run_backtest import run_one  # noqa: E402

OUT = ROOT / "kashif_data" / "experiment3"
RES = ROOT / "backtest_results" / "experiment3"
LOCK_REL = "kashif_data/experiment3/EXP3A_LOCK"
REMOTE = "https://github.com/ahmedmarzouk343/SEPA.git"


def _git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)


def _git_remote(*a):
    return _git("-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential", *a)


def _cagr(curve: pd.Series) -> float:
    yrs = (curve.index[-1] - curve.index[0]).days / 365.25
    return float((curve.iloc[-1] / curve.iloc[0]) ** (1 / yrs) - 1)


def _stats(curve: pd.Series) -> dict:
    r = curve.pct_change().dropna()
    return {"total_return": float(curve.iloc[-1] / curve.iloc[0] - 1), "cagr": _cagr(curve),
            "sharpe": float(r.mean() / r.std() * math.sqrt(252)) if r.std() > 0 else float("nan"),
            "max_drawdown": float((curve / curve.cummax() - 1).min())}


def swept(eq_df: pd.DataFrame, bench: pd.Series) -> pd.Series:
    eq = eq_df["equity"]
    cash_w = (eq_df["cash"] / eq).shift(1).fillna(1.0).clip(0, 1)
    rb = bench.reindex(eq.index).ffill().pct_change().fillna(0.0)
    r = eq.pct_change().fillna(0.0) + cash_w * rb
    return (1 + r).cumprod() * eq.iloc[0]


def evaluate(name, out_dir: Path, start, end) -> dict:
    eq_df = pd.read_csv(out_dir / "equity.csv", index_col=0, parse_dates=True)
    blend = reports.benchmark_curves(eq_df.index[0], eq_df.index[-1])["MDY_IJR_5050"].reindex(eq_df.index).ffill()
    ew = reports.ew_index_members(eq_df.index[0], eq_df.index[-1]).reindex(eq_df.index).ffill()
    m = json.loads((out_dir / "metrics.json").read_text())
    s_blend, s_ew = swept(eq_df, blend), swept(eq_df, ew)
    return {"arm": name, "window": [start, end], "audit_passed": m.get("audit_passed"),
            "raw": _stats(eq_df["equity"]), "trades": m["metrics"]["strategy"].get("trades"),
            "exposure": m["metrics"]["strategy"].get("exposure"),
            "win_rate": m["metrics"]["strategy"].get("win_rate"),
            "swept_into_blend": _stats(s_blend), "swept_into_ew": _stats(s_ew),
            "blend": _stats(blend), "ew_members": _stats(ew)}


def run_arms(arms: dict, start, end, token, out_root: Path) -> dict:
    res = {}
    for name, params in arms.items():
        d = out_root / name
        run_one(start, end, params | X3.BASE, run_id=name, tickers=X2.index_universe(), allow_validation2=token,
                out_dir=d, benchmarks=True)
        res[name] = evaluate(name, d, start, end)
    return res


def insample():
    from kashif_engine import panel as PANEL
    PANEL.build(X2.index_universe(), "US", name="US_idx", log=lambda *a: None)   # adds high50_prev / tt_early
    start, end = X3.INSAMPLE
    res = run_arms(X3.ARMS | X3.REFS, start, end, None, OUT / "insample_2024_2026")
    RES.mkdir(parents=True, exist_ok=True)
    (RES / "INSAMPLE_2024_2026.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps({k: {"raw_cagr": v["raw"]["cagr"], "swept_blend_cagr": v["swept_into_blend"]["cagr"],
                          "blend_cagr": v["blend"]["cagr"], "trades": v["trades"]} for k, v in res.items()}, indent=1))


def exp3a():
    lock = OUT / "EXP3A_LOCK"
    dirty = [ln for ln in _git("status", "--porcelain").stdout.splitlines()
             if ln[3:].startswith(("kashif_engine/", "us_fundamentals/")) and ln[3:].endswith(".py")]
    if lock.exists() or _git("log", "--all", "--oneline", "--", LOCK_REL).stdout.strip() or dirty:
        sys.exit(f"REFUSED: lock exists / claimed before / uncommitted code {dirty}")
    from kashif_engine import panel as PANEL
    PANEL.build(X2.index_universe(), "US", name="US_idx", log=lambda *a: None)   # before the claim
    OUT.mkdir(parents=True, exist_ok=True)
    nonce = secrets.token_hex(16)
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w") as f:
        json.dump({"claimed_utc": datetime.now(timezone.utc).isoformat(), "nonce": nonce,
                   "arms": X3.ARMS, "git_commit": _git("rev-parse", "HEAD").stdout.strip()}, f, indent=1)
    _git("add", "-f", LOCK_REL)
    if _git("-c", "commit.gpgsign=false", "commit", "--no-verify", "-m",
            "Experiment 3a: 2017-2021 window claimed for the frozen arms B1-B3", "--", LOCK_REL).returncode != 0 \
            or _git_remote("push", "-q", REMOTE, "HEAD:main").returncode != 0:
        sys.exit("REFUSED: could not commit and push the claim")
    lk = json.loads(lock.read_text())
    try:
        res = run_arms(X3.ARMS, *X3.EXP3A, nonce, OUT / "exp3a_2017_2021")
        for v in res.values():
            v["verdict"] = ("INVALID" if v["audit_passed"] is not True else
                            "KILLED" if v["swept_into_ew"]["cagr"] <= v["ew_members"]["cagr"] else "NOT_FALSIFIED")
    except BaseException as e:  # noqa: BLE001 -- recorded, never retried
        lk |= {"failed_utc": datetime.now(timezone.utc).isoformat(), "error": repr(e), "traceback": traceback.format_exc()}
        lock.write_text(json.dumps(lk, indent=1, default=str))
        _git("add", "-f", LOCK_REL)
        _git("-c", "commit.gpgsign=false", "commit", "--no-verify", "-m", "Experiment 3a FAILED", "--", LOCK_REL)
        _git_remote("push", "-q", REMOTE, "HEAD:main")
        raise
    lk |= {"finished_utc": datetime.now(timezone.utc).isoformat(), "verdicts": {k: v["verdict"] for k, v in res.items()}}
    lock.write_text(json.dumps(lk, indent=1, default=str))
    RES.mkdir(parents=True, exist_ok=True)
    (RES / "EXP3A_2017_2021.json").write_text(json.dumps(res, indent=2, default=str))
    _git("add", "-f", LOCK_REL, "backtest_results/experiment3/EXP3A_2017_2021.json")
    _git("-c", "commit.gpgsign=false", "commit", "--no-verify", "-m", "Experiment 3a finished: verdicts",
         "--", LOCK_REL, "backtest_results/experiment3/EXP3A_2017_2021.json")
    _git_remote("push", "-q", REMOTE, "HEAD:main")
    print(json.dumps({k: {"verdict": v["verdict"], "raw_cagr": v["raw"]["cagr"],
                          "swept_ew_cagr": v["swept_into_ew"]["cagr"], "ew_cagr": v["ew_members"]["cagr"],
                          "swept_blend_cagr": v["swept_into_blend"]["cagr"], "blend_cagr": v["blend"]["cagr"],
                          "trades": v["trades"]} for k, v in res.items()}, indent=1))


if __name__ == "__main__":
    {"insample": insample, "exp3a": exp3a}[sys.argv[1]]()
