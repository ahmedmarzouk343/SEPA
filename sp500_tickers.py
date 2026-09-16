"""
sp500_tickers.py — S&P 500 constituent list for comparison backtest.

Fetches the current S&P 500 list from Wikipedia, parses tickers,
fixes special characters for yfinance compatibility (e.g. BRK.B → BRK-B).
"""

import io

import pandas as pd
import requests

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def fetch_sp500_tickers():
    resp = requests.get(SP500_URL, headers={"User-Agent": "KashifBacktest/1.0"})
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    df = tables[0]
    raw_tickers = df["Symbol"].tolist()
    fixed = [t.replace(".", "-") for t in raw_tickers]
    return sorted(set(fixed))


SP500_TICKERS = fetch_sp500_tickers()

if __name__ == "__main__":
    print(f"S&P 500 tickers: {len(SP500_TICKERS)}")
    print(f"First 10: {SP500_TICKERS[:10]}")
    print(f"Last 10:  {SP500_TICKERS[-10:]}")
    brkb = "BRK-B" in SP500_TICKERS
    bfb = "BF-B" in SP500_TICKERS
    print(f"BRK-B present: {brkb}")
    print(f"BF-B present:  {bfb}")
