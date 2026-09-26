"""Export the verified split table plus the rejected candidates (split_table.csv)."""
from pathlib import Path
import pandas as pd
from fundamentals_store import STOCK_SPLITS

REJECTED = [
    ("AAMI", "2021-12", "tender-offer buyback of ~43% of shares", "SC TO-I/A 0001104659-21-147893"),
    ("CHRD", "2022-07", "Oasis-Whiting merger share issuance", "8-K 0001193125-22-189506"),
    ("RBA",  "2023-03", "IAA acquisition share issuance", "8-K 0001104659-23-034673"),
    ("CRGY", "2023-06", "OpCo unit conversion to Class A + public offering", "10-Q 0001866175-23-000073"),
    ("BBT",  "2025-09", "Berkshire-Brookline reverse acquisition (history replaced)", "8-K 0001108134-25-000017"),
    ("COKE", "2025-11", "buyback of The Coca-Cola Company's 18.8M shares (split in May 2025 is real)",
     "8-K 0001628280-25-050682"),
    ("PNFP", "2026-01", "Pinnacle-Synovus merger into a new holding company", "8-K 0001115055-26-000002"),
    ("SM",   "2026-01", "Civitas Resources merger share issuance", "8-K 0001104659-26-008380"),
]

rows = []
for tk, events in STOCK_SPLITS.items():
    for s in events:
        r = s["ratio"]
        rows.append({"ticker": tk, "status": "VERIFIED", "effective_date": s["effective_date"],
                     "ratio_new_per_old": str(r), "ratio_float": float(r),
                     "type": "reverse" if r < 1 else "forward",
                     "label": f"{r.numerator}-for-{r.denominator}" if r < 1 else f"{r}-for-1",
                     "sec_accession": s.get("sec_8k", s.get("evidence")),       # merged research rows carry "evidence"
                     "filing": s.get("filing", "8-K" if "sec_8k" in s else "research (splits_2014_2021.py)"),
                     "note": ""})
for tk, when, what, acc in REJECTED:
    rows.append({"ticker": tk, "status": "REJECTED (not a split)", "effective_date": when,
                 "ratio_new_per_old": "", "ratio_float": None, "type": "", "label": "",
                 "sec_accession": acc.rsplit(" ", 1)[1], "filing": acc.rsplit(" ", 1)[0], "note": what})
out = pd.DataFrame(rows).sort_values(["status", "effective_date"])
out.to_csv(Path(__file__).parent / "split_table.csv", index=False)
print(out[["ticker", "status", "effective_date", "label", "sec_accession", "note"]].to_string(index=False))
