"""Phase 4 driver: full-window grid, walk-forward folds, final selection.

Uses ONLY the tuning bundle (2022-01-03 .. 2024-06-28). Writes
kashif_data/tuning/{grid_full.csv, walkforward.csv, selection.json}.
The holdout is not touched here.
"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kashif_engine import tune as T  # noqa: E402

BUNDLE = str(ROOT / "kashif_data" / "signals" / "bundle_tune.pkl")


def main(workers=6):
    T.OUT.mkdir(parents=True, exist_ok=True)
    grid = T.combos()
    print(f"grid: {len(grid)} combinations x (1 full window + {len(T.FOLDS)} train folds) "
          f"+ {len(T.FOLDS)} fold tests")

    # 1. Full tuning window, every combination.
    full = T.run_batch([(T.TUNE[0], T.TUNE[1], p, BUNDLE, "full") for p in grid], workers=workers)
    full.to_csv(T.OUT / "grid_full.csv", index=False)
    best, ranked = T.select(full, T.MIN_TRADES_FULL)
    print("full-window pick (neighbour-median Sharpe):", best)

    # 2. Walk-forward: select on each anchored train window, test the pick out of sample.
    wf_rows = []
    tune_days = (pd.Timestamp(T.TUNE[1]) - pd.Timestamp(T.TUNE[0])).days
    for k, ((tr_s, tr_e), (te_s, te_e)) in enumerate(T.FOLDS, 1):
        tr = T.run_batch([(tr_s, tr_e, p, BUNDLE, f"wf{k}_train") for p in grid], workers=workers)
        frac = (pd.Timestamp(tr_e) - pd.Timestamp(tr_s)).days / tune_days
        min_tr = max(10, int(round(T.MIN_TRADES_FULL * frac)))
        pick, _ = T.select(tr, min_tr)
        if pick is None:
            wf_rows.append({"fold": k, "train": f"{tr_s}..{tr_e}", "test": f"{te_s}..{te_e}",
                            "pick": None, "note": f"no combination met >= {min_tr} trades and maxDD <= 25%"})
            continue
        te = T.run_batch([(te_s, te_e, pick, BUNDLE, f"wf{k}_test")], workers=1).iloc[0].to_dict()
        wf_rows.append({"fold": k, "train": f"{tr_s}..{tr_e}", "test": f"{te_s}..{te_e}",
                        "min_trades_train": min_tr, "pick": json.dumps(pick),
                        **{f"test_{c}": te.get(c) for c in ("trades", "sharpe", "cagr", "max_dd",
                                                             "total_return", "win_rate", "wl_ratio",
                                                             "audit_passed", "run_id")}})
    wf = pd.DataFrame(wf_rows)
    wf.to_csv(T.OUT / "walkforward.csv", index=False)
    print(wf.to_string())

    trials = pd.read_csv(T.OUT / "trials.csv")
    sel = {"final_params": best, "objective": "neighbour-median daily Sharpe, >=30 trades, maxDD<=25%",
           "n_combinations_in_grid": len(grid), "n_backtests_run_total": int(len(trials)),
           "top10": [{"median_nbhd_sharpe": m, "own_sharpe": o, **p} for m, o, p in ranked[:10]]}
    json.dump(sel, open(T.OUT / "selection.json", "w"), indent=2, default=str)
    print(json.dumps(sel, indent=2, default=str))


if __name__ == "__main__":
    main()
