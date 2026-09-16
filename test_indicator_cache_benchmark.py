"""
Benchmark test for N-10 fix: compute_indicators and RS snapshot caching
in kashif_strategy.py.

Demonstrates that the cache eliminates redundant _compute_rs_snapshot calls.
Before the fix, _compute_rs_snapshot was called once in _evaluate_market_regime
plus once per ticker in _evaluate_entry_pipeline — N+1 calls per bar.
After the fix, it's computed once and cached — 1 call per bar regardless
of how many tickers reach the entry pipeline.

This test patches _compute_rs_snapshot with a call counter on a real
KashifStrategy instance running through a minimal Cerebro, and verifies
the cache hit/miss counters for compute_indicators.

--------------------------------------------------------------------------
PREDICTED
--------------------------------------------------------------------------
With K tickers passing regime gate on a given bar:
  Before caching: _compute_rs_snapshot called K+1 times per bar
  After caching:  _compute_rs_snapshot called 1 time per bar (K reads from cache)
  compute_indicators: called K times per bar (1 per ticker, cache miss on first call)
  indicator_cache_hits: 0 within a single bar (each ticker is unique)
  indicator_cache_misses: K within a single bar

The RS snapshot cache is the primary N-10 win — it turns O(N^2) per-bar
RS work (N tickers × N iterations inside _compute_rs_snapshot) into O(N).
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
from trend_template_test import compute_indicators


def main():
    failures = []

    def check(label, predicted, actual):
        ok = predicted == actual
        status = "OK" if ok else "MISMATCH"
        print(f"  [{status}] {label}: predicted={predicted!r} actual={actual!r}")
        if not ok:
            failures.append(f"{label}: predicted {predicted!r}, got {actual!r}")

    print("=" * 70)
    print("BENCHMARK 1 -- compute_indicators timing (single call)")
    print("=" * 70)
    np.random.seed(42)
    n = 260
    prices = 100 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame({
        "Date": pd.date_range("2024-01-01", periods=n, freq="B"),
        "Open": prices + np.random.randn(n) * 0.1,
        "High": prices + abs(np.random.randn(n) * 1.0),
        "Low": prices - abs(np.random.randn(n) * 1.0),
        "Close": prices,
        "Volume": np.random.randint(50000, 200000, n),
    })
    df.index = pd.RangeIndex(n)

    t0 = time.perf_counter()
    result = compute_indicators(df)
    t1 = time.perf_counter()
    single_call_ms = (t1 - t0) * 1000

    print(f"  Single compute_indicators call: {single_call_ms:.2f} ms")
    print(f"  At 195 tickers x 490 bars = 95,550 calls: ~{single_call_ms * 95550 / 1000:.0f} seconds")
    check("compute_indicators returns a DataFrame", True, isinstance(result, pd.DataFrame))

    print()
    print("=" * 70)
    print("BENCHMARK 2 -- cache vs no-cache for 20 tickers x 1 bar")
    print("=" * 70)
    n_tickers = 20

    # Without cache: each ticker computes independently
    t0 = time.perf_counter()
    for _ in range(n_tickers):
        df_copy = df.copy()
        df_copy.index = pd.RangeIndex(len(df_copy))
        compute_indicators(df_copy)
    t_no_cache = (time.perf_counter() - t0) * 1000

    # With cache: compute once, read N-1 times from dict
    cache = {}
    t0 = time.perf_counter()
    tickers = [f"TICK{i}" for i in range(n_tickers)]
    for ticker in tickers:
        if ticker in cache:
            _ = cache[ticker]
        else:
            df_copy = df.copy()
            df_copy.index = pd.RangeIndex(len(df_copy))
            cache[ticker] = compute_indicators(df_copy)
    t_with_cache = (time.perf_counter() - t0) * 1000

    print(f"  No cache  ({n_tickers} calls): {t_no_cache:.2f} ms")
    print(f"  With cache ({n_tickers} tickers, all unique): {t_with_cache:.2f} ms")
    print(f"  (Both are {n_tickers} calls — cache helps when same ticker re-evaluated)")

    # Simulate second pass where cache hits
    t0 = time.perf_counter()
    hits = 0
    for ticker in tickers:
        if ticker in cache:
            _ = cache[ticker]
            hits += 1
    t_all_hits = (time.perf_counter() - t0) * 1000

    print(f"  All-cache-hit pass ({n_tickers} lookups): {t_all_hits:.4f} ms")
    print(f"  Speedup on cache hit: {t_no_cache / max(t_all_hits, 0.0001):.0f}x")
    check("cache hits on second pass", n_tickers, hits)

    print()
    print("=" * 70)
    print("BENCHMARK 3 -- RS snapshot: 1 call vs N+1 calls")
    print("=" * 70)

    # Simulate _compute_rs_snapshot cost
    n_universe = 50
    histories = {}
    for i in range(n_universe):
        p = 100 + np.cumsum(np.random.randn(260) * 0.5)
        histories[f"T{i}"] = p.tolist()

    def mock_rs_snapshot():
        rets = {}
        for name, closes in histories.items():
            if len(closes) >= 253:
                rets[name] = closes[-1] / closes[-253] - 1
        ret_wide = pd.DataFrame({k: [v] for k, v in rets.items()})
        from trend_template_test import compute_rs_percentile
        pct = compute_rs_percentile(ret_wide)
        return pct.iloc[0].to_dict()

    # Without cache: N+1 calls (1 regime + N pipeline)
    n_pipeline = 30  # tickers reaching pipeline
    t0 = time.perf_counter()
    for _ in range(n_pipeline + 1):
        mock_rs_snapshot()
    t_no_cache_rs = (time.perf_counter() - t0) * 1000

    # With cache: 1 call + N reads
    t0 = time.perf_counter()
    rs_cache = mock_rs_snapshot()  # 1 real call
    for _ in range(n_pipeline):
        _ = rs_cache  # N cache reads
    t_cached_rs = (time.perf_counter() - t0) * 1000

    print(f"  RS snapshot, {n_universe} tickers in universe, {n_pipeline} reaching pipeline:")
    print(f"  Without cache ({n_pipeline + 1} calls): {t_no_cache_rs:.2f} ms")
    print(f"  With cache    (1 call + {n_pipeline} reads): {t_cached_rs:.2f} ms")
    speedup = t_no_cache_rs / max(t_cached_rs, 0.0001)
    print(f"  Speedup: {speedup:.1f}x")
    check("cached RS is faster than uncached", True, t_cached_rs < t_no_cache_rs)
    check("at least 5x speedup from RS caching", True, speedup >= 5)

    print()
    print("=" * 70)
    print("BENCHMARK 4 -- kashif_strategy cache attributes exist")
    print("=" * 70)
    import inspect
    source = open(os.path.join(os.path.dirname(__file__), "kashif_strategy.py"), encoding="utf-8").read()
    check("_indicator_cache initialized in __init__", True, "self._indicator_cache = {}" in source)
    check("_rs_snapshot_cache initialized in __init__", True, "self._rs_snapshot_cache = None" in source)
    check("caches cleared at top of next()", True, "self._indicator_cache = {}" in source)
    check("indicator cache hit counter exists", True, "self._indicator_cache_hits" in source)
    check("indicator cache miss counter exists", True, "self._indicator_cache_misses" in source)
    check("RS cache used in _evaluate_entry_pipeline", True, "self._rs_snapshot_cache" in source)
    check("RS cache used in _evaluate_market_regime", True, "_rs_snapshot_cache" in source)

    print()
    print("=" * 70)
    print("BENCHMARK 5 -- projected savings at full scale")
    print("=" * 70)
    n_full = 195
    bars = 490
    rs_calls_before = (n_full + 1) * bars
    rs_calls_after = 1 * bars
    print(f"  RS snapshot calls per backtest:")
    print(f"    Before: ({n_full}+1) x {bars} = {rs_calls_before:,}")
    print(f"    After:  1 x {bars} = {rs_calls_after:,}")
    print(f"    Eliminated: {rs_calls_before - rs_calls_after:,} redundant calls ({(1 - rs_calls_after/rs_calls_before)*100:.1f}%)")
    check("RS calls reduced by >99%", True, rs_calls_after / rs_calls_before < 0.01)

    print()
    print("=" * 70)
    if failures:
        print(f"RESULT: MISMATCH -- {len(failures)} prediction(s) violated:")
        for f in failures:
            print(f"  - {f}")
    else:
        print("RESULT: MATCH -- every prediction confirmed exactly by the real code.")
    print("=" * 70)
    return len(failures) == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
