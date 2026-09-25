"""Classify every >120-day mid-series gap as extraction bug vs genuine source gap.

For each gap window (prev_end, next_end) we search the raw SEC companyfacts:
  RAW_QUARTER_EXISTS  a 60-120 day 10-Q/10-K fact (rev/NI/EPS) ends inside the
                      window -> the pipeline dropped data it could have used (BUG)
  ANNUAL_ONLY         no quarterly fact, but a >=300 day fact ends inside the
                      window -> Q4 derivation should have produced it (BUG)
  NO_10K_FACTS        ticker has zero annual facts in companyfacts at all, so Q4
                      cannot be derived (SOURCE GAP)
  SOURCE_GAP          nothing in the raw data for the window (SOURCE GAP)
"""
import json, sys, time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
from merged_pipeline import (cik_for, SEC_UA, REV_CONCEPTS, NI_CONCEPTS,
                             EPS_CONCEPTS, BANK_NII_CONCEPTS, _days)

SCRATCHPAD = Path(__file__).parent
CACHE = SCRATCHPAD / "companyfacts_cache"
CACHE.mkdir(exist_ok=True)
CONCEPTS = REV_CONCEPTS + NI_CONCEPTS + EPS_CONCEPTS + BANK_NII_CONCEPTS
FORMS = ("10-Q", "10-Q/A", "10-K", "10-K/A")


def facts(ticker):
    p = CACHE / f"{ticker}.json"
    if p.exists():
        return json.loads(p.read_text())
    cik = cik_for(ticker)
    for attempt in range(6):
        r = requests.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
                         headers={"User-Agent": SEC_UA}, timeout=30)
        time.sleep(0.15)
        if r.status_code not in (403, 429, 500, 502, 503, 504):
            break
        time.sleep(2 ** attempt * 5)
    if r.status_code == 404:
        return {}
    r.raise_for_status()  # never cache a throttled response as "no facts"
    g = r.json().get("facts", {}).get("us-gaap", {})
    p.write_text(json.dumps(g))
    return g


def raw_entries(gaap):
    out = []
    for c in CONCEPTS:
        units = gaap.get(c, {}).get("units", {})
        for u in ("USD", "USD/shares"):
            for e in units.get(u, []):
                if e.get("form") in FORMS and e.get("end"):
                    out.append((c, e))
    return out


def gaps_from_csv(df):
    res = []
    for tk, tdf in df.groupby("ticker"):
        tdf = tdf.sort_values("quarter_end_date")
        d = pd.to_datetime(tdf["quarter_end_date"]).tolist()
        fq = tdf["fiscal_quarter"].tolist()
        for i in range(1, len(d)):
            if (d[i] - d[i - 1]).days > 120:
                res.append((tk, d[i - 1], d[i], fq[i - 1], fq[i]))
    return res


def classify(tk, lo, hi):
    ents = raw_entries(facts(tk))
    has_annual = any((_days(e) or 0) >= 300 for _, e in ents)
    lo_w, hi_w = lo + timedelta(days=20), hi - timedelta(days=20)
    q_hits, a_hits = [], []
    for c, e in ents:
        end = datetime.strptime(e["end"], "%Y-%m-%d")
        if not (lo_w <= end <= hi_w):
            continue
        d = _days(e)
        if d is not None and 60 <= d <= 120:
            q_hits.append(f"{c}:{e['end']}:{e['form']}")
        elif d is not None and d >= 300:
            a_hits.append(f"{c}:{e['end']}:{e['form']}")
    if q_hits:
        return "RAW_QUARTER_EXISTS", sorted(set(q_hits))[:3]
    if a_hits:
        return "ANNUAL_ONLY", sorted(set(a_hits))[:3]
    if not has_annual:
        return "NO_10K_FACTS", []
    return "SOURCE_GAP", []


def main():
    df = pd.read_csv(SCRATCHPAD / "scaled_fundamentals.csv")
    gaps = gaps_from_csv(df)
    print(f"{len(gaps)} gaps across {len(set(g[0] for g in gaps))} tickers")
    rows = []
    for tk, lo, hi, fq0, fq1 in gaps:
        cls, ev = classify(tk, lo, hi)
        rows.append({"ticker": tk, "from": lo.date(), "to": hi.date(),
                     "days": (hi - lo).days, "from_q": fq0, "to_q": fq1,
                     "class": cls, "evidence": "; ".join(ev)})
    out = pd.DataFrame(rows)
    out.to_csv(SCRATCHPAD / "gap_diagnosis.csv", index=False)
    print(out["class"].value_counts().to_string())
    print("\nBy ticker:")
    print(out.groupby("class")["ticker"].nunique().to_string())
    for cls in ("RAW_QUARTER_EXISTS", "ANNUAL_ONLY"):
        sub = out[out["class"] == cls]
        if len(sub):
            print(f"\n{cls} ({len(sub)}):")
            print(sub.head(40).to_string(index=False))


if __name__ == "__main__":
    main()
