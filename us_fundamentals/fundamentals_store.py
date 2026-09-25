"""
Parquet-based fundamentals store with point-in-time, lookahead-bias-safe queries.

Converts the merged fundamentals Excel into a partitioned Parquet dataset
(one partition per ticker) and provides get_known_fundamentals() and
split-adjusted EPS comparison for the backtest engine.

Usage:
    # One-time conversion
    python fundamentals_store.py

    # As a library
    from fundamentals_store import get_known_fundamentals, adjust_eps_for_splits
    row = get_known_fundamentals("AAPL", date(2024, 5, 1))
    adj = adjust_eps_for_splits("TTEK", 1.59, date(2024, 8, 1), date(2025, 1, 1))  # -> ~0.318
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from fractions import Fraction
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

SCRATCHPAD = Path(__file__).resolve().parent

EXCEL_SOURCE = SCRATCHPAD / "merged_fundamentals_v3.xlsx"
PARQUET_ROOT = SCRATCHPAD / "scaled_fundamentals_parquet"

# ── Schema: explicit types so every read is consistent ──────────────
PARQUET_SCHEMA = pa.schema([
    ("ticker",                pa.string()),
    ("fiscal_quarter",        pa.string()),
    ("quarter_end_date",      pa.date32()),
    ("revenue",               pa.float64()),
    ("revenue_conf",          pa.string()),
    ("net_income",            pa.int64()),
    ("net_income_conf",       pa.string()),
    ("eps",                   pa.float64()),
    ("eps_conf",              pa.string()),
    ("earnings_release_date", pa.date32()),
    ("release_date_conf",     pa.string()),
    ("notes",                 pa.string()),
    ("stale_gap_quarter",     pa.bool_()),
])

STALE_GAP_DAYS = 120

# ═══════════════════════════════════════════════════════════════════════
#  Stock split events — verified from SEC EDGAR 8-K filings + XBRL data
# ═══════════════════════════════════════════════════════════════════════
# Each entry: effective_date (when the split takes effect / shares are
# distributed), ratio = NEW shares per OLD share as an exact Fraction
# (5-for-1 -> 5; 1-for-4 reverse -> Fraction(1, 4)), and the SEC filing
# accession for the audit trail (an 8-K unless "filing" says otherwise).
#
# The adjustment uses earnings_release_date (not quarter_end_date) as the
# reference because that determines the EPS basis: a 10-Q filed AFTER a split
# reports post-split EPS even if the quarter ended before the split.
#
# Rejected scanner candidates (share-count steps that are NOT splits):
# AAMI 2021 tender offer (SC TO-I/A 0001104659-21-147893), CHRD 2022 Oasis-
# Whiting merger (8-K 0001193125-22-189506), BBT 2025 Berkshire-Brookline
# reverse acquisition (8-K 0001108134-25-000017), RBA 2023 IAA acquisition
# (8-K 0001104659-23-034673), CRGY 2023 OpCo unit conversion + offering
# (10-Q 0001866175-23-000073), PNFP 2026 Pinnacle-Synovus holding-company
# merger (8-K 0001115055-26-000002), SM 2026 Civitas merger (8-K
# 0001104659-26-008380), COKE 2025 buyback of Coca-Cola Co.'s stake
# (8-K 0001628280-25-050682; the 2025 10-for-1 split below is real).
F = Fraction
STOCK_SPLITS: dict[str, list[dict]] = {
    "TTEK":  [{"effective_date": date(2024, 9, 6),  "ratio": F(5),
               "sec_8k": "0001104659-24-097783"}],
    "NVDA":  [{"effective_date": date(2021, 7, 19), "ratio": F(4),
               "sec_8k": "0001045810-21-000056"},
              {"effective_date": date(2024, 6, 7),  "ratio": F(10),
               "sec_8k": "0001045810-24-000206"}],
    "GOOGL": [{"effective_date": date(2022, 7, 15), "ratio": F(20),
               "sec_8k": "0001193125-22-167375"}],
    "WMT":   [{"effective_date": date(2024, 2, 23), "ratio": F(3),
               "sec_8k": "0000104169-24-000004"}],
    "AMZN":  [{"effective_date": date(2022, 6, 6),  "ratio": F(20),
               "sec_8k": "0001104659-22-065872"}],
    # Added 2026-09-24, each confirmed from the filing text.
    "ACMR":  [{"effective_date": date(2022, 3, 23), "ratio": F(3),
               "sec_8k": "0001140361-22-007685"}],
    "NLY":   [{"effective_date": date(2022, 9, 23), "ratio": F(1, 4),
               "sec_8k": "0001193125-22-250257"}],
    "EXLS":  [{"effective_date": date(2023, 8, 1),  "ratio": F(5),
               "sec_8k": "0001193125-23-200662"}],
    "MLI":   [{"effective_date": date(2023, 10, 20), "ratio": F(2),
               "sec_8k": "0000089439-23-000066"}],
    "CELH":  [{"effective_date": date(2023, 11, 13), "ratio": F(3),
               "sec_8k": "0001341766-23-000030"}],
    "HUBG":  [{"effective_date": date(2024, 1, 26), "ratio": F(2),
               "sec_8k": "0000950170-24-021432", "filing": "10-K (no 8-K filed)"}],
    "PANW":  [{"effective_date": date(2024, 12, 13), "ratio": F(2),
               "sec_8k": "0001193125-24-277082"}],
    "CRVL":  [{"effective_date": date(2024, 12, 24), "ratio": F(3),
               "sec_8k": "0001193125-24-285219"}],
    "MTH":   [{"effective_date": date(2025, 1, 2),  "ratio": F(2),
               "sec_8k": "0000833079-25-000021", "filing": "10-K (no 8-K filed)"}],
    "RLI":   [{"effective_date": date(2025, 1, 15), "ratio": F(2),
               "sec_8k": "0000084246-24-000028"}],
    "LXP":   [{"effective_date": date(2025, 11, 10), "ratio": F(1, 5),
               "sec_8k": "0000910108-25-000074"}],
    # Found by the re-run scanner on the final data (incl. class-level EPS).
    "NSSC":  [{"effective_date": date(2022, 1, 4),  "ratio": F(2),
               "sec_8k": "0001558370-21-016588"}],
    "GME":   [{"effective_date": date(2022, 7, 21), "ratio": F(4),
               "sec_8k": "0001326380-22-000100"}],
    "CHDN":  [{"effective_date": date(2023, 5, 19), "ratio": F(2),
               "sec_8k": "0000020212-23-000078"}],
    "USLM":  [{"effective_date": date(2024, 7, 12), "ratio": F(5),
               "sec_8k": "0001558370-24-006804"}],
    "SMCI":  [{"effective_date": date(2024, 9, 30), "ratio": F(10),
               "sec_8k": "0001375365-24-000035"}],
    "COKE":  [{"effective_date": date(2025, 5, 23), "ratio": F(10),
               "sec_8k": "0000317540-25-000062"}],
    "PIPR":  [{"effective_date": date(2026, 3, 23), "ratio": F(4),
               "sec_8k": "0001104659-26-033351"}],
    "POWL":  [{"effective_date": date(2026, 4, 1),  "ratio": F(3),
               "sec_8k": "0000080420-26-000054"}],
}


def get_split_events(ticker: str) -> list[dict]:
    """Return split events for a ticker, sorted by date."""
    return sorted(STOCK_SPLITS.get(ticker, []), key=lambda s: s["effective_date"])


def _split_factor(ticker: str, from_date: date, to_date: date) -> Fraction:
    factor = Fraction(1)
    for split in STOCK_SPLITS.get(ticker, []):
        eff = split["effective_date"]
        if from_date < eff <= to_date:
            factor *= split["ratio"]
        elif to_date < eff <= from_date:
            factor /= split["ratio"]
    return factor


def get_cumulative_split_factor(ticker: str, from_date: date, to_date: date) -> float:
    """Cumulative split factor between two dates (new shares per old share).

    A 5:1 split between from_date and to_date returns 5.0; a 1-for-4
    reverse split returns 0.25. No splits returns 1.0.
    """
    return float(_split_factor(ticker, from_date, to_date))


def adjust_eps_for_splits(ticker: str,
                          eps: float | None,
                          earnings_release_date: date,
                          as_of_date: date) -> float | None:
    """Adjust as-filed EPS to be comparable at as_of_date.

    Divides pre-split EPS by the cumulative split factor so it is
    comparable with post-split quarters.

    as_of_date is REQUIRED — no default to today(), because in a backtest
    "today" is the simulated date, not the real calendar date. Defaulting
    to date.today() would leak future split knowledge into historical
    comparisons.

    Args:
        ticker: Stock ticker
        eps: As-filed EPS value (None passes through)
        earnings_release_date: When the earnings were publicly released
        as_of_date: The simulated "now" — only splits known by this date apply

    Returns:
        Split-adjusted EPS, or None if eps is None
    """
    if eps is None:
        return None
    # Exact arithmetic: a 1-for-5 reverse split must multiply by exactly 5,
    # and 1/5 has no exact float.
    factor = _split_factor(ticker, earnings_release_date, as_of_date)
    return float(Fraction(eps) / factor) if factor != 1 else eps


# ═══════════════════════════════════════════════════════════════════════
#  STEP 1 -- Convert Excel -> Partitioned Parquet
# ═══════════════════════════════════════════════════════════════════════

def excel_to_parquet(excel_path: Path = EXCEL_SOURCE,
                     parquet_root: Path = PARQUET_ROOT) -> pd.DataFrame:
    """Read merged Excel, write partitioned Parquet, return the DataFrame."""
    df = pd.read_excel(excel_path, sheet_name="merged_data")
    src_rows = len(df)
    src_tickers = df["ticker"].nunique()

    # Parse date columns into proper date objects
    df["quarter_end_date"] = pd.to_datetime(df["quarter_end_date"]).dt.date
    df["earnings_release_date"] = pd.to_datetime(df["earnings_release_date"]).dt.date

    # Fill NaN strings with None for clean Parquet nulls
    str_cols = ["revenue_conf", "net_income_conf", "eps_conf",
                "release_date_conf", "notes"]
    for c in str_cols:
        df[c] = df[c].where(df[c].notna(), None)

    # Flag rows where the NEXT quarter's release is >120 days away.
    # During that gap the backtest serves this row's data, which is stale.
    df["stale_gap_quarter"] = False
    for ticker in df["ticker"].unique():
        mask = df["ticker"] == ticker
        tdf = df.loc[mask].sort_values(["earnings_release_date", "quarter_end_date"])
        idxs = tdf.index.tolist()
        for j in range(len(idxs) - 1):
            gap = (tdf.loc[idxs[j + 1], "earnings_release_date"]
                   - tdf.loc[idxs[j], "earnings_release_date"]).days
            if gap > STALE_GAP_DAYS:
                df.loc[idxs[j], "stale_gap_quarter"] = True

    table = pa.Table.from_pandas(df, schema=PARQUET_SCHEMA, preserve_index=False)

    # Write partitioned by ticker -- each ticker gets its own directory
    pq.write_to_dataset(
        table,
        root_path=str(parquet_root),
        partition_cols=["ticker"],
        existing_data_behavior="delete_matching",
    )

    # Verify round-trip
    rt = pq.read_table(str(parquet_root)).to_pandas()
    assert len(rt) == src_rows, f"Row count mismatch: {src_rows} -> {len(rt)}"
    assert rt["ticker"].nunique() == src_tickers, "Ticker count mismatch"

    stale_count = int(df["stale_gap_quarter"].sum())
    stale_tickers = df.loc[df["stale_gap_quarter"], "ticker"].nunique()
    print(f"  Excel -> Parquet: {src_rows} rows, {src_tickers} tickers")
    print(f"  stale_gap_quarter=True: {stale_count} rows across {stale_tickers} tickers")
    print(f"  Partitioned at: {parquet_root}")
    return df


# ═══════════════════════════════════════════════════════════════════════
#  STEP 2 -- Point-in-time query function
# ═══════════════════════════════════════════════════════════════════════

# Per-ticker cache: loaded on first access, stays in memory for the run.
_ticker_cache: dict[str, pd.DataFrame] = {}


def _load_ticker(ticker: str, parquet_root: Path = PARQUET_ROOT) -> pd.DataFrame:
    """Load one ticker's partition into a DataFrame sorted by release date."""
    if ticker in _ticker_cache:
        return _ticker_cache[ticker]

    part_dir = parquet_root / f"ticker={ticker}"
    if not part_dir.exists():
        _ticker_cache[ticker] = pd.DataFrame()
        return _ticker_cache[ticker]

    df = pq.read_table(str(part_dir)).to_pandas()
    df["ticker"] = ticker  # partition column stripped by pyarrow
    df["quarter_end_date"] = pd.to_datetime(df["quarter_end_date"]).dt.date
    df["earnings_release_date"] = pd.to_datetime(df["earnings_release_date"]).dt.date
    df.sort_values(["earnings_release_date", "quarter_end_date"], inplace=True)
    df.reset_index(drop=True, inplace=True)
    _ticker_cache[ticker] = df
    return df


