"""Per-ticker health table for the final dataset (per_ticker_summary.csv).

Every missing value and every quarter gap carries a specific cause, taken from
missing_values_explained.csv and gap_diagnosis.csv. A ticker with any cause
that couldn't be classified is REVIEW.
"""
from pathlib import Path
import pandas as pd

from fundamentals_store import STOCK_SPLITS

HERE = Path(__file__).parent
df = pd.read_csv(HERE / "scaled_fundamentals.csv")
gaps = pd.read_csv(HERE / "gap_diagnosis.csv")
labels = pd.read_csv(HERE / "label_inconsistencies.csv")
miss = pd.read_csv(HERE / "missing_values_explained.csv")
notes = df["notes"].fillna("")
# Every gap class was traced to a cause (see FINAL_VERIFICATION_REPORT.md).
GAP_CAUSE = {
    "ANNUAL_ONLY": "first 10-K after IPO/spin-off (no 10-Qs that year)",
    "RAW_QUARTER_EXISTS": "corporate event: FY change / predecessor-successor stub / new registrant",
    "NO_10K_FACTS": "no 10-K facts in SEC companyfacts",
    "SOURCE_GAP": "no filing covers the period",
}

rows = []
for tk, t in df.groupby("ticker"):
    n = notes.loc[t.index]
    g = gaps[gaps["ticker"] == tk]
    m = miss[miss["ticker"] == tk]
    basis = n.str.extract(r"revenue basis: ([^;]+)")[0].dropna().unique()
    rec = {
        "ticker": tk,
        "quarters": len(t),
        "first_quarter_end": t["quarter_end_date"].min(),
        "last_quarter_end": t["quarter_end_date"].max(),
        "missing_revenue": int(t["revenue"].isna().sum()),
        "missing_net_income": int(t["net_income"].isna().sum()),
        "missing_eps": int(t["eps"].isna().sum()),
        "missing_release_date": int(t["earnings_release_date"].isna().sum()),
        "missing_value_causes": " | ".join(
            f"{f}: {c}" for (f, c), _ in m.groupby(["field", "cause"])),
        "unexplained_missing": int((m["cause"] == "UNEXPLAINED").sum()),
        "rejected_values": int(n.str.contains("REJECTED").sum()),
        "flagged_values": int(n.str.contains("FLAG:").sum()),
        "eps_scale_errors_corrected": int(n.str.contains("scale error").sum()),
        "eps_from_class_level_xbrl": int(n.str.contains("XBRL instance").sum()),
        "values_from_comparatives": int(n.str.contains("comparative").sum()),
        "gaps": len(g),
        "gap_causes": "; ".join(sorted({GAP_CAUSE[c] for c in g["class"]})),
        "label_steps_inconsistent": int((labels["ticker"] == tk).sum()),
        "splits_in_table": "; ".join(f"{s['effective_date']} ratio {s['ratio']}"
                                     for s in STOCK_SPLITS.get(tk, [])),
        "revenue_basis": basis[0] if len(basis) else "total revenues",
    }
    missing = rec["missing_revenue"] + rec["missing_net_income"] + rec["missing_eps"]
    assert missing == len(m), f"{tk}: {missing} missing values but {len(m)} explanations"
    if rec["rejected_values"] or rec["label_steps_inconsistent"] or rec["unexplained_missing"]:
        status = "REVIEW"
    elif missing or rec["gaps"]:
        status = "OK_WITH_KNOWN_GAPS"
    else:
        status = "CLEAN"
    rec["status"] = status
    rows.append(rec)

out = pd.DataFrame(rows)
out.to_csv(HERE / "per_ticker_summary.csv", index=False)
print(out["status"].value_counts().to_string())
blank = out[(out.missing_revenue + out.missing_net_income + out.missing_eps > 0)
            & (out.missing_value_causes == "")]
print(f"tickers with missing values but no cause: {len(blank)}")
print(f"unexplained missing values: {out.unexplained_missing.sum()}")
