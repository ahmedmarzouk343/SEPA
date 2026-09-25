"""Turn the verified 2014-2021 split research into us_fundamentals/splits_2014_2021.py.

Input : kashif_data/experiment2/splits_2014_2021.json (from the research session)
Output: us_fundamentals/splits_2014_2021.py -- a dict merged into
        fundamentals_store.STOCK_SPLITS at import. The already-verified
        2021+ table is not edited.
Only rows with verdict VERIFIED and kind split / reverse_split /
stock_dividend are kept; everything else is listed as rejected.
"""
import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "kashif_data" / "experiment2" / "splits_2014_2021.json"
OUT = ROOT / "us_fundamentals" / "splits_2014_2021.py"
# Later verified finds (e.g. stock dividends Yahoo missed), same schema; any date.
ADDITIONS = sorted((ROOT / "kashif_data" / "experiment2").glob("splits_*additions*.json"))
KEEP = {"split", "reverse_split", "stock_dividend"}
# Rule: apply a split only when it was done by the registrant whose SEC filings form
# the stored EPS series. Rulings on the research session's flagged rows:
EXCLUDE = {
    ("AA", "2016-10-05"): "done by Alcoa Inc. (CIK 4281), not Alcoa Corp (CIK 1675149)",
    ("OVV", "2020-01-24"): "Encana consolidation; Ovintiv's series is built from its own post-consolidation filings",
    ("OZK", "2014-06-23"): "holding company CIK; no SEC fundamentals exist for OZK",
    ("UA", "2016-06-29"): "Class C settlement dividend; company adjusted the EPS numerator, not share counts",
}


def main():
    rows = json.loads(SRC.read_text())
    for a in ADDITIONS:
        rows += json.loads(a.read_text())
    keep, reject = [], []
    for r in rows:
        ok = r.get("verdict") == "VERIFIED" and r.get("kind") in KEEP and \
            (r["ticker"], r["effective_date"][:10]) not in EXCLUDE
        (keep if ok else reject).append(r)
    lines = ['"""Stock splits 2014-2021, verified from primary sources by a research session',
             f'for experiment 2 ({len(keep)} kept, {len(reject)} rejected -- see',
             'kashif_data/experiment2/splits_2014_2021.json for evidence and rejections).',
             'Merged into fundamentals_store.STOCK_SPLITS at import; the 2021+ table is untouched."""',
             "from datetime import date", "from fractions import Fraction as F", "",
             "SPLITS_2014_2021 = {"]
    by_t = {}
    for r in sorted(keep, key=lambda r: (r["ticker"], r["effective_date"])):
        by_t.setdefault(r["ticker"], []).append(r)
    for t, rs in by_t.items():
        items = []
        for r in rs:
            y, m, d = (int(x) for x in r["effective_date"][:10].split("-"))
            ratio = Fraction(int(r["ratio_new"]), int(r["ratio_old"]))
            items.append(f'{{"effective_date": date({y}, {m}, {d}), "ratio": F({ratio.numerator}, {ratio.denominator}), '
                         f'"evidence": {json.dumps(str(r.get("evidence_url_or_accession", "")))}}}')
        lines.append(f'    "{t}": [' + ",\n            ".join(items) + "],")
    lines.append("}")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"kept {len(keep)} splits in {len(by_t)} tickers; rejected {len(reject)}: "
          f"{sorted({(r['ticker'], r.get('kind')) for r in reject})[:15]}")


if __name__ == "__main__":
    sys.exit(main())
