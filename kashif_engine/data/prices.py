"""Daily OHLCV from yfinance, cached as one Parquet file per ticker.

Yahoo's `Close`/`Open`/`High`/`Low`/`Volume` are already SPLIT-adjusted
(`Adj Close` is additionally dividend-adjusted). We keep both views:

  split-adjusted (Open..Close, Volume)  -> every signal. Trend Template, RS,
      VCP and regime logic are all ratios/comparisons, so a uniform rescale of
      past bars by a later split cannot change any decision: no lookahead.
  raw (RawOpen..RawClose, RawVolume)    -> fills, share counts, commissions,
      stop prices, liquidity. Reconstructed as split_adj * (product of split
      ratios with ex-date AFTER the bar).

Dividends are kept per RAW share on the ex-date so the ledger can credit cash.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "kashif_data" / "prices"
COLUMNS = ["Open", "High", "Low", "Close", "AdjClose", "Volume", "Dividends", "Splits"]


def _cache_path(market: str, ticker: str) -> Path:
    return CACHE_DIR / market / f"{ticker}.parquet"


def download(tickers, market="US", suffix="", start="2019-06-01", end=None,
             chunk=40, pause=2.0, log=print, force=False):
    """Fetch and cache tickers (all of them with force=True). Returns failures."""
    import yfinance as yf
    out_dir = CACHE_DIR / market
    out_dir.mkdir(parents=True, exist_ok=True)
    todo = list(tickers) if force else [t for t in tickers if not _cache_path(market, t).exists()]
    failed = []
    for i in range(0, len(todo), chunk):
        batch = todo[i:i + chunk]
        symbols = [t.replace(".", "-") + suffix for t in batch]
        for attempt in range(4):
            try:
                df = yf.download(symbols, start=start, end=end, auto_adjust=False,
                                 actions=True, group_by="ticker", progress=False, threads=True)
                break
            except Exception as ex:  # noqa: BLE001 -- network; retry with backoff
                log(f"  batch {i // chunk} attempt {attempt + 1} failed: {ex}")
                time.sleep(pause * (2 ** attempt))
        else:
            failed.extend(batch)
            continue
        for t, sym in zip(batch, symbols):
            try:
                sub = df[sym] if isinstance(df.columns, pd.MultiIndex) else df
            except KeyError:
                failed.append(t)
                continue
            sub = sub.rename(columns={"Adj Close": "AdjClose", "Stock Splits": "Splits"})
            sub = sub.dropna(subset=["Close"])
            if sub.empty:
                failed.append(t)
                continue
            for c in COLUMNS:
                if c not in sub.columns:
                    sub[c] = 0.0
            sub = sub[COLUMNS].astype(float)
            sub.index = pd.to_datetime(sub.index).tz_localize(None).normalize()
            sub.index.name = "Date"
            sub.to_parquet(_cache_path(market, t))
        log(f"  prices: {min(i + chunk, len(todo))}/{len(todo)} fetched, {len(failed)} failed")
        time.sleep(pause)
    return failed


def load(ticker, market="US") -> pd.DataFrame | None:
    """Cached frame with split-adjusted and reconstructed raw columns."""
    p = _cache_path(market, ticker)
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    from kashif_engine.data import price_corrections
    return add_raw_columns(price_corrections.apply(ticker, df))


def add_raw_columns(df: pd.DataFrame) -> pd.DataFrame:
    """RawX = X * factor, factor = product of split ratios with ex-date after the bar."""
    df = df.copy()
    splits = df["Splits"].where(df["Splits"] > 0, 1.0)
    # factor on bar t multiplies all splits strictly after t.
    after = splits[::-1].cumprod()[::-1].shift(-1).fillna(1.0)
    df["SplitFactor"] = after
    for c in ("Open", "High", "Low", "Close"):
        df["Raw" + c] = df[c] * after
    df["RawVolume"] = df["Volume"] / after
    # Yahoo reports dividends in split-adjusted units; convert to per raw share.
    df["RawDividend"] = df["Dividends"] * after
    return df


def cached_tickers(market="US"):
    d = CACHE_DIR / market
    return sorted(p.stem for p in d.glob("*.parquet")) if d.exists() else []
