"""Fingerprints of every data input that changes a decision, and store checks.

quick()   -- cheap (file sizes and mtimes plus table hashes): recorded in a
             signal bundle and re-checked every time the bundle is used, so a
             bundle built on other data is refused instead of silently mixed
             with fresh fills.
content() -- SHA-256 of file contents: recorded in the bundle at build time
             and compared by the validation runner with its own lock hashes,
             so the validation provably ran on the development data.
store_integrity() -- one parquet file per ticker partition, no duplicate
             (ticker, quarter_end_date), FIZZ EPS all null. pyarrow's
             write_to_dataset appends, so a rebuild without a clean directory
             can leave two versions of a quarter.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "us_fundamentals" / "scaled_fundamentals_parquet"
PRICES = ROOT / "kashif_data" / "prices" / "US"


def _stat_hash(folder: Path, pattern: str) -> str:
    h = hashlib.sha256()
    for p in sorted(folder.rglob(pattern)):
        st = p.stat()
        h.update(f"{p.relative_to(folder)}|{st.st_size}|{st.st_mtime_ns}\n".encode())
    return h.hexdigest()[:16]


def sha_tree(folder: Path, pattern: str) -> str:
    h = hashlib.sha256()
    for p in sorted(folder.rglob(pattern)):
        h.update(str(p.relative_to(folder)).encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def tables() -> dict:
    from kashif_engine.data import price_corrections as PC
    from kashif_engine.data.fundamentals import split_table_fingerprint
    return {"splits": split_table_fingerprint(), "breaks": PC.breaks_fingerprint(),
            "corrections": hashlib.sha256(repr(PC.CORRECTIONS).encode()).hexdigest()[:16]}


def quick() -> dict:
    return tables() | {"store_stat": _stat_hash(STORE, "*.parquet"), "prices_stat": _stat_hash(PRICES, "*.parquet")}


def content() -> dict:
    return tables() | {"fundamentals_store": sha_tree(STORE, "*.parquet"),
                       "price_cache": sha_tree(PRICES, "*.parquet")}


def store_integrity() -> list:
    """Problems with the fundamentals store; empty when it is sound."""
    import pandas as pd
    import pyarrow.parquet as pq
    problems = []
    for part in sorted(STORE.iterdir()):
        files = list(part.glob("*.parquet"))
        if len(files) != 1:
            problems.append(f"{part.name}: {len(files)} parquet files")
    df = pq.read_table(str(STORE)).to_pandas()
    dup = df.duplicated(["ticker", "quarter_end_date"])
    if dup.any():
        problems.append(f"{int(dup.sum())} duplicate (ticker, quarter_end_date) rows")
    fizz = df[df["ticker"].astype(str) == "FIZZ"]
    if fizz["eps"].notna().any():
        problems.append("FIZZ has non-null EPS (XBRL_EPS_UNRELIABLE not applied)")
    return problems
