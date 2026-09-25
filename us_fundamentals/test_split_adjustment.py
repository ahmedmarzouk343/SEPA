"""
Verify split-adjustment logic against the verified split table.

Tests:
1. Raw vs adjusted EPS at each split boundary (original 5 tickers)
2. Non-split tickers (BURL, CRM) are completely unaffected
3. Cross-boundary comparison — TTEK quarter before split vs after,
   side-by-side showing the fix works
4. Edge cases: None EPS, same-day comparison, as_of_date required
5. Lookahead-bias test: as_of_date BEFORE a split must not apply it
6. Reverse splits (NLY, LXP): pre-split EPS is multiplied, exactly
7. Every split in the table vs the dataset's own as-filed EPS basis
"""
import sys, os, math
os.environ["PYTHONIOENCODING"] = "utf-8"
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from datetime import date, timedelta
from fractions import Fraction
from fundamentals_store import (
    adjust_eps_for_splits,
    get_cumulative_split_factor,
    get_split_events,
    STOCK_SPLITS,
    PARQUET_ROOT,
)
import pyarrow.parquet as pq
import pandas as pd

# Load Parquet data
table = pq.read_table(str(PARQUET_ROOT))
df = table.to_pandas()
df["quarter_end_date"] = pd.to_datetime(df["quarter_end_date"]).dt.date
df["earnings_release_date"] = pd.to_datetime(df["earnings_release_date"]).dt.date

# All tests use an explicit as_of_date — never date.today()
CURRENT = date(2026, 9, 24)

passed = 0
failed = 0

