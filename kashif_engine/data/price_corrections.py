"""Documented corrections to Yahoo's split adjustment, applied at load time.

Yahoo's split-adjusted history is used as-is, except where the split ratio
Yahoo applied contradicts the company's own SEC filing (found while verifying
2014-2021 splits for experiment 2; every other verified split agrees within 0.5%).
The raw cache files are never edited: the correction is applied in memory on load.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

# ticker, first bar on the new basis, ratio Yahoo applied, ratio in the filing (new/old), source
CORRECTIONS = [
    {"ticker": "VTOL", "ex_date": "2020-06-12", "yahoo_ratio": 0.5, "filing_ratio": 1 / 3,
     "source": "Era Group 1-for-3 reverse split effective 2020-06-11 (SEC filings cited in "
               "kashif_data/experiment2/splits_2014_2021.json); Yahoo booked 1-for-2."},
]


# History breaks (kashif_engine/data/history_breaks.csv, from the 2014-2021
# identity check): the series before `date` belongs to another company or
# basis -- a SPAC shell, a predecessor, cancelled pre-bankruptcy equity, a
# spun-off parent. kind: price_cut (drop bars before date), fundamentals_break
# (no YoY across date; kashif_engine.data.fundamentals), both, bad_bar (drop
# that one bar).
BREAKS_FILE = Path(__file__).with_name("history_breaks.csv")
PRICE_KINDS = ("price_cut", "both")
FUND_KINDS = ("fundamentals_break", "both")
_breaks = None


def history_breaks(ticker: str | None = None) -> list[dict]:
    global _breaks
    if _breaks is None:
        if not BREAKS_FILE.exists():
            raise FileNotFoundError(f"{BREAKS_FILE} missing: an absent table would silently mean 'no breaks'")
        rows = pd.read_csv(BREAKS_FILE, dtype=str, keep_default_na=False).to_dict("records")
        for b in rows:
            for k in ("ticker", "date", "kind"):
                b[k] = str(b.get(k, "")).strip()
            if not b["ticker"] or b["kind"] not in PRICE_KINDS + FUND_KINDS + ("bad_bar",):
                raise ValueError(f"bad history-break row: {b}")
            d = pd.to_datetime(b["date"], errors="raise") if b["date"] else pd.NaT
            if pd.isna(d):                  # pd.to_datetime("") is NaT, not an error
                raise ValueError(f"history-break row without a date: {b}")
            b["date"] = str(d.date())
        keys = [(b["ticker"], b["date"], b["kind"]) for b in rows]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate history-break rows")
        _breaks = rows
    return [b for b in _breaks if ticker is None or b["ticker"] == ticker]


def apply(ticker: str, df: pd.DataFrame) -> pd.DataFrame:
    for b in history_breaks(ticker):
        d = pd.Timestamp(b["date"])
        if b["kind"] in PRICE_KINDS:
            df = df[df.index >= d]
        elif b["kind"] == "bad_bar":
            if d in df.index and (df.loc[d, "Splits"] not in (0, 0.0) or df.loc[d, "Dividends"] not in (0, 0.0)):
                raise ValueError(f"{ticker} bad_bar {d.date()} carries a split or dividend; carry it, don't drop it")
            df = df.drop(index=d, errors="ignore")
    for c in CORRECTIONS:
        if c["ticker"] != ticker:
            continue
        ex = pd.Timestamp(c["ex_date"])
        k = c["yahoo_ratio"] / c["filing_ratio"]     # >1: pre-split bars were under-scaled
        before = df.index < ex
        df = df.copy()
        for col in ("Open", "High", "Low", "Close", "AdjClose", "Dividends"):
            df.loc[before, col] = df.loc[before, col] * k
        df.loc[before, "Volume"] = df.loc[before, "Volume"] / k
        if ex in df.index:
            df.loc[ex, "Splits"] = c["filing_ratio"]
    return df


def fingerprint(ticker: str) -> tuple:
    """Corrections applied to `ticker`, for cache keys (the cache file's mtime
    does not change when a correction is added)."""
    return tuple(sorted((c["ex_date"], c["yahoo_ratio"], c["filing_ratio"])
                        for c in CORRECTIONS if c["ticker"] == ticker)) +         tuple(sorted((b["date"], b["kind"]) for b in history_breaks(ticker)))


def breaks_fingerprint() -> str:
    """Hash of the whole break table, for caches keyed across tickers."""
    import hashlib
    rows = sorted((b["ticker"], b["date"], b["kind"]) for b in history_breaks())
    return hashlib.sha256(repr(rows).encode()).hexdigest()[:16]
