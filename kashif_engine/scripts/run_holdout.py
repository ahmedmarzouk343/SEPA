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
import json
import sys
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
    LOCK.write_text(json.dumps({"started_utc": started, "arms": arms}, default=str))
    results = {}
    for name, params in arms.items():
        # Full prepare (signal caches make it fast) so each run writes complete decision receipts.
        results[name] = run_one(HOLDOUT[0], HOLDOUT[1], params, run_id=name,
                                out_dir=ROOT / "kashif_data" / "runs" / name)
    LOCK.write_text(json.dumps({"started_utc": started, "finished_utc": datetime.now(timezone.utc).isoformat(),
                                "arms": arms, "run_ids": list(results)}, default=str))
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
