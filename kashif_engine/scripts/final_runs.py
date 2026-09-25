"""Phase 5 deliverables for one window: frozen-parameter runs with and without
catalyst ranking, QuantStats HTML, and the committed result files.

    python kashif_engine/scripts/final_runs.py tune       # tuning window
    python kashif_engine/scripts/final_runs.py holdout    # after run_holdout.py (copies only)
"""
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kashif_engine import reports  # noqa: E402
from kashif_engine.run_backtest import run_one  # noqa: E402
from kashif_engine.tune import TUNE  # noqa: E402

OUT = ROOT / "backtest_results"
RUNS = ROOT / "kashif_data" / "runs"
KEEP = ("trades.csv", "fills.csv", "dividends.csv", "equity.csv", "metrics.json", "audit.json", "run.json",
        "candidates.csv", "sizing_state.csv", "events.csv", "decision_receipts.parquet")


def publish(run_id, title):
    src = RUNS / run_id
    dst = OUT / run_id
    dst.mkdir(parents=True, exist_ok=True)
    for f in KEEP:
        if (src / f).exists():
            shutil.copy(src / f, dst / f)
    eq = pd.read_csv(src / "equity.csv", index_col=0, parse_dates=True)["equity"]
    bench = reports.benchmark_curves(eq.index[0], eq.index[-1])["MDY_IJR_5050"]
    reports.quantstats_html(eq, bench, dst / f"quantstats_{run_id}.html", title)


def main():
    which = sys.argv[1]
    sel = json.loads((ROOT / "kashif_data" / "tuning" / "selection.json").read_text())
    params = dict(sel["final_params"])
    if which == "tune":
        cat = ROOT / "kashif_data" / "catalyst" / "catalyst_scores_tune.parquet"
        arms = {"TUNE_final": params,
                "TUNE_final_with_catalyst": params | {"use_catalyst": True, "catalyst_path": str(cat)}}
        for rid, p in arms.items():
            out = run_one(TUNE[0], TUNE[1], p, run_id=rid, out_dir=RUNS / rid)
            print(rid, json.dumps({k: out["metrics"]["strategy"].get(k) for k in
                                   ("total_return", "cagr", "max_drawdown", "sharpe", "trades", "win_rate",
                                    "win_loss_ratio", "exposure")}, default=str), "audit", out["audit_passed"])
            publish(rid, f"Minervini SEPA v1 - {rid} (vs MDY/IJR 50/50)")
    else:
        for rid in ("HOLDOUT_primary", "HOLDOUT_with_catalyst"):
            publish(rid, f"Minervini SEPA v1 - {rid} (vs MDY/IJR 50/50)")
    for f in ("grid_full.csv", "walkforward.csv", "selection.json", "trials.csv"):
        p = ROOT / "kashif_data" / "tuning" / f
        if p.exists():
            (OUT / "tuning").mkdir(parents=True, exist_ok=True)
            shutil.copy(p, OUT / "tuning" / f)


if __name__ == "__main__":
    main()
