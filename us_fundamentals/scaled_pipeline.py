"""
Scaled fundamentals pipeline — ~1,000 tickers (S&P 400 + S&P 600).

Reuses the battle-tested SEC extraction, Q4 derivation, and reconciliation
from merged_pipeline.py. Adds batch processing with intermediate saves
and resume capability.

Output: CSV + Parquet (partitioned by ticker).
"""
import sys, os, json, time, traceback, warnings
from datetime import datetime, date
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

warnings.filterwarnings("ignore")

SCRATCHPAD = Path(__file__).resolve().parent

sys.path.insert(0, str(SCRATCHPAD))
from merged_pipeline import (
    fetch_sec_full, derive_q4, reconcile_ticker,
    sanity_check, duplicate_ni_scan, load_cached,
    cik_for,
)

UNIVERSE_FILE = SCRATCHPAD / "sp_universe.json"
CHECKPOINT_DIR = SCRATCHPAD / "pipeline_checkpoints"
OUTPUT_CSV = SCRATCHPAD / "scaled_fundamentals.csv"
OUTPUT_PARQUET = SCRATCHPAD / "scaled_fundamentals_parquet"
PROGRESS_FILE = CHECKPOINT_DIR / "progress.json"

BATCH_SIZE = 50

COLS = [
    "ticker", "fiscal_quarter", "quarter_end_date",
    "revenue", "revenue_conf",
    "net_income", "net_income_conf",
    "eps", "eps_conf",
    "earnings_release_date", "release_date_conf",
    "notes",
]


def load_universe():
    with open(UNIVERSE_FILE) as f:
        data = json.load(f)
    return data["combined"]


def load_progress():
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"completed": [], "failed": {}, "rows": []}


def save_progress(progress):
    CHECKPOINT_DIR.mkdir(exist_ok=True)
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f)


def save_batch_checkpoint(batch_num, rows):
    CHECKPOINT_DIR.mkdir(exist_ok=True)
    path = CHECKPOINT_DIR / f"batch_{batch_num:04d}.json"
    with open(path, "w") as f:
        json.dump(rows, f)


def load_all_checkpoint_rows():
    if not CHECKPOINT_DIR.exists():
        return []
    all_rows = []
    for p in sorted(CHECKPOINT_DIR.glob("batch_*.json")):
        with open(p) as f:
            all_rows.extend(json.load(f))
    return all_rows


CLASS_EPS_FILE = SCRATCHPAD / "class_eps_supplement.json"
_class_eps = json.loads(CLASS_EPS_FILE.read_text()) if CLASS_EPS_FILE.exists() else {}


def _apply_class_eps(ticker, rows):
    """Fill EPS that companyfacts lacks because the filer tagged it only per
    share class (built by class_eps.py from each filing's XBRL instance)."""
    sup = _class_eps.get(ticker, {}).get("rows", {})
    if not sup:
        return
    ends = {datetime.strptime(k, "%Y-%m-%d").date(): v for k, v in sup.items()}
    for r in rows:
        if r.get("eps") is not None:
            continue
        qed = datetime.strptime(r["quarter_end_date"], "%Y-%m-%d").date()
        hit = next((v for d, v in ends.items() if abs((d - qed).days) <= 5), None)
        if hit is None:
            continue
        cls = hit["class"].split(":")[-1].replace("Member", "")
        r["eps"] = hit["eps"]
        r["eps_conf"] = "SINGLE_SOURCE"
        note = (f"EPS for {cls} from the filing's XBRL instance ({hit['source']}); "
                f"companyfacts omits class-level EPS")
        r["notes"] = f"{r['notes']}; {note}" if r.get("notes") else note


def process_ticker(ticker, custom_rows, et_rows):
    """Process one ticker: SEC pull + Q4 derivation + reconciliation."""
    q, a, sh = fetch_sec_full(ticker)
    if not q and not a:
        return [], "no_data"

    q4_derived = derive_q4(q, a, sh, ticker)
    rows, eps_log = reconcile_ticker(ticker, q, a, sh, custom_rows, et_rows)
    _apply_class_eps(ticker, rows)
    return rows, None


