"""Phase 5: the ONE holdout evaluation (2024-07-01 .. 2026-09-24).

Pre-declared before any holdout number existed:
  * PRIMARY arm   = the frozen parameters from kashif_data/tuning/selection.json
                    (written by run_tuning.py), catalyst OFF.
  * SECONDARY arm = identical parameters + catalyst ranking ON, so the report
                    can say whether the catalyst helped out of sample.
Both arms run once, from this single invocation; the verdict in the report is
the PRIMARY arm. The first invocation writes kashif_data/tuning/HOLDOUT_LOCK and
every later invocation refuses to run: re-running after seeing the result would
turn the holdout into a tuning set.

    python kashif_engine/scripts/run_holdout.py
"""
import hashlib
import json
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kashif_engine.run_backtest import run_one  # noqa: E402
from kashif_engine.tune import HOLDOUT  # noqa: E402

TUNING = ROOT / "kashif_data" / "tuning"
LOCK = TUNING / "HOLDOUT_LOCK"
CATALYST = ROOT / "kashif_data" / "catalyst" / "catalyst_scores_holdout.parquet"


def main():
    if LOCK.exists():
        sys.exit(f"REFUSED: the holdout was already run once ({LOCK.read_text().strip()}).")
    sel = json.loads((TUNING / "selection.json").read_text())
    base = dict(sel["final_params"])
    arms = {"HOLDOUT_primary": base,
            "HOLDOUT_with_catalyst": base | {"use_catalyst": True, "catalyst_path": str(CATALYST)}}
    if not CATALYST.exists():
        sys.exit("catalyst scores for the holdout window are missing -- build them first")
    started = datetime.now(timezone.utc).isoformat()
    sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()  # noqa: E731
    frozen = {"selection.json": sha(TUNING / "selection.json"),
              "PREDECLARED_HOLDOUT_ANALYSES.md": sha(TUNING / "PREDECLARED_HOLDOUT_ANALYSES.md"),
              "catalyst_scores_holdout.parquet": sha(CATALYST),
              "strategy_config.json": sha(ROOT / "minervini_sepa_v1_strategy_config.json"),
              "git_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                           text=True).stdout.strip()}
    lock = {"started_utc": started, "arms": arms, "frozen_inputs": frozen}
    LOCK.write_text(json.dumps(lock, indent=2, default=str))
    results = {}
    try:
        for name, params in arms.items():
            # Full prepare (signal caches make it fast) so each run writes complete decision receipts.
            results[name] = run_one(HOLDOUT[0], HOLDOUT[1], params, run_id=name, allow_holdout=True,
                                    out_dir=ROOT / "kashif_data" / "runs" / name)
    except Exception as e:  # noqa: BLE001 -- recorded in the lock; the one-time rerun rule is in the report
        lock |= {"failed_utc": datetime.now(timezone.utc).isoformat(), "error": repr(e),
                 "traceback": traceback.format_exc(), "completed_arms": list(results)}
        LOCK.write_text(json.dumps(lock, indent=2, default=str))
        raise
    lock |= {"finished_utc": datetime.now(timezone.utc).isoformat(), "run_ids": list(results),
             "audit_passed": {k: v.get("audit_passed") for k, v in results.items()}}
    LOCK.write_text(json.dumps(lock, indent=2, default=str))
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