def get_known_fundamentals(ticker: str,
                           as_of_date: date,
                           parquet_root: Path = PARQUET_ROOT) -> dict | None:
    """Return the most recent quarter whose earnings were public by as_of_date.

    This is the ONLY safe way for the backtest engine to look up fundamentals.
    It gates on earnings_release_date (when numbers became public), never on
    quarter_end_date (when the accounting period ended).

    Returns None if no quarter has been released yet as of as_of_date.
    """
    df = _load_ticker(ticker, parquet_root)
    if df.empty:
        return None

    # Filter to quarters whose earnings were released on or before as_of_date
    known = df[df["earnings_release_date"] <= as_of_date]
    if known.empty:
        return None

    # Most recent release
    latest = known.iloc[-1]
    return latest.to_dict()


# ═══════════════════════════════════════════════════════════════════════
#  STEP 3 -- Point-in-time validation with real test cases
# ═══════════════════════════════════════════════════════════════════════

def validate_point_in_time(parquet_root: Path = PARQUET_ROOT):
    """Test that get_known_fundamentals() never leaks future data."""
    print("\n" + "=" * 64)
    print("  POINT-IN-TIME VALIDATION")
    print("=" * 64)

    # Load raw data to find real release dates
    full = pq.read_table(str(parquet_root)).to_pandas()
    full["earnings_release_date"] = pd.to_datetime(full["earnings_release_date"]).dt.date
    full["quarter_end_date"] = pd.to_datetime(full["quarter_end_date"]).dt.date

    all_pass = True

    def run_case(ticker: str, as_of: date, expect_quarter: str, label: str):
        nonlocal all_pass
        result = get_known_fundamentals(ticker, as_of, parquet_root)

        # Show the two adjacent release dates for context
        tdf = full[full["ticker"] == ticker].sort_values("earnings_release_date")
        releases = list(zip(tdf["fiscal_quarter"], tdf["earnings_release_date"]))

        if result is None:
            got_q = "None"
            ok = expect_quarter == "None"
        else:
            got_q = result["fiscal_quarter"]
            ok = got_q == expect_quarter

        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False

        print(f"\n  {label}")
        print(f"    Ticker: {ticker}  |  as_of_date: {as_of}")

        # Find the bracket
        prev_rel = None
        next_rel = None
        for fq, rd in releases:
            if rd <= as_of:
                prev_rel = (fq, rd)
            elif next_rel is None:
                next_rel = (fq, rd)

        if prev_rel:
            print(f"    Last released:  {prev_rel[0]} on {prev_rel[1]}")
        if next_rel:
            print(f"    Next upcoming:  {next_rel[0]} on {next_rel[1]} (must NOT be returned)")
        print(f"    Returned:       {got_q}")
        print(f"    Expected:       {expect_quarter}  ->  {status}")

    # ── BURL: fiscal year ends early February ──
    # Find BURL's actual release dates to pick good test points
    burl = full[full["ticker"] == "BURL"].sort_values("earnings_release_date")
    burl_releases = list(zip(burl["fiscal_quarter"], burl["earnings_release_date"]))
    if len(burl_releases) >= 2:
        q_earlier = burl_releases[-2]
        q_later = burl_releases[-1]
        # Query date between the two release dates: should get earlier quarter
        mid_date = q_earlier[1] + (q_later[1] - q_earlier[1]) // 2
        run_case("BURL", mid_date, q_earlier[0],
                 f"BURL: between {q_earlier[0]} release and {q_later[0]} release")
        # Day OF later release: should get the later quarter
        run_case("BURL", q_later[1], q_later[0],
                 f"BURL: on {q_later[0]} release date itself")

    # ── TTEK: fiscal year ends late September ──
    ttek = full[full["ticker"] == "TTEK"].sort_values("earnings_release_date")
    ttek_releases = list(zip(ttek["fiscal_quarter"], ttek["earnings_release_date"]))
    if len(ttek_releases) >= 2:
        q_earlier = ttek_releases[-2]
        q_later = ttek_releases[-1]
        mid_date = q_earlier[1] + (q_later[1] - q_earlier[1]) // 2
        run_case("TTEK", mid_date, q_earlier[0],
                 f"TTEK: between {q_earlier[0]} release and {q_later[0]} release")

    # ── CRM: Q4 FY2025 -- the one we just fixed ──
    crm = full[full["ticker"] == "CRM"].sort_values("earnings_release_date")
    crm_releases = list(zip(crm["fiscal_quarter"], crm["earnings_release_date"],
                            crm["quarter_end_date"]))
    # Find Q4 FY2025 and the quarter before it
    crm_q4_25 = [(fq, rd, qed) for fq, rd, qed in crm_releases if fq == "Q4 2025"]
    crm_q3_25 = [(fq, rd, qed) for fq, rd, qed in crm_releases if fq == "Q3 2025"]
    if crm_q4_25 and crm_q3_25:
        q3_rel = crm_q3_25[0][1]
        q4_rel = crm_q4_25[0][1]
        q4_qed = crm_q4_25[0][2]
        # Key test: as_of = Q4 quarter_end_date (2025-01-31), which is BEFORE
        # Q4 earnings release. Must return Q3, NOT Q4.
        run_case("CRM", q4_qed, "Q3 2025",
                 "CRM: on Q4 FY2025 quarter_end_date (before earnings release)")
        # After Q4 release: should return Q4
        run_case("CRM", q4_rel, "Q4 2025",
                 "CRM: on Q4 FY2025 earnings_release_date")

    # ── Edge case: before any data exists ──
    run_case("BURL", date(2018, 1, 1), "None",
             "BURL: before any earnings release in dataset")

    # ── Edge case: nonexistent ticker ──
    result = get_known_fundamentals("ZZZZZ", date(2025, 1, 1), parquet_root)
    status = "PASS" if result is None else "FAIL"
    if result is not None:
        all_pass = False
    print(f"\n  Nonexistent ticker 'ZZZZZ': returned {'None' if result is None else result}  ->  {status}")

    return all_pass