def check(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")
    if detail:
        print(f"        {detail}")


# ═══════════════════════════════════════════════════════════════════════
#  TEST 1: Each split ticker — raw vs adjusted EPS across boundary
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("  TEST 1: Raw vs adjusted EPS for each split ticker")
print("=" * 70)

SPLIT_TICKERS = ["TTEK", "NVDA", "GOOGL", "WMT", "AMZN"]

# Each split is checked at its own boundary (as of the first post-split
# release), so a ticker with several splits (NVDA) tests each one alone.
for ticker, split in [(t, s) for t in SPLIT_TICKERS for s in get_split_events(t)]:
    eff_date = split["effective_date"]
    ratio = split["ratio"]

    tdf = df[df["ticker"] == ticker].sort_values("earnings_release_date").copy()

    pre_split = tdf[tdf["earnings_release_date"] < eff_date]
    post_split = tdf[tdf["earnings_release_date"] >= eff_date]

    if pre_split.empty or post_split.empty:
        print(f"\n  {ticker}: Cannot test -- missing pre or post-split data")
        continue

    last_pre = pre_split.iloc[-1]
    first_post = post_split.iloc[0]

    raw_pre = last_pre["eps"]
    raw_post = first_post["eps"]
    erd_pre = last_pre["earnings_release_date"]
    erd_post = first_post["earnings_release_date"]
    fq_pre = last_pre["fiscal_quarter"]
    fq_post = first_post["fiscal_quarter"]

    adj_pre = adjust_eps_for_splits(ticker, raw_pre, erd_pre, erd_post)

    print(f"\n  {ticker} ({ratio}:1 split, effective {eff_date}):")
    print(f"    Last pre-split:  {fq_pre:12s}  raw EPS = ${raw_pre:>8.2f}  "
          f"adjusted = ${adj_pre:>8.4f}  (released {erd_pre})")
    print(f"    First post-split:{fq_post:12s}  raw EPS = ${raw_post:>8.2f}  "
          f"(released {erd_post})")

    if raw_pre is not None and raw_post is not None and adj_pre is not None:
        expected_adj = raw_pre / ratio
        check(f"{ticker} adjustment = raw/{ratio}",
              abs(adj_pre - expected_adj) < 0.001,
              f"${raw_pre:.2f}/{ratio} = ${expected_adj:.4f}, got ${adj_pre:.4f}")

        if raw_post != 0 and raw_pre != 0:
            raw_ratio = abs(raw_pre / raw_post)
            adj_ratio = abs(adj_pre / raw_post)
            compression = raw_ratio / adj_ratio if adj_ratio != 0 else float('inf')
            check(f"{ticker} magnitude compressed by ~{ratio}x (got {compression:.1f}x)",
                  abs(compression - ratio) / ratio < 0.01,
                  f"raw gap={raw_ratio:.1f}x, adj gap={adj_ratio:.2f}x, compression={compression:.1f}x")

    adj_post = adjust_eps_for_splits(ticker, raw_post, erd_post, erd_post)
    check(f"{ticker} post-split EPS unchanged",
          adj_post == raw_post,
          f"raw=${raw_post:.2f}, adjusted=${adj_post:.2f}")


# ═══════════════════════════════════════════════════════════════════════
#  TEST 2: Non-split tickers are completely unaffected
# ═══════════════════════════════════════════════════════════════════════
print(f"\n{'='*70}")
print("  TEST 2: Non-split tickers unaffected")
print("=" * 70)

# AAPL left this list when the 2014-2021 splits were merged: it split 7:1
# (2014-06-06) and 4:1 (2020-08-28, 8-K 2020-07-30), so it is no longer a
# non-split ticker over the data's span.
for ticker in ["BURL", "CRM", "MSFT"]:
    tdf = df[df["ticker"] == ticker].sort_values("earnings_release_date")

    all_unchanged = True
    for _, row in tdf.iterrows():
        raw = row["eps"]
        erd = row["earnings_release_date"]
        adj = adjust_eps_for_splits(ticker, raw, erd, CURRENT)
        if raw is not None and adj != raw:
            all_unchanged = False
            break

    check(f"{ticker}: all {len(tdf)} quarters unchanged",
          all_unchanged)

    factor = get_cumulative_split_factor(ticker, date(2020, 1, 1), CURRENT)
    check(f"{ticker}: split factor = {factor}", factor == 1.0)


# ═══════════════════════════════════════════════════════════════════════
#  TEST 3: Cross-boundary comparison (TTEK detailed)
# ═══════════════════════════════════════════════════════════════════════
print(f"\n{'='*70}")
print("  TEST 3: Cross-boundary comparison -- TTEK")
print("=" * 70)

ttek = df[df["ticker"] == "TTEK"].sort_values("quarter_end_date").copy()
eff = STOCK_SPLITS["TTEK"][0]["effective_date"]

print(f"\n  TTEK split: 5:1 effective {eff}")
print(f"\n  {'Quarter':12s} {'End Date':>12s} {'Released':>12s} {'Raw EPS':>10s} {'Adj EPS':>10s} {'Basis':>10s}")
print(f"  {'-'*68}")

for _, row in ttek.iterrows():
    fq = row["fiscal_quarter"]
    qed = row["quarter_end_date"]
    erd = row["earnings_release_date"]
    raw = row["eps"]
    if raw is None:
        continue

    adj = adjust_eps_for_splits("TTEK", raw, erd, CURRENT)
    basis = "pre-split" if erd < eff else "post-split"
    marker = " <--" if fq in ("Q3 2024", "Q4 2024", "Q2 2025", "Q3 2025") else ""

    print(f"  {fq:12s} {str(qed):>12s} {str(erd):>12s}  ${raw:>7.2f}  ${adj:>8.4f}  {basis:>10s}{marker}")

ttek_q3 = ttek[ttek["fiscal_quarter"] == "Q3 2024"].iloc[0]
ttek_q4 = ttek[ttek["fiscal_quarter"] == "Q4 2024"].iloc[0]
q3_adj = adjust_eps_for_splits("TTEK", ttek_q3["eps"], ttek_q3["earnings_release_date"], CURRENT)
q4_raw = ttek_q4["eps"]

print(f"\n  TTEK Q3 2024 (pre-split):  raw=${ttek_q3['eps']:.2f} -> adjusted=${q3_adj:.4f}")
print(f"  TTEK Q4 2024 (post-split): raw=${q4_raw:.2f} (no adjustment needed)")
print(f"  WITHOUT adjustment: Q3/Q4 ratio = {ttek_q3['eps']/q4_raw:.1f}x (fake 4.5x jump)")
print(f"  WITH adjustment:    Q3/Q4 ratio = {q3_adj/q4_raw:.2f}x (genuine change)")

check("TTEK Q3->Q4 no longer shows fake 5x jump",
      abs(q3_adj / q4_raw) < 3,
      f"adjusted ratio = {q3_adj/q4_raw:.2f}x")


# ═══════════════════════════════════════════════════════════════════════
#  TEST 4: Edge cases
# ═══════════════════════════════════════════════════════════════════════
print(f"\n{'='*70}")
print("  TEST 4: Edge cases")
print("=" * 70)

check("None EPS returns None",
      adjust_eps_for_splits("TTEK", None, date(2024, 1, 1), CURRENT) is None)

check("Same-day as effective date: no adjustment (split not yet in effect)",
      adjust_eps_for_splits("TTEK", 1.59, date(2024, 9, 6), CURRENT) == 1.59,
      "earnings_release ON effective_date -> condition is from < eff, not <=")

adj = adjust_eps_for_splits("TTEK", 1.59, date(2024, 9, 5), CURRENT)
check("Day before split: adjusted",
      abs(adj - 1.59 / 5) < 0.001,
      f"${adj:.4f} = $1.59/5")

adj = adjust_eps_for_splits("TTEK", 0.35, date(2024, 9, 7), CURRENT)
check("Day after split: unchanged",
      adj == 0.35,
      f"${adj:.2f}")

check("get_split_events('BURL') returns []",
      get_split_events("BURL") == [])

events = get_split_events("TTEK")
check("get_split_events('TTEK') has 1 event",
      len(events) == 1 and events[0]["ratio"] == 5)

# as_of_date is required (no default) -- TypeError if omitted
try:
    adjust_eps_for_splits("TTEK", 1.59, date(2024, 8, 1))
    check("as_of_date required: should have raised TypeError", False)
except TypeError:
    check("as_of_date required: TypeError when omitted", True)


# ═══════════════════════════════════════════════════════════════════════
#  TEST 5: Lookahead-bias prevention
# ═══════════════════════════════════════════════════════════════════════
print(f"\n{'='*70}")
print("  TEST 5: Lookahead-bias prevention")
print("=" * 70)

# TTEK split effective 2024-09-06
# If backtest is simulating 2024-08-15, it must NOT know about the split
adj_before = adjust_eps_for_splits("TTEK", 1.59, date(2024, 8, 1), date(2024, 8, 15))
check("TTEK: as_of BEFORE split -> no adjustment",
      adj_before == 1.59,
      f"Simulating 2024-08-15, split not yet happened. Got ${adj_before:.2f}")

# Same EPS, but as_of AFTER split -> should adjust
adj_after = adjust_eps_for_splits("TTEK", 1.59, date(2024, 8, 1), date(2024, 10, 1))
check("TTEK: as_of AFTER split -> adjusts",
      abs(adj_after - 1.59 / 5) < 0.001,
      f"Simulating 2024-10-01, split known. Got ${adj_after:.4f}")

# WMT split effective 2024-02-23
# Backtest on 2024-01-15: WMT split is future, must not apply
adj_wmt = adjust_eps_for_splits("WMT", 0.17, date(2023, 11, 30), date(2024, 1, 15))
check("WMT: as_of 2024-01-15 (before split) -> no adjustment",
      adj_wmt == 0.17,
      f"Split is Feb 23, simulating Jan 15. Got ${adj_wmt:.2f}")

# Same, but as_of after split
adj_wmt2 = adjust_eps_for_splits("WMT", 0.17, date(2023, 11, 30), date(2024, 3, 1))
check("WMT: as_of 2024-03-01 (after split) -> adjusts",
      abs(adj_wmt2 - 0.17 / 3) < 0.001,
      f"Split is Feb 23, simulating Mar 1. Got ${adj_wmt2:.4f}")

# GOOGL split effective 2022-07-15
# Backtest on 2022-06-01: GOOGL split is future
adj_g = adjust_eps_for_splits("GOOGL", 24.62, date(2022, 4, 27), date(2022, 6, 1))
check("GOOGL: as_of 2022-06-01 (before split) -> no adjustment",
      adj_g == 24.62,
      f"Split is Jul 15, simulating Jun 1. Got ${adj_g:.2f}")

adj_g2 = adjust_eps_for_splits("GOOGL", 24.62, date(2022, 4, 27), date(2022, 8, 1))
check("GOOGL: as_of 2022-08-01 (after split) -> adjusts",
      abs(adj_g2 - 24.62 / 20) < 0.001,
      f"Split is Jul 15, simulating Aug 1. Got ${adj_g2:.4f}")

# Cross-ticker: non-split ticker unaffected regardless of as_of
adj_burl = adjust_eps_for_splits("BURL", 2.50, date(2024, 1, 1), date(2024, 8, 1))
check("BURL: no split regardless of as_of_date",
      adj_burl == 2.50)


# ═══════════════════════════════════════════════════════════════════════
#  TEST 6: Reverse splits -- pre-split EPS must be MULTIPLIED
# ═══════════════════════════════════════════════════════════════════════
print(f"\n{'='*70}")
print("  TEST 6: Reverse splits (NLY 1-for-4, LXP 1-for-5)")
print("=" * 70)

for tk, n in (("NLY", 4), ("LXP", 5)):
    eff = STOCK_SPLITS[tk][0]["effective_date"]
    check(f"{tk}: stored ratio is new/old = 1/{n}",
          STOCK_SPLITS[tk][0]["ratio"] == Fraction(1, n))
    check(f"{tk}: cumulative factor across split = {1/n}",
          get_cumulative_split_factor(tk, eff - timedelta(days=30), eff + timedelta(days=30)) == 1 / n)
    t = df[df["ticker"] == tk].sort_values("earnings_release_date")
    pre = t[t["earnings_release_date"] < eff].dropna(subset=["eps"]).iloc[-1]
    raw = pre["eps"]
    adj = adjust_eps_for_splits(tk, raw, pre["earnings_release_date"], CURRENT)
    check(f"{tk}: pre-split {pre['fiscal_quarter']} EPS {raw} -> {adj} (x{n}, not /{n})",
          abs(adj - raw * n) < 1e-9 and abs(adj) >= abs(raw),
          f"raw={raw}, adjusted={adj}, expected={raw * n}")
    check(f"{tk}: as_of before reverse split -> unchanged",
          adjust_eps_for_splits(tk, raw, pre["earnings_release_date"], eff - timedelta(days=1)) == raw)
    post = t[t["earnings_release_date"] >= eff].dropna(subset=["eps"])
    if len(post):
        p = post.iloc[0]
        check(f"{tk}: first post-split quarter unchanged",
              adjust_eps_for_splits(tk, p["eps"], p["earnings_release_date"], CURRENT) == p["eps"])

# Anchored to the companies' own later filings, which re-present a pre-split
# quarter on the post-split basis. These are the strongest check that date,
# ratio AND direction are right.
ANCHORS = [  # ticker, quarter end, as-filed, value in later filing, later filing
    ("NLY",  date(2022, 6, 30),  0.55, 2.20, "10-Q 0001628280-23-027317"),
    ("CELH", date(2023, 9, 30),  0.89, 0.30, "10-Q 0001341766-24-000093"),
    ("EXLS", date(2023, 6, 30),  1.46, 0.29, "10-Q 0001297989-24-000007"),
    ("CRVL", date(2024, 9, 30),  1.35, 0.45, "10-Q 0001193125-25-269721"),
]
for tk, qed, filed_eps, later_eps, src in ANCHORS:
    r = df[(df["ticker"] == tk) & (df["quarter_end_date"] == qed)].iloc[0]
    adj = adjust_eps_for_splits(tk, r["eps"], r["earnings_release_date"], CURRENT)
    check(f"{tk} {qed}: as-filed {r['eps']} -> adjusted {adj:.4f} = {later_eps} per {src}",
          r["eps"] == filed_eps and round(adj, 2) == later_eps)

# 1/5 has no exact float: 1.23 / 0.2 = 6.1499999999999995. Exact math gives 6.15.
check("LXP: exact arithmetic (1.23 pre-split -> 6.15)",
      adjust_eps_for_splits("LXP", 1.23, date(2025, 8, 1), CURRENT) == 6.15,
      f"got {adjust_eps_for_splits('LXP', 1.23, date(2025, 8, 1), CURRENT)!r}")


# ═══════════════════════════════════════════════════════════════════════
#  TEST 7: Every split matches the dataset's own as-filed EPS basis
# ═══════════════════════════════════════════════════════════════════════
# Implied diluted shares (NI / EPS) must step by the split ratio exactly at
# the effective date as seen through earnings_release_date. A wrong date or
# ratio -- or a row whose release date and EPS basis disagree -- fails here.
print(f"\n{'='*70}")
print("  TEST 7: Split ratio and date vs. the dataset's as-filed EPS")
print("=" * 70)

# NI here is before preferred dividends, so NI/EPS is no share-count proxy for
# a heavy preferred issuer; those are covered by the filing anchors in TEST 6.
PROXY_INVALID = {"NLY": "preferred dividends swamp NI/EPS; anchored in TEST 6"}

for tk in sorted(STOCK_SPLITS):
    if tk in PROXY_INVALID:
        print(f"  SKIP: {tk} -- {PROXY_INVALID[tk]}")
        continue
    for s in STOCK_SPLITS[tk]:
        eff, ratio = s["effective_date"], float(s["ratio"])
        t = df[(df["ticker"] == tk) & df["eps"].notna() & df["net_income"].notna()
               & (df["eps"].abs() >= 0.10)].copy()
        t["impl"] = t["net_income"] / t["eps"]
        t = t[t["impl"] > 0]
        win = timedelta(days=400)
        pre = t[(t["earnings_release_date"] < eff) & (t["earnings_release_date"] >= eff - win)]
        post = t[(t["earnings_release_date"] >= eff) & (t["earnings_release_date"] < eff + win)]
        if len(pre) < 1 or len(post) < 1:
            print(f"  SKIP: {tk} -- not enough rows around {eff}")
            continue
        step = post["impl"].median() / pre["impl"].median()
        # Every row after the split must be on the post-split basis, not just
        # the median. Compare on a log scale (ratios): NI here is before
        # preferred dividends, so NI/EPS overstates shares for NLY-type issuers.
        lr = (post["impl"] / pre["impl"].median()).map(math.log)
        wrong = post[lr.abs() < (lr - math.log(ratio)).abs()]
        check(f"{tk}: shares step x{step:.2f} at {eff} vs ratio {s['ratio']}",
              abs(step / ratio - 1) < 0.15 and wrong.empty,
              f"pre n={len(pre)}, post n={len(post)}, rows still pre-split basis after {eff}: "
              f"{list(wrong['fiscal_quarter'])}")


# ═══════════════════════════════════════════════════════════════════════
#  SUMMARY
# ═══════════════════════════════════════════════════════════════════════
print(f"\n{'='*70}")
print(f"  RESULTS: {passed} passed, {failed} failed")
print(f"{'='*70}")
if failed:
    print(f"\n  {failed} FAILURES")
else:
    print(f"\n  ALL TESTS PASSED")
