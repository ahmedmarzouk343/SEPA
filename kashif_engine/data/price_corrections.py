"""Documented corrections to Yahoo's split adjustment, applied at load time.

Yahoo's split-adjusted history is used as-is, except where the split ratio
Yahoo applied contradicts the company's own SEC filing (found while verifying
2014-2021 splits for experiment 2; every other verified split agrees within 0.5%).
The raw cache files are never edited: the correction is applied in memory on load.
"""
from __future__ import annotations

import pandas as pd

# ticker, first bar on the new basis, ratio Yahoo applied, ratio in the filing (new/old), source
CORRECTIONS = [
    {"ticker": "VTOL", "ex_date": "2020-06-12", "yahoo_ratio": 0.5, "filing_ratio": 1 / 3,
     "source": "Era Group 1-for-3 reverse split effective 2020-06-11 (SEC filings cited in "
               "kashif_data/experiment2/splits_2014_2021.json); Yahoo booked 1-for-2."},
]


def apply(ticker: str, df: pd.DataFrame) -> pd.DataFrame:
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
                        for c in CORRECTIONS if c["ticker"] == ticker))
