"""Find likely stock splits missing from fundamentals_store.STOCK_SPLITS.

As-filed EPS jumps by the split ratio at a split, so implied diluted shares
(NI / EPS) step by that ratio and stay there. Candidates are reported for
human verification; they are NOT added to the verified split table.
"""
import sys
from pathlib import Path
from statistics import median
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from fundamentals_store import STOCK_SPLITS

RATIOS = [2, 3, 4, 5, 8, 10, 15, 20, 25, 30, 40, 50]
TOL = 0.05
# Two quarters each side: three missed COKE (one bad row nearby) and LXP
# (split within three quarters of the data's end).
WIN = 2          # quarters on each side of the step
STABLE = 1.3     # max/min implied shares within a side (buybacks, rounding)

df = pd.read_csv(Path(__file__).parent / "scaled_fundamentals.csv")
# Small EPS makes NI/EPS dominated by rounding; skip it.
df = df[df["eps"].abs() >= 0.25].dropna(subset=["net_income", "eps"])
df["implied_shares"] = df["net_income"] / df["eps"]
df = df[df["implied_shares"] > 0]

known = {tk for tk in STOCK_SPLITS}
out = []
for tk, t in df.sort_values("quarter_end_date").groupby("ticker"):
    s = t["implied_shares"].tolist()
    d = t["quarter_end_date"].tolist()
    for i in range(WIN, len(s) - WIN + 1):
        b, a = s[i - WIN:i], s[i:i + WIN]
        if max(b) / min(b) > STABLE or max(a) / min(a) > STABLE:
            continue
        before, after = median(b), median(a)
        r = after / before
        for R in RATIOS:
            for label, target in ((f"{R}:1", R), (f"1:{R} reverse", 1 / R)):
                if abs(r / target - 1) <= TOL:
                    out.append({"ticker": tk, "between": f"{d[i-1]} -> {d[i]}",
                                "implied_ratio": round(r, 3), "looks_like": label,
                                "in_split_table": tk in known})
cand = pd.DataFrame(out).drop_duplicates(subset=["ticker", "looks_like"])
cand.to_csv(Path(__file__).parent / "split_candidates.csv", index=False)
print(f"{len(cand)} candidate splits across {cand['ticker'].nunique() if len(cand) else 0} tickers")
print(cand.to_string(index=False))
