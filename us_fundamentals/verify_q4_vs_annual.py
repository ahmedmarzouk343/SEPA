"""Q4 consistency against the company's own annual EPS.

Q4 is derived (FY - Q1..Q3), so for every derived Q4 in the store:

    stored Q1 + Q2 + Q3 + Q4 EPS  ~=  the 10-K's first-filed annual diluted EPS

Not exact -- quarterly share counts differ from the annual one -- so the
check flags only gaps beyond max(5 cents, 5% of |FY EPS|). Years with a split
inside them are skipped: the stored Q1-Q3 are as filed on the old basis.

    python verify_q4_vs_annual.py [--from 2014-01-01] [--tickers A,B]
Writes q4_vs_annual.csv; prints the flagged rows.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fundamentals_store import STOCK_SPLITS  # noqa: E402
from merged_pipeline import SEC_UA, cik_for  # noqa: E402

TAGS = ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic")


def annual_eps(cik):
    r = requests.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
                     headers={"User-Agent": SEC_UA}, timeout=30)
    time.sleep(0.2)
    if r.status_code != 200:
        return {}
    gaap = r.json().get("facts", {}).get("us-gaap", {})
    for tag in TAGS:
        rows = gaap.get(tag, {}).get("units", {}).get("USD/shares", [])
        out = {}
        for x in sorted(rows, key=lambda x: x["filed"]):
            if not x.get("start") or not x["form"].startswith("10-K"):
                continue
            days = (datetime.strptime(x["end"], "%Y-%m-%d") - datetime.strptime(x["start"], "%Y-%m-%d")).days
            if days >= 300:
                out.setdefault(x["end"], x["val"])        # first filed
        if out:
            return out
    return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default="2014-01-01")
    ap.add_argument("--tickers", default="")
    a = ap.parse_args()
    st = pd.read_csv(HERE / "scaled_fundamentals.csv")
    st = st[st["quarter_end_date"] >= a.start]
    q4 = st[st["fiscal_quarter"].astype(str).str.startswith("Q4") & st["eps"].notna()]
    if a.tickers:
        q4 = q4[q4["ticker"].isin(a.tickers.split(","))]
    rows = []
    for t, g in q4.groupby("ticker"):
        cik = cik_for(t)
        fy = annual_eps(cik) if cik else {}
        tst = st[st["ticker"] == t].sort_values("quarter_end_date")
        for r in g.itertuples():
            if r.quarter_end_date not in fy:
                continue
            end = pd.Timestamp(r.quarter_end_date)
            prior = tst[(pd.to_datetime(tst["quarter_end_date"]) < end)
                        & (pd.to_datetime(tst["quarter_end_date"]) > end - pd.Timedelta(days=330))]
            if len(prior) != 3 or prior["eps"].isna().any():
                continue
            if any(end - pd.Timedelta(days=365) < pd.Timestamp(s["effective_date"]) <= end
                   for s in STOCK_SPLITS.get(t, [])):
                continue
            total = float(prior["eps"].sum() + r.eps)
            gap = abs(total - fy[r.quarter_end_date])
            rows.append({"ticker": t, "quarter_end_date": r.quarter_end_date, "q4_eps": r.eps,
                         "sum_4q": round(total, 4), "fy_eps": fy[r.quarter_end_date], "gap": round(gap, 4),
                         "flag": gap > max(0.05, 0.05 * abs(fy[r.quarter_end_date]))})
    out = pd.DataFrame(rows)
    out.to_csv(HERE / "q4_vs_annual.csv", index=False)
    if out.empty:
        print("nothing checkable")
        return 0
    print(f"{len(out)} Q4 rows checked; flagged {int(out['flag'].sum())} ({out['flag'].mean():.1%})")
    print(out[out["flag"]].sort_values("gap", ascending=False).head(40).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
