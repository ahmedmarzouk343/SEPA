"""
Full verification suite for the scaled fundamentals dataset.

Checks:
1. Missing data % (target ≤1%)
2. Duplicate net_income scan (repeated values within same ticker)
3. Invalid quarter label scan (anything other than Q1-Q4)
4. Mid-series gap scan (>120 days between consecutive quarters)
5. Fiscal-year-end month coverage
6. Per-ticker failure listing (no averaging away)
7. Confidence distribution
"""
import sys, os, json
from datetime import date, datetime
from pathlib import Path
from collections import Counter

import pandas as pd

SCRATCHPAD = Path(__file__).resolve().parent
CSV_PATH = SCRATCHPAD / "scaled_fundamentals.csv"
REPORT_PATH = SCRATCHPAD / "verification_report.txt"

FIELDS = ["revenue", "net_income", "eps", "earnings_release_date"]


def load_data():
    df = pd.read_csv(CSV_PATH)
    df["quarter_end_date"] = pd.to_datetime(df["quarter_end_date"]).dt.date
    df["earnings_release_date"] = pd.to_datetime(
        df["earnings_release_date"], errors="coerce").dt.date
    return df


def check_missing_data(df, out):
    out.append("=" * 80)
    out.append("  CHECK 1: MISSING DATA")
    out.append("=" * 80)

    total_pts = len(df) * len(FIELDS)
    missing = 0
    missing_by_field = {}
    missing_detail = []

    for f in FIELDS:
        miss_f = df[f].isna().sum()
        if f == "earnings_release_date":
            miss_f += (df[f].astype(str) == "").sum()
        missing_by_field[f] = int(miss_f)
        missing += miss_f

    pct = missing / total_pts * 100 if total_pts else 0
    out.append(f"  Total data points: {total_pts} ({len(df)} rows x {len(FIELDS)} fields)")
    out.append(f"  Missing:           {missing} ({pct:.2f}%)")
    out.append(f"  Target:            <=1.00%  {'PASS' if pct <= 1.0 else 'FAIL'}")
    out.append("")

    for f in FIELDS:
        out.append(f"    {f:<25} missing={missing_by_field[f]}")

    # Per-ticker missing count
    out.append("")
    ticker_missing = {}
    for ticker in df["ticker"].unique():
        tdf = df[df["ticker"] == ticker]
        tmiss = 0
        for f in FIELDS:
            tmiss += tdf[f].isna().sum()
            if f == "earnings_release_date":
                tmiss += (tdf[f].astype(str) == "").sum()
        if tmiss > 0:
            ticker_missing[ticker] = tmiss

    if ticker_missing:
        out.append(f"  Tickers with missing data ({len(ticker_missing)}):")
        for tk, cnt in sorted(ticker_missing.items(),
                              key=lambda x: -x[1])[:50]:
            out.append(f"    {tk:<8} {cnt} missing fields")
        if len(ticker_missing) > 50:
            out.append(f"    ... and {len(ticker_missing)-50} more")

    return pct, missing, ticker_missing


def check_duplicate_ni(df, out):
    out.append("")
    out.append("=" * 80)
    out.append("  CHECK 2: DUPLICATE NET INCOME SCAN")
    out.append("=" * 80)

    flagged = []
    for ticker in sorted(df["ticker"].unique()):
        tdf = df[df["ticker"] == ticker].sort_values("quarter_end_date")
        ni_vals = [(str(r["quarter_end_date"]), r["net_income"])
                   for _, r in tdf.iterrows()
                   if pd.notna(r["net_income"])]
        for i in range(len(ni_vals) - 2):
            d1, v1 = ni_vals[i]
            d2, v2 = ni_vals[i + 1]
            d3, v3 = ni_vals[i + 2]
            if v1 == v2 == v3 and v1 != 0:
                flagged.append(
                    f"{ticker}: NI={v1:,.0f} repeated at {d1}, {d2}, {d3}")

    if flagged:
        for f in flagged:
            out.append(f"  FLAGGED: {f}")
        out.append(f"  {len(flagged)} issues — FAIL")
    else:
        out.append("  Zero flagged — PASS")

    return flagged


