"""Phase 5: the ONE holdout run (2024-07-01 .. 2026-09-24).

Reads the frozen parameters from kashif_data/tuning/selection.json (written
by run_tuning.py before this script is ever run) and refuses to run twice:
the first run writes kashif_data/tuning/HOLDOUT_LOCK with the result paths.
Re-running after seeing the result would turn the holdout into a tuning set.

    python kashif_engine/scripts/run_holdout.py [--catalyst]
"""
import argparse
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalyst", action="store_true", help="frozen decision: rank with catalyst scores")
    a = ap.parse_args()
    if LOCK.exists():
        sys.exit(f"REFUSED: the holdout was already run once ({LOCK.read_text().strip()}).")
    sel = json.loads((TUNING / "selection.json").read_text())
    params = dict(sel["final_params"])
    if a.catalyst:
        params.update(use_catalyst=True,
                      catalyst_path=str(ROOT / "kashif_data" / "catalyst" / "catalyst_scores_holdout.parquet"))
    LOCK.write_text(json.dumps({"started_utc": datetime.now(timezone.utc).isoformat(), "params": params},
                               default=str))
    # Full prepare (signal caches make it fast) so the run writes complete decision receipts.
    out = run_one(HOLDOUT[0], HOLDOUT[1], params, run_id="HOLDOUT_final",
                  out_dir=ROOT / "kashif_data" / "runs" / "HOLDOUT_final")
    LOCK.write_text(json.dumps({"started_utc": json.loads(LOCK.read_text())["started_utc"],
                                "finished_utc": datetime.now(timezone.utc).isoformat(),
                                "params": params, "run_id": out["run_id"]}, default=str))
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
