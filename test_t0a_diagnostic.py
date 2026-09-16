"""
Diagnostic: simulate the exact _high_low_counts accumulation logic
with REAL S&P 500 data to see if the deque values are truly constant.
"""
import collections
import sys
from pathlib import Path
import pandas as pd
import yfinance as yf

HISTORY_BUFFER_MAXLEN = 260
WARMUP_START = "2022-08-01"
IS_END = "2025-08-26"

# Use a small set of tickers for speed
TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM",
           "V", "UNH", "JNJ", "WMT", "PG", "MA", "HD", "DIS", "BAC", "XOM",
           "PFE", "CSCO"]

print(f"Downloading {len(TICKERS)} tickers...")
data = {}
for t in TICKERS:
    df = yf.download(t, start=WARMUP_START, end=IS_END, auto_adjust=True, progress=False)
    if df is not None and not df.empty:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        data[t] = df
        print(f"  {t}: {len(df)} bars")

# Get common dates (simulate Backtrader's synchronization)
all_dates = None
for t, df in data.items():
    dates = set(df.index)
    if all_dates is None:
        all_dates = dates
    else:
        all_dates = all_dates.intersection(dates)
common_dates = sorted(all_dates)
print(f"\nCommon dates: {len(common_dates)} bars")
print(f"  First: {common_dates[0]}")
print(f"  Last:  {common_dates[-1]}")

# Simulate the accumulation logic from next()
history = {t: collections.deque(maxlen=HISTORY_BUFFER_MAXLEN) for t in data}
high_low_counts = collections.deque(maxlen=HISTORY_BUFFER_MAXLEN)

for bar_idx, date in enumerate(common_dates):
    # Append to history
    for t, df in data.items():
        if date in df.index:
            row = df.loc[date]
            history[t].append({"Close": float(row["Close"])})

    # Count 52-week highs/lows (exact same logic as kashif_strategy.py:349-360)
    count_high = 0
    count_low = 0
    for t in data:
        closes = [b["Close"] for b in history[t]]
        if len(closes) >= 253:
            if closes[-1] >= max(closes[-253:]):
                count_high += 1
            if closes[-1] <= min(closes[-253:]):
                count_low += 1
    high_low_counts.append((count_high, count_low))

print(f"\n--- High/Low Counts (last 30 bars of deque) ---")
counts_list = list(high_low_counts)
start = max(0, len(counts_list) - 30)
for i in range(start, len(counts_list)):
    h, l = counts_list[i]
    bar_num = len(common_dates) - len(counts_list) + i
    date_approx = common_dates[bar_num] if bar_num < len(common_dates) else "?"
    ratio = h / (l + 1) if True else 0
    print(f"  [{i:3d}] bar={bar_num:4d}  date={str(date_approx)[:10]}  H={h:3d}  L={l:3d}  ratio={ratio:.3f}")

# Show ratio comparison for the last few bars
print(f"\n--- Ratio comparison (last 5 bars, window=21) ---")
all_h = pd.Series([h for h, _ in high_low_counts])
all_l = pd.Series([l for _, l in high_low_counts])
ratio = all_h / (all_l + 1)
shifted = ratio.shift(21)
for i in range(max(0, len(ratio) - 5), len(ratio)):
    r = ratio.iloc[i]
    s = shifted.iloc[i]
    fav = r > s if not pd.isna(s) else False
    print(f"  [{i}] ratio={r:.3f}  shift(21)={'NaN' if pd.isna(s) else f'{s:.3f}'}  fav={fav}")

# Summary
print(f"\n--- Summary ---")
print(f"Total bars: {len(common_dates)}")
print(f"Deque length: {len(high_low_counts)}")
unique_counts = len(set(counts_list))
print(f"Unique (H, L) tuples in deque: {unique_counts}")
print(f"Bars with 0 highs and 0 lows: {sum(1 for h, l in counts_list if h == 0 and l == 0)}")
fav_series = ratio > ratio.shift(21)
fav_true = fav_series.sum()
print(f"Bars where ratio > ratio.shift(21): {int(fav_true)} / {len(ratio)}")