def check_invalid_quarters(df, out):
    out.append("")
    out.append("=" * 80)
    out.append("  CHECK 3: INVALID QUARTER LABELS")
    out.append("=" * 80)

    valid_pattern = {"Q1", "Q2", "Q3", "Q4"}
    invalid = []
    for _, r in df.iterrows():
        fq = str(r.get("fiscal_quarter", ""))
        q_part = fq.split()[0] if fq else ""
        if q_part not in valid_pattern:
            invalid.append(
                f"{r['ticker']} {r['quarter_end_date']}: '{fq}'")

    if invalid:
        out.append(f"  {len(invalid)} invalid quarter labels:")
        for item in invalid[:30]:
            out.append(f"    {item}")
        if len(invalid) > 30:
            out.append(f"    ... and {len(invalid)-30} more")
        out.append("  FAIL")
    else:
        out.append("  All quarter labels valid — PASS")

    return invalid


def check_gaps(df, out):
    out.append("")
    out.append("=" * 80)
    out.append("  CHECK 4: MID-SERIES GAP SCAN (>120 days)")
    out.append("=" * 80)

    gap_tickers = {}
    for ticker in sorted(df["ticker"].unique()):
        tdf = df[df["ticker"] == ticker].sort_values("quarter_end_date")
        qeds = tdf["quarter_end_date"].tolist()
        gaps = []
        for i in range(1, len(qeds)):
            gap_days = (qeds[i] - qeds[i - 1]).days
            if gap_days > 120:
                fq_prev = tdf.iloc[i - 1]["fiscal_quarter"]
                fq_next = tdf.iloc[i]["fiscal_quarter"]
                gaps.append(
                    f"{fq_prev} -> {fq_next} ({gap_days}d, "
                    f"{qeds[i-1]} to {qeds[i]})")
        if gaps:
            gap_tickers[ticker] = gaps

    if gap_tickers:
        out.append(f"  {len(gap_tickers)} tickers with gaps:")
        for tk, gaps in sorted(gap_tickers.items()):
            for g in gaps:
                out.append(f"    {tk:<8} {g}")
    else:
        out.append("  No mid-series gaps — PASS")

    return gap_tickers


def check_fy_months(df, out):
    out.append("")
    out.append("=" * 80)
    out.append("  CHECK 5: FISCAL-YEAR-END MONTH COVERAGE")
    out.append("=" * 80)

    fy_months = {}
    for ticker in df["ticker"].unique():
        tdf = df[df["ticker"] == ticker].sort_values("quarter_end_date")
        fqs = tdf["fiscal_quarter"].tolist()
        qeds = tdf["quarter_end_date"].tolist()
        for fq, qed in zip(fqs, qeds):
            if str(fq).startswith("Q4"):
                month = qed.month if hasattr(qed, "month") else None
                if month:
                    fy_months.setdefault(month, set()).add(ticker)

    out.append(f"  FY-end months represented:")
    month_names = {
        1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
        7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"
    }
    for m in sorted(fy_months.keys()):
        tickers = sorted(fy_months[m])
        out.append(
            f"    {month_names.get(m, '?'):>3} (month {m:>2}): "
            f"{len(tickers)} tickers"
            f"  e.g. {', '.join(tickers[:5])}"
            f"{'...' if len(tickers) > 5 else ''}")

    all_12 = len(fy_months) == 12
    out.append(f"\n  All 12 months covered: {'YES — PASS' if all_12 else 'NO — check missing months'}")

    return fy_months


