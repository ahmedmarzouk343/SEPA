"""Replace 10-Q/10-K filing dates with the 8-K Item 2.02 earnings-release date.

A company's numbers become public with its earnings press release (8-K
Item 2.02), usually days to weeks BEFORE the 10-Q/10-K. For every quarter row,
take the LATEST Item 2.02 8-K filed strictly after the quarter end
(>= 7 days), on or before the SEC filing date already stored and at most 60
days before it; its acceptance date (New York time) becomes
earnings_release_date. Latest, not earliest: pre-announcements are Item 2.02
too (WING 2019-01-14 "preliminary sales", 44 days before the full release;
LZB 2019-06-05 "anticipated fiscal 2019 results", 13 days early), and 5.4% of
rows had another 2.02 between the first one and the filing. The results
release is never after the 10-Q/10-K, so the latest 2.02 on or before the
filing is never earlier than it: at worst a few days conservative. No match -> the SEC filing date stays.

Never moves a date LATER. The original date is kept in sec_filing_date and
the choice in release_date_source, so every row is auditable.

The engine still treats a release date as usable from the NEXT day's close
(the 8-K acceptance time is ignored here), so a pre-market release is one
day conservative -- never early.

Input : scaled_fundamentals.csv, ../kashif_data/edgar/events_8k.parquet
Output: scaled_fundamentals.csv (+2 columns) and the parquet store, rewritten.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
EVENTS = HERE.parent / "kashif_data" / "edgar" / "events_8k.parquet"
CSV = HERE / "scaled_fundamentals.csv"
STORE = HERE / "scaled_fundamentals_parquet"
MIN_DAYS_AFTER_END = 7
# The 8-K may precede the stored SEC date by at most this many days (the
# normal press-release -> 10-Q/10-K gap is 0-45 days). A row dated much later
# holds a RESTATED or first-10-Q-after-IPO value; the original press release
# announced a different number, so its date must not be borrowed.
MAX_LEAD_DAYS = 60


def main():
    df = pd.read_csv(CSV)
    if "sec_filing_date" in df.columns:
        base = pd.to_datetime(df["sec_filing_date"])       # idempotent: always start from SEC dates
    else:
        base = pd.to_datetime(df["earnings_release_date"])
    df["sec_filing_date"] = base.dt.strftime("%Y-%m-%d")
    qe = pd.to_datetime(df["quarter_end_date"])

    ev = pd.read_parquet(EVENTS)
    ev = ev[ev["items"].str.split(",").apply(lambda xs: "2.02" in xs)].copy()
    acc = pd.to_datetime(ev["accepted"], utc=True).dt.tz_convert("America/New_York")
    ev["release_day"] = acc.dt.tz_localize(None).dt.normalize()
    by_t = {t: g.sort_values("release_day") for t, g in ev.groupby("ticker")}

    from fundamentals_store import STOCK_SPLITS
    splits = {t: [pd.Timestamp(x["effective_date"]) for x in v] for t, v in STOCK_SPLITS.items()}
    new_dates, sources, accs = [], [], []
    n_split_guard = 0
    for t, e, r in zip(df["ticker"], qe, base):
        g = by_t.get(t)
        hit = None
        if g is not None and pd.notna(r):
            m = g[(g["release_day"] >= e + pd.Timedelta(days=MIN_DAYS_AFTER_END)) & (g["release_day"] <= r)
                  & (g["release_day"] >= r - pd.Timedelta(days=MAX_LEAD_DAYS))]
            if len(m):
                hit = m.iloc[-1]
                # The stored EPS is on the SEC filing's share basis; moving its date
                # back across a split would make adjust_eps_for_splits divide twice.
                if any(hit["release_day"] < sd <= r for sd in splits.get(t, [])):
                    hit = None
                    n_split_guard += 1
        if hit is not None:
            new_dates.append(hit["release_day"])
            sources.append("8-K 2.02")
            accs.append(hit["accession"])
        else:
            new_dates.append(r)
            sources.append("SEC 10-Q/10-K filing")
            accs.append(None)
    df["earnings_release_date"] = pd.to_datetime(new_dates).strftime("%Y-%m-%d")
    df["release_date_source"] = sources
    df["release_8k_accession"] = accs
    moved = (pd.to_datetime(df["earnings_release_date"]) < base)
    assert (pd.to_datetime(df["earnings_release_date"]) <= base).all(), "a date moved LATER"
    lead = (base - pd.to_datetime(df["earnings_release_date"])).dt.days[moved]
    df.to_csv(CSV, index=False)

    cols = ["ticker", "fiscal_quarter", "quarter_end_date", "revenue", "revenue_conf", "net_income",
            "net_income_conf", "eps", "eps_conf", "earnings_release_date", "release_date_conf", "notes",
            "sec_filing_date", "release_date_source"]
    pq_df = df[cols].copy()
    for c in ("quarter_end_date", "earnings_release_date", "sec_filing_date"):
        pq_df[c] = pd.to_datetime(pq_df[c], errors="coerce")
    for c in ("revenue", "net_income", "eps"):
        pq_df[c] = pd.to_numeric(pq_df[c], errors="coerce")
    if STORE.exists():
        shutil.rmtree(STORE)
    pq.write_to_dataset(pa.Table.from_pandas(pq_df, preserve_index=False), root_path=str(STORE),
                        partition_cols=["ticker"])
    print(f"rows {len(df)}; release date moved to the 8-K 2.02 date on {int(moved.sum())} "
          f"({moved.mean():.1%}); median lead {lead.median():.0f} days, max {lead.max():.0f}")
    print(df["release_date_source"].value_counts().to_dict())
    print(f"kept the SEC date because a split fell between the 8-K and the filing: {n_split_guard} rows")


if __name__ == "__main__":
    sys.exit(main())
