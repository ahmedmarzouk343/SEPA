"""Check that fiscal-quarter labels advance in step with period end dates.

Between consecutive rows the label index (4*FY + Q) must advance by the number
of quarters the end dates advance (days / 91.3, rounded). Anything else is a
mislabeled quarter or fiscal year.
"""
from pathlib import Path
import pandas as pd

df = pd.read_csv(Path(__file__).parent / "scaled_fundamentals.csv")
df["qed"] = pd.to_datetime(df["quarter_end_date"])
lab = df["fiscal_quarter"].str.extract(r"Q(\d) (\d{4})").astype(int)
df["idx"] = lab[1] * 4 + lab[0]

bad = []
for tk, t in df.sort_values("qed").groupby("ticker"):
    t = t.reset_index(drop=True)
    for i in range(1, len(t)):
        want = round((t.qed[i] - t.qed[i - 1]).days / 91.3)
        got = t.idx[i] - t.idx[i - 1]
        if got != want:
            bad.append({"ticker": tk, "prev": f"{t.fiscal_quarter[i-1]}@{t.quarter_end_date[i-1]}",
                        "next": f"{t.fiscal_quarter[i]}@{t.quarter_end_date[i]}",
                        "quarters_by_date": want, "quarters_by_label": got})
out = pd.DataFrame(bad)
out.to_csv(Path(__file__).parent / "label_inconsistencies.csv", index=False)
print(f"{len(out)} label steps inconsistent with dates, in {out['ticker'].nunique() if len(out) else 0} tickers")
if len(out):
    print(out.to_string(index=False))