def check_confidence(df, out):
    out.append("")
    out.append("=" * 80)
    out.append("  CHECK 6: CONFIDENCE DISTRIBUTION")
    out.append("=" * 80)

    conf_fields = ["revenue_conf", "net_income_conf", "eps_conf",
                   "release_date_conf"]
    total = 0
    counts = Counter()
    for cf in conf_fields:
        if cf in df.columns:
            counts.update(df[cf].value_counts().to_dict())
            total += len(df)

    for level in ["HIGH_CONFIDENCE", "RECONCILED", "SINGLE_SOURCE",
                  "NEEDS_MANUAL_REVIEW"]:
        cnt = counts.get(level, 0)
        pct = cnt / total * 100 if total else 0
        out.append(f"  {level:<25} {cnt:>6}  ({pct:5.1f}%)")

    return dict(counts)


def check_quarter_count(df, out):
    out.append("")
    out.append("=" * 80)
    out.append("  CHECK 7: PER-TICKER QUARTER COUNT")
    out.append("=" * 80)

    counts = df.groupby("ticker").size()
    out.append(f"  Median quarters per ticker: {counts.median():.0f}")
    out.append(f"  Mean quarters per ticker:   {counts.mean():.1f}")
    out.append(f"  Min:  {counts.min()} ({counts.idxmin()})")
    out.append(f"  Max:  {counts.max()} ({counts.idxmax()})")

    short = counts[counts < 10]
    if len(short) > 0:
        out.append(f"\n  Tickers with <10 quarters ({len(short)}):")
        for tk, cnt in short.sort_values().items():
            out.append(f"    {tk:<8} {cnt} quarters")

    return counts


def run_verification():
    print("Loading data...")
    df = load_data()
    print(f"  {len(df)} rows, {df['ticker'].nunique()} tickers\n")

    out = []
    out.append("=" * 80)
    out.append("  SCALED FUNDAMENTALS VERIFICATION REPORT")
    out.append(f"  Generated: {datetime.now().isoformat()}")
    out.append(f"  Dataset: {len(df)} rows, {df['ticker'].nunique()} tickers")
    out.append("=" * 80)

    missing_pct, _, ticker_missing = check_missing_data(df, out)
    dup_flags = check_duplicate_ni(df, out)
    invalid_labels = check_invalid_quarters(df, out)
    gap_tickers = check_gaps(df, out)
    fy_months = check_fy_months(df, out)
    conf_dist = check_confidence(df, out)
    q_counts = check_quarter_count(df, out)

    # Summary
    out.append("")
    out.append("=" * 80)
    out.append("  VERIFICATION SUMMARY")
    out.append("=" * 80)
    checks = [
        ("Missing data <=1%", missing_pct <= 1.0),
        ("No duplicate NI", len(dup_flags) == 0),
        ("Valid quarter labels", len(invalid_labels) == 0),
        ("No unexplained gaps", len(gap_tickers) == 0),
    ]
    for label, passed in checks:
        out.append(f"  {'PASS' if passed else 'FAIL'}  {label}")

    # Tickers needing human review
    needs_review = set()
    for tk in ticker_missing:
        if ticker_missing[tk] > 2:
            needs_review.add(tk)
    for tk in gap_tickers:
        needs_review.add(tk)
    for flag in dup_flags:
        tk = flag.split(":")[0].strip()
        needs_review.add(tk)

    if needs_review:
        out.append(f"\n  TICKERS RECOMMENDED FOR HUMAN REVIEW ({len(needs_review)}):")
        for tk in sorted(needs_review):
            reasons = []
            if tk in ticker_missing and ticker_missing[tk] > 2:
                reasons.append(f"missing={ticker_missing[tk]}")
            if tk in gap_tickers:
                reasons.append(f"gaps={len(gap_tickers[tk])}")
            if any(tk in f for f in dup_flags):
                reasons.append("dup_NI")
            out.append(f"    {tk:<8} {', '.join(reasons)}")

    report = "\n".join(out)
    print(report)

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\nReport saved: {REPORT_PATH}")


if __name__ == "__main__":
    run_verification()
