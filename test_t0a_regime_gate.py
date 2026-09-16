"""
test_t0a_regime_gate.py — Controlled unit test for T0-A regime gate bug.

Synthetic 25-bar scenario:
  Bars 1-3:  2 new highs, 5 new lows (weak breadth)
  Bars 4-25: progressively more highs, fewer lows (improving bull)

Hand-calculated expected result on bar 25:
  ratio[25] = 13 / (1+1) = 6.500
  ratio[25-21] = ratio[4] = 3 / (4+1) = 0.600
  ratio[25] > ratio[4]  ->  6.500 > 0.600  ->  TRUE

If the current code returns False, the bug is confirmed and we show exactly
where it diverges.
"""

import collections
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from market_regime_gate import compute_new_high_low_ratio, new_high_low_ratio_favorable

# --------------------------------------------------------------------------
# Synthetic data: 25 bars of (count_high, count_low)
# --------------------------------------------------------------------------
SYNTHETIC_BARS = [
    # Bars 1-3: weak breadth
    (2, 5),   # bar 1
    (2, 5),   # bar 2
    (2, 5),   # bar 3
    # Bars 4-25: progressively improving
    (3, 4),   # bar 4   — user spec
    (3, 4),   # bar 5
    (4, 4),   # bar 6
    (4, 3),   # bar 7
    (5, 3),   # bar 8   — user spec
    (5, 3),   # bar 9
    (6, 3),   # bar 10
    (7, 2),   # bar 11
    (8, 2),   # bar 12  — user spec
    (8, 2),   # bar 13
    (9, 2),   # bar 14
    (9, 2),   # bar 15
    (9, 1),   # bar 16
    (10, 1),  # bar 17
    (10, 1),  # bar 18
    (10, 1),  # bar 19
    (11, 1),  # bar 20
    (11, 1),  # bar 21
    (12, 1),  # bar 22  — user spec
    (12, 1),  # bar 23
    (12, 1),  # bar 24
    (13, 1),  # bar 25
]

assert len(SYNTHETIC_BARS) == 25


# --------------------------------------------------------------------------
# Hand-calculate expected values
# --------------------------------------------------------------------------
print("=" * 70)
print("T0-A Unit Test: 25-bar synthetic scenario")
print("=" * 70)

print("\n--- Hand Calculation ---")
for i, (h, l) in enumerate(SYNTHETIC_BARS, 1):
    ratio = h / (l + 1)
    print(f"  Bar {i:2d}: H={h:2d}, L={l:2d}  ->  ratio = {h}/({l}+1) = {ratio:.3f}")

# On bar 25 (index 24), ratio.shift(21) gives index 24-21 = 3 (bar 4)
h25, l25 = SYNTHETIC_BARS[24]
h4, l4 = SYNTHETIC_BARS[3]
ratio_bar25 = h25 / (l25 + 1)
ratio_bar4 = h4 / (l4 + 1)
expected = ratio_bar25 > ratio_bar4
print(f"\n  ratio[bar 25] = {ratio_bar25:.3f}")
print(f"  ratio[bar 4]  = {ratio_bar4:.3f}   (= ratio.shift(21) at bar 25)")
print(f"  {ratio_bar25:.3f} > {ratio_bar4:.3f}  ->  EXPECTED = {expected}")


# --------------------------------------------------------------------------
# Run the EXACT current code path (extracted from _new_high_low_ratio_favorable_snapshot)
# --------------------------------------------------------------------------
print("\n--- Running Current Code ---")

_high_low_counts = collections.deque(maxlen=260)
for h, l in SYNTHETIC_BARS:
    _high_low_counts.append((h, l))

print(f"  Deque length: {len(_high_low_counts)}")
print(f"  Guard check (len >= 22): {len(_high_low_counts) >= 22}")

if len(_high_low_counts) < 22:
    actual = False
    print("  EARLY EXIT: deque too short -> False")
else:
    count_high = pd.Series([h for h, _ in _high_low_counts])
    count_low = pd.Series([l for _, l in _high_low_counts])
    ratio = compute_new_high_low_ratio(count_high, count_low)
    fav = new_high_low_ratio_favorable(ratio)

    print(f"\n  ratio series (all {len(ratio)} values):")
    for idx in range(len(ratio)):
        r = ratio.iloc[idx]
        f_val = fav.iloc[idx]
        shifted = ratio.shift(21).iloc[idx]
        print(f"    [{idx:2d}] ratio={r:.3f}  shift(21)={'NaN' if pd.isna(shifted) else f'{shifted:.3f}':>7s}  fav={f_val}")

    last_fav = fav.iloc[-1]
    actual = bool(last_fav) if not pd.isna(last_fav) else False
    print(f"\n  fav.iloc[-1] = {last_fav}")
    print(f"  pd.isna(fav.iloc[-1]) = {pd.isna(last_fav)}")
    print(f"  ACTUAL RESULT = {actual}")


# --------------------------------------------------------------------------
# Verdict
# --------------------------------------------------------------------------
print("\n--- Verdict ---")
print(f"  Expected: {expected}")
print(f"  Actual:   {actual}")
if actual == expected:
    print("  OK MATCH — current code returns correct result on synthetic data")
    print("  -> T0-A logic is correct in isolation. Bug may be in other regime")
    print("    conditions (leader_pullback_shallow, leader_divergence) or in")
    print("    how the 52-week high/low counts are accumulated with real data.")
else:
    print("  FAIL MISMATCH — current code has a bug!")
    print("  -> The snapshot method diverges from the hand calculation.")

print("=" * 70)
