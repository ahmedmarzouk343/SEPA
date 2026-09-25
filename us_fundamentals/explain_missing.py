"""Give every missing revenue / net income / EPS value a specific cause.

Checks the final dataset's notes, the raw SEC companyfacts, and the class-level
EPS supplement. Anything that fits no known cause is reported as UNEXPLAINED so
that a blank explanation can never hide.  Output: missing_values_explained.csv
"""
import json, sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from gap_diagnosis import facts
from merged_pipeline import (_days, REV_CONCEPTS, NI_CONCEPTS, EPS_CONCEPTS,
                             BANK_NII_CONCEPTS, _originally_filed)

HERE = Path(__file__).parent
FORMS = ("10-Q", "10-Q/A", "10-K", "10-K/A")
SUP = json.loads((HERE / "class_eps_supplement.json").read_text()) \
    if (HERE / "class_eps_supplement.json").exists() else {}


def period_facts(g, concepts, end, units=("USD", "USD/shares", "shares")):
    """(concept, kind, originally_filed) for facts on this period end.
    originally_filed is only meaningful for annual facts."""
    out = []
    for c in concepts:
        for u in units:
            for e in g.get(c, {}).get("units", {}).get(u, []):
                if e.get("end") != end or e.get("form") not in FORMS:
                    continue
                d = _days(e) or 0
                kind = "Q" if 60 <= d <= 120 else ("FY" if d >= 300 else None)
                if kind:
                    out.append((c, kind, _originally_filed(end, e.get("filed", ""))))
    return out


def revenue_like(g):
    return [c for c in g if "Revenue" in c and not c.startswith(
        ("Deferred", "IncreaseDecrease", "ContractWithCustomer", "Cost"))]


REJECT_WORD = {"revenue": "revenue", "eps": "EPS", "net_income": "NI"}


def cause(field, r, g):
    notes = r.notes if isinstance(r.notes, str) else ""
    for part in notes.split("; "):
        if part.startswith("REJECTED") and REJECT_WORD[field] in part:
            return "rejected by sanity check: " + part.split(": ", 1)[1]
    end, q4 = r.quarter_end_date, r.fiscal_quarter.startswith("Q4")

    if field == "revenue":
        std = period_facts(g, REV_CONCEPTS + BANK_NII_CONCEPTS + ["NoninterestIncome"], end, ("USD",))
        if q4:
            fy = [f for f in std if f[1] == "FY"]
            if not fy:
                return "Q4 not derivable: no annual revenue fact in the 10-K"
            if not [f for f in std if f[1] == "FY" and f[2]]:
                return "Q4 not derivable: annual revenue only in later (restated) 10-K comparatives"
            return ("Q4 not derivable: Q1-Q3 revenue incomplete or on a different basis "
                    "than the annual (bank composite / concept change)")
        if not std:
            other = [c for c in revenue_like(g) if period_facts(g, [c], end, ("USD",))]
            if other:
                return f"revenue tagged only as sub-line(s) {other[:2]}, no total-revenue concept"
            return "no revenue fact filed for this period in any us-gaap concept (company-specific tag or pre-revenue)"
        return "only a restated next-year comparative exists (restatement detected nearby; not as-filed)"

    if field == "eps":
        sup = SUP.get(r.ticker)
        class_filer = bool(sup and sup.get("rows"))
        eps_f = period_facts(g, EPS_CONCEPTS + ["EarningsPerShareBasicAndDiluted"], end, ("USD/shares",))
        sh_f = period_facts(g, ["WeightedAverageNumberOfDilutedSharesOutstanding",
                                "WeightedAverageNumberOfShareOutstandingBasicAndDiluted"], end, ("shares",))
        if q4 and class_filer:
            return ("Q4 class-level EPS not derivable: the 10-K has no Q4 figure and the year's "
                    "quarters/FY use different dilution bases or tags (Up-C if-converted) or span a split")
        if q4:
            if not sh_f:
                return "Q4 EPS not derivable: no Q4 or annual diluted share count as filed, and no Q4 EPS in the 10-K"
            return "Q4 EPS not derivable: late-filed annual share count disagrees with Q1-Q3 (split/restatement)"
        if class_filer:
            return "class-level EPS not tagged for this period in its filing (and no non-class EPS)"
        if not eps_f and not sh_f:
            return ("no EPS or diluted share count filed for this period, non-class or class-level "
                    "(typically pre-IPO / first-10-K periods)")
        return "EPS only in a next-year comparative that failed the restatement/split checks"

    if field == "net_income":
        ni_f = period_facts(g, NI_CONCEPTS, end, ("USD",))
        if q4:
            return "Q4 NI not derivable: annual or Q1-Q3 net income missing as filed"
        return "no net income fact for this period as filed" if not ni_f else \
            "net income only in restated comparatives"
    return "UNEXPLAINED"


def main():
    df = pd.read_csv(HERE / "scaled_fundamentals.csv")
    out = []
    for tk, t in df.groupby("ticker"):
        miss = t[t.revenue.isna() | t.net_income.isna() | t.eps.isna()]
        if miss.empty:
            continue
        g = facts(tk)
        for _, r in miss.iterrows():
            for field in ("revenue", "net_income", "eps"):
                if pd.isna(r[field]):
                    out.append({"ticker": tk, "fiscal_quarter": r.fiscal_quarter,
                                "quarter_end_date": r.quarter_end_date, "field": field,
                                "cause": cause(field, r, g)})
    o = pd.DataFrame(out)
    o.to_csv(HERE / "missing_values_explained.csv", index=False)
    print(f"{len(o)} missing values explained; UNEXPLAINED: {(o.cause == 'UNEXPLAINED').sum()}")
    o["cause_group"] = o.cause.str.replace(r"\(.*|\[.*|: .*", "", regex=True).str.strip()
    print(o.groupby(["field", "cause_group"]).size().to_string())


if __name__ == "__main__":
    main()
