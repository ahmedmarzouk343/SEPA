"""Verify every split in STOCK_SPLITS against the company's OWN restatement.

After a split or stock dividend, a company re-presents earlier quarters on the
new share basis in its next filings' comparative columns. So for a quarter
that ended before the split:

    first-filed EPS / EPS as re-filed after the split  ==  split ratio

That is primary-source evidence for the ratio and the date, immune to the
noise that defeats the NI/EPS share-count proxy of test_split_adjustment.py
TEST 7 (buybacks, preferred dividends, minority interests, cents rounding
against a 3-5% stock dividend).

It also checks the STORE: each stored EPS for a quarter near the split must
equal the first-filed value (as-filed). A stored value that equals the
post-split restatement while its release date is before the split would be
adjusted twice at query time -- that is an error.

    python verify_splits_vs_restatements.py            # all tickers in STOCK_SPLITS
Writes split_restatement_check.csv; exit code 1 if anything is CONTRADICTED
or any stored row is on the wrong basis.
"""
from __future__ import annotations

import math
import sys
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fundamentals_store import STOCK_SPLITS  # noqa: E402
from merged_pipeline import SEC_UA, cik_for  # noqa: E402

TAGS = ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic")
MIN_EPS = 0.20          # below this, cent rounding swamps a 3-5% ratio
TOL = 0.012             # |median ratio / split ratio - 1|
OUT = HERE / "split_restatement_check.csv"


def _d(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def eps_facts(cik):
    for attempt in range(6):
        r = requests.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
                         headers={"User-Agent": SEC_UA}, timeout=30)
        time.sleep(0.25)
        if r.status_code in (403, 429, 500, 502, 503) and attempt < 5:
            time.sleep(2 ** attempt * 5)
            continue
        break
    if r.status_code == 404:
        return []
    r.raise_for_status()
    gaap = r.json().get("facts", {}).get("us-gaap", {})
    out = []
    for tag in TAGS:
        for f in gaap.get(tag, {}).get("units", {}).get("USD/shares", []):
            if not f.get("start") or f.get("form") not in ("10-Q", "10-K", "10-Q/A", "10-K/A"):
                continue
            days = (_d(f["end"]) - _d(f["start"])).days
            if 60 <= days <= 120:
                out.append({"tag": tag, "start": f["start"], "end": f["end"], "val": float(f["val"]),
                            "filed": _d(f["filed"])})
        if out:
            return out          # one tag per company: the first that exists
    return out


def check_split(ticker, split, all_splits, facts, store):
    eff = split["effective_date"]
    ratio = float(split["ratio"])
    nxt = min([s["effective_date"] for s in all_splits if s["effective_date"] > eff], default=date(2100, 1, 1))
    prv = max([s["effective_date"] for s in all_splits if s["effective_date"] < eff], default=date(1900, 1, 1))
    df = pd.DataFrame(facts)
    ratios, per_q = [], {}
    if not df.empty:
        for end, g in df.groupby("end"):
            if not (prv < _d(end) < eff):
                continue
            orig = g[g["filed"] < eff].sort_values("filed")
            rest = g[(g["filed"] >= eff) & (g["filed"] < nxt)].sort_values("filed")
            if orig.empty or rest.empty:
                continue
            o, n = orig.iloc[0]["val"], rest.iloc[0]["val"]
            per_q[end] = (o, n)
            if abs(o) >= MIN_EPS and n != 0 and (o > 0) == (n > 0):
                ratios.append(o / n)
    # Decide on a log scale between "restated by the split ratio" and "not
    # restated" (ratio 1). Restated EPS is re-rounded to cents, so a 2:1 on
    # $0.59 shows 0.59/0.30 = 1.967: that is rounding, not a contradiction.
    # A 3-5% stock dividend is below cent resolution on small EPS, so one
    # quarter cannot settle it.
    if ratios:
        med = float(pd.Series(ratios).median())
        d_split, d_none = abs(math.log(med / ratio)), abs(math.log(med))
        if abs(med / ratio - 1) < TOL or (d_split < 0.25 * abs(math.log(ratio)) and abs(math.log(ratio)) > 0.2):
            verdict = "CONFIRMED"
        elif abs(math.log(ratio)) <= 0.2 and (len(ratios) < 2 or min(d_split, d_none) > 0.5 * abs(math.log(ratio))):
            verdict = "INCONCLUSIVE"
        elif abs(math.log(ratio)) <= 0.2 and d_split < d_none:
            verdict = "CONFIRMED"
        else:
            verdict = "CONTRADICTED"
    else:
        med, verdict = None, "NO_EVIDENCE"
    # Stored rows for quarters with both an original and a restated value.
    wrong = []
    st = store[store["ticker"] == ticker]
    for r in st.itertuples(index=False):
        q = per_q.get(str(r.quarter_end_date)[:10])
        if q is None or pd.isna(r.eps):
            continue
        o, n = q
        rd = pd.Timestamp(r.earnings_release_date).date()
        if abs(r.eps - o) > 0.006 and abs(r.eps - n) <= 0.006 and rd < eff and abs(o - n) > 0.006:
            wrong.append(f"{r.fiscal_quarter}: stored {r.eps} = restated {n}, filed {o}, released {rd}")
    return {"ticker": ticker, "effective_date": eff, "ratio": str(split["ratio"]), "verdict": verdict,
            "median_orig_over_restated": med, "n_quarters": len(ratios),
            "store_rows_on_wrong_basis": "; ".join(wrong)}


def main():
    store = pd.read_csv(HERE / "scaled_fundamentals.csv")
    rows = []
    tickers = sorted(STOCK_SPLITS)
    for i, t in enumerate(tickers):
        cik = cik_for(t)
        facts = eps_facts(cik) if cik else []
        for s in sorted(STOCK_SPLITS[t], key=lambda s: s["effective_date"]):
            rows.append(check_split(t, s, STOCK_SPLITS[t], facts, store))
        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{len(tickers)} tickers", flush=True)
    out = pd.DataFrame(rows)
    out.to_csv(OUT, index=False)
    print(out["verdict"].value_counts().to_string())
    bad = out[(out["verdict"] == "CONTRADICTED") | (out["store_rows_on_wrong_basis"] != "")]
    if len(bad):
        print("\nPROBLEMS:")
        print(bad.to_string(index=False))
    nev = out[out["verdict"] == "NO_EVIDENCE"]
    if len(nev):
        print(f"\nNO_EVIDENCE ({len(nev)}): " + ", ".join(f"{r.ticker} {r.effective_date}" for r in nev.itertuples()))
    return 1 if len(bad) else 0


if __name__ == "__main__":
    sys.exit(main())
