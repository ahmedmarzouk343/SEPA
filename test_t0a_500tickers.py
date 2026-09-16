"""
Quick diagnostic: simulate only the T0-A condition (ratio_pass) with ~500
tickers to verify whether it fires. Bypasses Backtrader entirely.
"""
import collections
import sys
from pathlib import Path
import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from market_regime_gate import compute_new_high_low_ratio, new_high_low_ratio_favorable
from sp500_tickers import SP500_TICKERS

HISTORY_BUFFER_MAXLEN = 260
WARMUP_START = "2022-08-01"
IS_START = "2023-08-27"
IS_END = "2025-08-26"

print(f"Downloading {len(SP500_TICKERS)} S&P 500 tickers...")
data = {}
for i, t in enumerate(SP500_TICKERS):
    if (i + 1) % 100 == 0:
        print(f"  {i+1}/{len(SP500_TICKERS)}")
    try:
        df = yf.download(t, start=WARMUP_START, end=IS_END, auto_adjust=True, progress=False)
    except Exception:
        continue
    if df is not None and not df.empty:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        data[t] = df

print(f"Loaded: {len(data)} tickers")

# Get common dates
all_dates = None
for t, df in data.items():
    dates = set(df.index)
    if all_dates is None:
        all_dates = dates
    else:
        all_dates = all_dates.intersection(dates)
common_dates = sorted(all_dates)
print(f"Common dates: {len(common_dates)} (first={common_dates[0].date()}, last={common_dates[-1].date()})")

# Simulate accumulation
history = {t: collections.deque(maxlen=HISTORY_BUFFER_MAXLEN) for t in data}
high_low_counts = collections.deque(maxlen=HISTORY_BUFFER_MAXLEN)

is_start_dt = pd.Timestamp(IS_START)
ratio_true_count = 0
is_bar_count = 0

for bar_idx, date in enumerate(common_dates):
    for t, df in data.items():
        if date in df.index:
            history[t].append({"Close": float(df.loc[date, "Close"])})

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

    # Check ratio_pass during IS period
    if date >= is_start_dt:
        is_bar_count += 1
        if len(high_low_counts) >= 22:
            ch = pd.Series([h for h, _ in high_low_counts])
            cl = pd.Series([l for _, l in high_low_counts])
            ratio = compute_new_high_low_ratio(ch, cl)
            fav = new_high_low_ratio_favorable(ratio)
            if not pd.isna(fav.iloc[-1]) and bool(fav.iloc[-1]):
                ratio_true_count += 1

        # Print first 3 and last 3 IS bars
        if is_bar_count <= 3 or is_bar_count >= (len(common_dates) - bar_idx + is_bar_count - 2):
            if is_bar_count <= 3:
                print(f"  IS bar {is_bar_count}: date={date.date()} H={count_high} L={count_low} deque_len={len(high_low_counts)}")

print(f"\n--- T0-A Results with {len(data)} tickers ---")
print(f"IS bars: {is_bar_count}")
print(f"ratio_pass=True: {ratio_true_count}")
print(f"ratio_pass=True %: {ratio_true_count/is_bar_count*100:.1f}%" if is_bar_count else "N/A")

# Show last 5 deque entries
hl = list(high_low_counts)
print(f"\nLast 5 deque entries:")
for i in range(max(0, len(hl)-5), len(hl)):
    h, l = hl[i]
    r = h / (l + 1)
    print(f"  H={h:3d}  L={l:3d}  ratio={r:.3f}")