# ═══════════════════════════════════════════════════════════════════════
#  STEP 4 -- Sanity checks on converted data
# ═══════════════════════════════════════════════════════════════════════

def sanity_checks(excel_df: pd.DataFrame, parquet_root: Path = PARQUET_ROOT):
    """Verify the Parquet data matches the source Excel exactly."""
    print("\n" + "=" * 64)
    print("  SANITY CHECKS -- PARQUET vs EXCEL")
    print("=" * 64)

    pq_df = pq.read_table(str(parquet_root)).to_pandas()
    pq_df["quarter_end_date"] = pd.to_datetime(pq_df["quarter_end_date"]).dt.date
    pq_df["earnings_release_date"] = pd.to_datetime(pq_df["earnings_release_date"]).dt.date

    all_pass = True

    # 1. Row count
    xl_rows = len(excel_df)
    pq_rows = len(pq_df)
    ok = xl_rows == pq_rows
    if not ok: all_pass = False
    print(f"\n  Row count:  Excel={xl_rows}  Parquet={pq_rows}  {'PASS' if ok else 'FAIL'}")

    # 2. Ticker count and no empty partitions
    xl_tickers = set(excel_df["ticker"].unique())
    pq_tickers = set(pq_df["ticker"].unique())
    ok = xl_tickers == pq_tickers
    if not ok: all_pass = False
    print(f"  Ticker set match:  {'PASS' if ok else 'FAIL'}")
    if xl_tickers != pq_tickers:
        print(f"    Missing in Parquet: {xl_tickers - pq_tickers}")
        print(f"    Extra in Parquet:   {pq_tickers - xl_tickers}")

    empty = [t for t in pq_tickers if len(pq_df[pq_df["ticker"] == t]) == 0]
    ok = len(empty) == 0
    if not ok: all_pass = False
    print(f"  No empty partitions: {'PASS' if ok else 'FAIL'}")
    if empty:
        print(f"    Empty: {empty}")

    # 3. Duplicate NI scan (3+ consecutive identical values per ticker)
    print(f"\n  Duplicate NI scan (3+ consecutive identical):")
    dup_count = 0
    for t in sorted(pq_tickers):
        tdf = pq_df[pq_df["ticker"] == t].sort_values("quarter_end_date")
        nis = tdf["net_income"].tolist()
        for i in range(len(nis) - 2):
            if nis[i] == nis[i+1] == nis[i+2] and pd.notna(nis[i]):
                print(f"    {t}: 3 consecutive NI={nis[i]:,.0f} starting at index {i}")
                dup_count += 1
    ok = dup_count == 0
    if not ok: all_pass = False
    print(f"    {'Zero flagged -- PASS' if ok else f'{dup_count} flagged -- FAIL'}")

    # 4. Checkpoint values against Parquet data
    print(f"\n  5 checkpoint values (from Parquet):")
    checks = [
        ("BURL", "Q4 2022", "net_income",  185_200_000),
        ("BURL", "Q4 2023", "net_income",  227_458_000),
        ("TTEK", "Q3 2024", "eps",         1.59),
        ("TTEK", "Q4 2024", "eps",         0.35),
        ("CRM",  "Q4 2025", "net_income",  1_708_000_000),
    ]
    for ticker, fq, field, expected in checks:
        row = pq_df[(pq_df["ticker"] == ticker) & (pq_df["fiscal_quarter"] == fq)]
        if row.empty:
            print(f"    {ticker} {fq} {field}: NOT FOUND -- FAIL")
            all_pass = False
            continue
        actual = row.iloc[0][field]
        if field == "eps":
            ok = abs(actual - expected) < 0.02
        else:
            ok = actual == expected
        status = "OK" if ok else f"MISMATCH (actual={actual})"
        if not ok: all_pass = False
        print(f"    {ticker} {fq} {field}: expected={expected:>15,}  actual={actual:>15,}  {status}")

    # 5. Value comparison: spot-check numeric columns match
    print(f"\n  Numeric value integrity (Excel vs Parquet):")
    merge_key = ["ticker", "fiscal_quarter"]
    xl_sorted = excel_df.sort_values(merge_key).reset_index(drop=True)
    pq_sorted = pq_df.sort_values(merge_key).reset_index(drop=True)

    for col in ["revenue", "net_income", "eps"]:
        xl_vals = xl_sorted[col].values
        pq_vals = pq_sorted[col].values
        # Handle NaN comparison
        match = ((xl_vals == pq_vals) | (pd.isna(xl_vals) & pd.isna(pq_vals))).all()
        ok = bool(match)
        if not ok: all_pass = False
        print(f"    {col:15s}: {'MATCH' if ok else 'MISMATCH'}")

    return all_pass


# ═══════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 64)
    print("  Fundamentals Store -- Excel -> Parquet + Point-in-Time Queries")
    print("=" * 64)

    print("\n--- Step 1: Convert Excel -> Partitioned Parquet ---")
    print(f"  Source: {EXCEL_SOURCE}")
    print(f"  Using pyarrow {pa.__version__} (native partitioned write,")
    print(f"  no DuckDB dependency -- simpler, and pyarrow is already")
    print(f"  required for Parquet reads at query time)")
    df = excel_to_parquet()

    print("\n--- Step 2: get_known_fundamentals() ready ---")
    print("  Signature: get_known_fundamentals(ticker, as_of_date) -> dict | None")
    print("  Gates on earnings_release_date, never quarter_end_date")

    print("\n--- Step 3: Point-in-time validation ---")
    pit_pass = validate_point_in_time()

    print("\n--- Step 4: Sanity checks ---")
    sc_pass = sanity_checks(df)

    print("\n" + "=" * 64)
    overall = "ALL PASS" if (pit_pass and sc_pass) else "FAILURES DETECTED"
    print(f"  OVERALL: {overall}")
    print("=" * 64)
