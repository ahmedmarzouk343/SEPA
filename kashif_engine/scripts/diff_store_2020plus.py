"""Amendment 3: diff the rebuilt fundamentals store against the committed one
for quarters ending 2020-01-01 or later, classified per field.

    python kashif_engine/scripts/diff_store_2020plus.py [git-rev]   (default HEAD)

Writes kashif_data/experiment2/store_diff_2020plus.csv (one row per changed
field) and prints counts by field and by the note that explains the change.
"""
import io
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CSV = "us_fundamentals/scaled_fundamentals.csv"
FIELDS = ["revenue", "net_income", "eps", "earnings_release_date", "fiscal_quarter"]


def main(rev="HEAD"):
    old = pd.read_csv(io.StringIO(subprocess.run(["git", "show", f"{rev}:{CSV}"], cwd=ROOT, capture_output=True,
                                                 text=True, check=True).stdout))
    new = pd.read_csv(ROOT / CSV)
    key = ["ticker", "quarter_end_date"]
    old, new = (d[d["quarter_end_date"] >= "2020-01-01"].set_index(key) for d in (old, new))
    only_old, only_new = old.index.difference(new.index), new.index.difference(old.index)
    both = old.index.intersection(new.index)
    rows = []
    for f in FIELDS:
        a, b = old.loc[both, f], new.loc[both, f]
        if f in ("revenue", "net_income", "eps"):
            diff = ~((a - b).abs() <= 1e-9 * a.abs().clip(lower=1) + 1e-9) & ~(a.isna() & b.isna())
        else:
            diff = (a.astype(str) != b.astype(str))
        for k in diff[diff].index:
            rows.append({"ticker": k[0], "quarter_end_date": k[1], "field": f, "old": a[k], "new": b[k],
                         "new_note": str(new.loc[k, "notes"])[:160]})
    out = pd.DataFrame(rows)
    out.to_csv(ROOT / "kashif_data" / "experiment2" / "store_diff_2020plus.csv", index=False)
    print(f"2020+ rows: old {len(old)}, new {len(new)}, only-old {len(only_old)}, only-new {len(only_new)}")
    if len(only_old):
        print("  dropped:", sorted({t for t, _ in only_old})[:40])
    if len(only_new):
        print("  added:", sorted({t for t, _ in only_new})[:40])
    if out.empty:
        print("no field changed")
        return
    print(out.groupby("field").size().to_string())
    print(f"tickers touched: {out['ticker'].nunique()}")
    for f in FIELDS:
        sub = out[out["field"] == f]
        if len(sub):
            print(f"\n--- {f}: {len(sub)} changes, top notes")
            print(sub["new_note"].str.slice(0, 70).value_counts().head(8).to_string())


if __name__ == "__main__":
    main(*sys.argv[1:])