def run_pipeline():
    T0 = time.time()
    tickers = load_universe()

    print("=" * 70)
    print(f"  Scaled Fundamentals Pipeline")
    print(f"  {len(tickers)} tickers")
    print("=" * 70)

    # Load cached comparison data (available for original 36 tickers)
    print("\n--- Loading cached comparison data ---")
    custom_rows, et_rows = load_cached()
    print(f"  Custom: {len(custom_rows)} rows   ET: {len(et_rows)} rows")

    # Check CIK availability
    print("\n--- Checking CIK availability ---")
    no_cik = []
    for tk in tickers:
        if cik_for(tk) is None:
            no_cik.append(tk)
    if no_cik:
        print(f"  {len(no_cik)} tickers have no SEC CIK mapping:")
        for tk in no_cik:
            print(f"    {tk}")
    else:
        print(f"  All {len(tickers)} tickers have CIK mappings")

    # Load progress for resume capability
    progress = load_progress()
    completed_set = set(progress["completed"])
    remaining = [tk for tk in tickers if tk not in completed_set]

    if completed_set:
        print(f"\n--- Resuming: {len(completed_set)} already done, "
              f"{len(remaining)} remaining ---")

    # Process in batches
    batch_rows = []
    # Checkpoints are flushed by row count, not ticker count, so derive the
    # next batch number from files on disk to avoid overwriting saved batches.
    existing = [int(p.stem.split("_")[1]) for p in CHECKPOINT_DIR.glob("batch_*.json")] \
        if CHECKPOINT_DIR.exists() else []
    batch_num = max(existing, default=0)
    failed = dict(progress.get("failed", {}))
    ticker_stats = {}
    n_done_at_start = len(completed_set)

    print(f"\n--- Processing {len(remaining)} tickers ---")

    for i, tk in enumerate(remaining):
        idx = n_done_at_start + i + 1
        pct = idx / len(tickers) * 100
        elapsed = time.time() - T0
        rate = idx / elapsed if elapsed > 0 else 0
        eta = (len(tickers) - idx) / rate if rate > 0 else 0

        print(f"  [{idx:>4}/{len(tickers)}] {pct:5.1f}% {tk:<6} "
              f"(elapsed {elapsed:.0f}s, ETA {eta:.0f}s) ...",
              end=" ", flush=True)

        try:
            rows, err = process_ticker(tk, custom_rows, et_rows)
            if err:
                failed[tk] = err
                print(f"SKIP ({err})")
            else:
                print(f"{len(rows)} quarters")
                batch_rows.extend(rows)
                ticker_stats[tk] = len(rows)
        except Exception as e:
            err_msg = str(e)[:200]
            failed[tk] = err_msg
            print(f"ERROR: {err_msg}")
            traceback.print_exc()

        completed_set.add(tk)

        # Save checkpoint every BATCH_SIZE tickers
        if len(batch_rows) >= BATCH_SIZE * 15 or i == len(remaining) - 1:
            batch_num += 1
            save_batch_checkpoint(batch_num, batch_rows)
            progress["completed"] = sorted(completed_set)
            progress["failed"] = failed
            save_progress(progress)
            print(f"  --- Checkpoint saved (batch {batch_num}, "
                  f"{len(batch_rows)} rows) ---")
            batch_rows = []

    # Collect all rows from checkpoints
    print("\n--- Assembling final dataset ---")
    all_rows = load_all_checkpoint_rows()
    print(f"  Total rows: {len(all_rows)}")
    print(f"  Total tickers with data: "
          f"{len(set(r['ticker'] for r in all_rows))}")
    print(f"  Failed/skipped: {len(failed)}")

    if failed:
        print(f"\n  Failed tickers:")
        for tk, reason in sorted(failed.items()):
            print(f"    {tk}: {reason}")

    # Sanity checks
    print("\n--- Sanity checks ---")
    rejected = sanity_check(all_rows)
    if rejected:
        print(f"  {len(rejected)} rejections:")
        for r in rejected[:20]:
            print(f"    {r}")
        if len(rejected) > 20:
            print(f"    ... and {len(rejected)-20} more")
    else:
        print("  No rejections")

    # Duplicate NI scan
    print("\n--- Duplicate NI scan ---")
    dup_flags = duplicate_ni_scan(all_rows)
    if dup_flags:
        for f in dup_flags[:20]:
            print(f"  FLAGGED: {f}")
        if len(dup_flags) > 20:
            print(f"  ... and {len(dup_flags)-20} more")
        print(f"  {len(dup_flags)} tickers flagged")
    else:
        print("  Zero flagged — PASS")

    # Write CSV
    print(f"\n--- Writing CSV ---")
    df = pd.DataFrame(all_rows)
    for col in COLS:
        if col not in df.columns:
            df[col] = None
    df = df[COLS + [c for c in df.columns
                    if c not in COLS and c != "is_q4" and not c.startswith("_")]]
    df.sort_values(["ticker", "quarter_end_date"], inplace=True)
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"  Saved: {OUTPUT_CSV}")
    print(f"  {len(df)} rows, {df['ticker'].nunique()} tickers")

    # Write Parquet (partitioned by ticker)
    print(f"\n--- Writing Parquet ---")
    pq_df = df[COLS].copy()
    pq_df["quarter_end_date"] = pd.to_datetime(pq_df["quarter_end_date"])
    pq_df["earnings_release_date"] = pd.to_datetime(
        pq_df["earnings_release_date"], errors="coerce")
    pq_df["revenue"] = pd.to_numeric(pq_df["revenue"], errors="coerce")
    pq_df["net_income"] = pd.to_numeric(pq_df["net_income"], errors="coerce")
    pq_df["eps"] = pd.to_numeric(pq_df["eps"], errors="coerce")

    table = pa.Table.from_pandas(pq_df)
    OUTPUT_PARQUET.mkdir(exist_ok=True)
    pq.write_to_dataset(
        table,
        root_path=str(OUTPUT_PARQUET),
        partition_cols=["ticker"],
    )
    print(f"  Saved: {OUTPUT_PARQUET}")

    # Summary
    elapsed = time.time() - T0
    print(f"\n{'='*70}")
    print(f"  PIPELINE COMPLETE")
    print(f"{'='*70}")
    print(f"  Tickers processed: {len(completed_set)}")
    print(f"  Tickers with data: {len(set(r['ticker'] for r in all_rows))}")
    print(f"  Failed/skipped:    {len(failed)}")
    print(f"  Total quarters:    {len(all_rows)}")
    print(f"  Sanity rejections: {len(rejected)}")
    print(f"  Duplicate NI flags:{len(dup_flags)}")
    print(f"  Elapsed:           {elapsed:.0f}s ({elapsed/60:.1f}m)")


if __name__ == "__main__":
    run_pipeline()
