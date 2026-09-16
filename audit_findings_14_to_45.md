# Kashif Pipeline Audit — Findings #14–#45
> Static analysis + runtime-verified execution | August 2026

---

## Static Analysis Findings (#14–#29)

### #14 | Medium | `_build_swing_sequence` drops swings without price comparison
- **File:** vcp_detection.py:211
- **Issue:** `cleaned.pop()` on consecutive same-type swings keeps the later one regardless of price. Could discard the true peak and keep a lower one.
- **Fix:** Compare prices and keep the more extreme swing (higher for peaks, lower for troughs).

### #15 | Low | Leader prices lack DatetimeIndex alignment
- **File:** kashif_strategy.py:362
- **Issue:** Leader price Series are built with plain integer indices. Tickers that started trading on different dates have misaligned indices — bar 0 for one ticker is a different calendar date than bar 0 for another.
- **Fix:** Use actual dates as the index when building leader price Series.

### #16 | Medium | History buffer maxlen=260 too small for 65-week VCP bases
- **File:** kashif_strategy.py:133
- **Issue:** `HISTORY_BUFFER_MAXLEN=260` but `BASE_DURATION_MAX_TRADING_DAYS=325`. The weekly resample gets ~52 weeks of data when a valid VCP base could span 65 weeks.
- **Fix:** Increase `HISTORY_BUFFER_MAXLEN` to at least 330.

### #17 | Medium | `exit_candidates` flag set but never acted on
- **File:** kashif_strategy.py:678
- **Issue:** Largest-decline exit signal sets `self.exit_candidates[d] = True` and increments a counter, but nothing reads the flag to place a sell order. The signal is purely decorative.
- **Fix:** Wire the flag to actually place sell orders when set, or remove the dead code.

### #18 | Low | Rolling min comparison assumes no bar gaps
- **File:** kashif_strategy.py:396
- **Issue:** `_higher_low_flag` uses `iloc[-1]` vs `iloc[-1 - window]` on integer-indexed Series. Ticker suspensions cause the comparison to span a different calendar period than intended.
- **Fix:** Use date-aware indexing or document the assumption.

### #19 | High | `log2(peg)` crashes on PEG <= 0 — RUNTIME CONFIRMED
- **File:** fundamentals_screen.py:160
- **Issue:** `math.log2(peg)` raises `ValueError: math domain error` when PEG is zero or negative. Turnaround companies (negative earnings) commonly have negative PEG.
- **Fix:** Add guard: `if peg <= 0: return 0.0` (or a defined penalty value).

### #20 | High | No guard on empty `eps` list — RUNTIME CONFIRMED
- **File:** fundamentals_screen.py:248
- **Issue:** `score_earnings_growth(eps[-1], category)` throws `IndexError: list index out of range` when `eps_yoy_growth_by_quarter` is an empty list. No length guard exists.
- **Fix:** Add `if not eps: return 0.0` before accessing `eps[-1]`.

### #21 | Low | None-to-0.0 cast for excluded screen (latent)
- **File:** fundamentals_screen.py:269
- **Issue:** `scores_bool["code_33"]` can be `None` (excluded), but the numeric conversion `1.0 if x else 0.0` treats it as 0.0. Harmless now because excluded weight is zero, but would break if exclusion logic changes.
- **Fix:** Explicitly handle `None` before the boolean conversion.

### #22 | Low | `detect_source_flip` ignores its first argument
- **File:** fundamentals_screen.py:53
- **Issue:** Function signature is `(sources, window)` but only `window` is used. The full `sources` list is passed and silently ignored.
- **Fix:** Either use the `sources` parameter or remove it from the signature.

### #23 | High | RS snapshot recomputed ~196x per bar (performance bomb)
- **File:** kashif_strategy.py:360, 446
- **Issue:** Each `_evaluate_entry_pipeline` call recomputes the full RS snapshot, iterating all tickers' 253-bar history. With 195 tickers and 490 bars, that's ~96,000 RS computations per backtest.
- **Fix:** Cache RS snapshot once per bar in `next()`, reuse across all tickers. Saves 99.5% of RS work.

### #24 | High | New-high-low ratio condition structurally always False — RUNTIME CONFIRMED
- **File:** kashif_strategy.py:401-418
- **Issue:** `_new_high_low_ratio_favorable_snapshot` builds `pd.Series([sum(highs)] * 22)` — a constant series. Then `ratio > ratio.shift(21)` is always False because a constant equals itself. This condition can never pass.
- **Fix:** Store daily high/low counts as a running time series, not a single-point snapshot repeated 22 times.

### #25 | Medium | Breakeven stop uses original entry, not blended cost basis
- **File:** kashif_strategy.py:690
- **Issue:** Add-on buys are allowed (via `_guard_no_averaging_down`), but the breakeven stop stays pinned to the first entry's price. The stop could be far below the blended average, creating unintended risk exposure.
- **Fix:** Recalculate breakeven stop from the volume-weighted average entry price after each add-on.

### #26 | High | Add-on buys create orphaned stop orders
- **File:** kashif_strategy.py:720-727
- **Issue:** When a second buy fills for the same ticker, `self.stop_order[d]` is overwritten with the new stop, but the first stop is still live in backtrader. Two competing stops exist — the first can fill unexpectedly, partially closing the position.
- **Fix:** Cancel the existing stop before placing the new one: `self.cancel(self.stop_order[d])`.

### #27 | Medium | Calendar vs trading days in forward returns
- **File:** backfill_catalyst_returns.py:115
- **Issue:** `timedelta(days=10)` adds calendar days. 10 calendar days ≈ 7 trading days. Catalyst accuracy metrics are systematically mis-measured.
- **Fix:** Use `pd.bdate_range` or count actual trading bars.

### #28 | Low | Base price may shift to next trading day
- **File:** backfill_catalyst_returns.py:91
- **Issue:** `_fetch_close_on_or_after` finds the first available bar, which may be 1-3 days after the intended date. Combined with calendar-day offsets, returns span inconsistent periods.
- **Fix:** Document this behavior or snap to the nearest prior trading day.

### #29 | Medium | Track record grows unboundedly with duplicates — RUNTIME CONFIRMED
- **File:** catalyst_check.py:906
- **Issue:** Each `catalyst_check()` call appends to `catalyst_track_record.jsonl` unconditionally. After just a few test runs, COMI already has 3 duplicate entries for the same date. A full backtest would write ~95,550 lines per run.
- **Fix:** Dedup by (ticker, date) before appending, or write to a fresh file per run.

---

## Runtime-Discovered Findings (#30–#45)

### #30 | CRITICAL | Regime gate `new_high_low_ratio_favorable` always returns False — RUNTIME CONFIRMED
- **File:** kashif_strategy.py:414
- **Issue:** `_new_high_low_ratio_favorable_snapshot` builds a constant series by repeating today's single snapshot 22 times: `pd.Series([sum(highs)] * 22)`. Then `new_high_low_ratio_favorable()` checks `ratio > ratio.shift(21)`. A constant series compared to itself shifted by 21 is always equal, never greater. Verified: False on every bar across a 490-bar run with 5 tickers. Since the regime gate is an AND of 3 conditions, the gate never opens, and no ticker ever reaches the hard filter.
- **Fix:** Store daily high/low counts as a running time series (append one value per bar), so the ratio comparison can detect real change over time.

### #31 | CRITICAL | VCP weekly base validation always rejects — monotonicity impossible with 1 contraction — RUNTIME CONFIRMED
- **File:** vcp_detection.py:440
- **Issue:** With 2 years of data (~105 weekly bars), `detect_swings` finds only 3-4 peaks and 3-4 troughs, producing bases with 1 contraction each. `rule_a` requires `depths[-1] <= depths[0] * 0.75` — with a single contraction, `depths[-1] == depths[0]`, so this demands `depth <= depth * 0.75`, which is impossible for any positive depth. All 5 test tickers return `WEEKLY_BASE_REJECTED:MONOTONICITY_FAILED`. Even if the regime gate were fixed, entry timing blocks every ticker.
- **Fix:** Skip `rule_a` when `len(depths) == 1` (a single contraction has no "final vs first" to compare), or lower `CONTRACTION_COUNT_MIN` to 1 for weekly bases.

### #32 | Medium | Regime gate requires 22+ tickers with 253+ bars of history
- **File:** kashif_strategy.py:412
- **Issue:** `_new_high_low_ratio_favorable_snapshot` returns False early if `len(highs) < 22`, meaning fewer than 22 tickers must have 253+ bars. Any subset test or demo run with fewer than 22 viable tickers can never open the gate.
- **Fix:** Document the minimum universe requirement or add a bypass for small test runs.

### #33 | High | `compute_peg_modifier(peg)` crashes on PEG <= 0 — RUNTIME CONFIRMED
- **File:** fundamentals_screen.py:160
- **Issue:** `math.log2(peg)` raises `ValueError: math domain error` when PEG is zero or negative. Turnaround companies (negative earnings) commonly have negative PEG. Tested: PEG=0.0 and PEG=-0.5 both crash.
- **Fix:** Guard with `if peg <= 0: return 0.0` before the log2 call.

### #34 | High | `compute_composite` crashes on empty `eps` list — RUNTIME CONFIRMED
- **File:** fundamentals_screen.py:248
- **Issue:** `score_earnings_growth(eps[-1], category)` throws `IndexError: list index out of range` when `eps_yoy_growth_by_quarter` is an empty list.
- **Fix:** Add `if not eps: return 0.0` at the top of the function.

### #35 | High | `compute_composite` crashes when `margin_by_quarter` is None — RUNTIME CONFIRMED
- **File:** fundamentals_screen.py:104
- **Issue:** `score_code_33` calls `len(margin_by_quarter)` which throws `TypeError: object of type 'NoneType' has no len()`. The None check only covers `revenue_yoy_growth_by_quarter`, not margin.
- **Fix:** Add `if margin_by_quarter is None: return 0.0` guard in `score_code_33`.

### #36 | High | `_compute_rs_snapshot` recomputed ~196x per bar — BENCHMARKED
- **File:** kashif_strategy.py:446
- **Issue:** Each call iterates all tickers' 253-bar history and builds a DataFrame. With 195 tickers and 490 bars, that's ~96,000 RS computations per backtest. Benchmarked: even with 5 tickers, the hard filter alone takes ~4ms per ticker per bar. At full scale (195 tickers x 490 bars), the hard filter alone would take ~7 minutes.
- **Fix:** Move RS computation to `next()` before the per-ticker loop; cache once per bar and reuse across all tickers.

### #37 | High | `compute_indicators` rebuilds all rolling windows from scratch every bar — BENCHMARKED: 1.6ms/call
- **File:** kashif_strategy.py:443-445
- **Issue:** Each `_evaluate_entry_pipeline` call converts the entire 260-bar history deque to a DataFrame and recomputes all 7 rolling windows (SMA-50, SMA-150, SMA-200, 52-week high/low, 252-day return, SMA-200 slope). At scale: 195 x 490 x 1.6ms = ~2.5 minutes of pure indicator recomputation.
- **Fix:** Compute indicators once per ticker per bar and cache the result, or use incremental rolling calculations.

### #38 | CRITICAL | Catalyst API calls per-ticker-per-bar cause timeouts at scale — RUNTIME CONFIRMED
- **File:** catalyst_check.py
- **Issue:** When regime gate is forced open, tickers passing hard filter hit `catalyst_check()` which makes live HTTP calls to ArabFinance + Google News + Gemini API per ticker per bar. A 5-ticker run exceeded the 10-minute timeout. At full scale with 195 tickers, even a few passing bars would generate thousands of API calls.
- **Fix:** Cache catalyst results by (ticker, date) so the same ticker on the same bar doesn't re-fetch. In backtesting mode, either disable live calls entirely or use a pre-computed cache.

### #39 | Medium | 29 of 224 EGX tickers return zero data from yfinance — RUNTIME CONFIRMED
- **File:** egx_tickers.py
- **Issue:** These tickers return 0 bars: QNBE, VLMR, VLMRA, VALU, TAQA, UBEE, BONY, KORA, ACAP, NAPR, GOUR, CRST, ACTF, GTWL, ALRA, NARE, PHGC, GPIM, GGRN, AMII, AIDC, GTEX, POCO, KRDI, TANM, TYCN, AIHC, DGTZ, CPME. Loading these as backtrader feeds without pre-filtering would crash or produce undefined behavior.
- **Fix:** Add a pre-filter step that removes tickers with zero data before attaching feeds to Cerebro.

### #40 | Medium | yfinance has quarterly income data for ~65% of EGX tickers — fundamentals_screen IS wireable
- **File:** fundamentals_screen.py
- **Issue:** COMI returns Net Income, Total Revenue, Basic EPS, and Diluted EPS for 7 quarters via `quarterly_income_stmt`. However, there are NaN gaps (e.g., EPS missing for one quarter). ~35% of tickers have no quarterly data at all. The fundamentals screen can be wired but needs robust NaN handling.
- **Fix:** Fetch `quarterly_income_stmt`, handle NaN gaps with interpolation or skip, and pass to `compute_composite`.

### #41 | High | `google-generativeai` SDK is deprecated — FutureWarning on every import — RUNTIME CONFIRMED
- **File:** catalyst_check.py:92
- **Issue:** The package (v0.8.6) prints a deprecation warning: "All support for the `google.generativeai` package has ended." The replacement is `google.genai`. This SDK could stop working at any time with a Google server-side change.
- **Fix:** Migrate from `import google.generativeai as genai` to `from google import genai` (new SDK).

### #42 | High | `score_with_model` is NOT a stub — makes real Gemini API calls — RUNTIME CONFIRMED
- **File:** catalyst_check.py:686
- **Issue:** The strategy docstring says "score_with_model() is itself still a deliberate stub — always NEUTRAL." But the actual code makes live calls to Gemini 3.6 Flash via the deprecated SDK, and successfully returned `STRONG_POSITIVE` for COMI in testing. The docstring is stale — the model is real and costs money per call.
- **Fix:** Update the strategy docstring to reflect reality. Add cost tracking/logging for API calls.

### #43 | Medium | `pytest` not installed — 9 test files cannot run via standard test runner — RUNTIME CONFIRMED
- **File:** (project-wide)
- **Issue:** All test files are standalone scripts (not pytest test cases), and `pytest` is not installed. Tests pass when run directly with `python test_*.py`, but there's no `requirements.txt` or `requirements-dev.txt` listing any dependencies, and no way to run the full test suite in one command.
- **Fix:** Add `pytest` to dev dependencies. Convert test scripts to proper pytest format or add a `run_all_tests.py` wrapper.

### #44 | Medium | Track record file grows with duplicates across runs — RUNTIME CONFIRMED
- **File:** catalyst_check.py:906
- **Issue:** `catalyst_track_record.jsonl` already has 3 duplicate entries for COMI (same date, different runs) after just a few test invocations. A full backtest would accumulate ~95,550 lines per run with no deduplication.
- **Fix:** Dedup by (ticker, date, score) before appending, or write to a timestamped file per run.

### #45 | Low | Decision receipts never created in backtrader run — RUNTIME CONFIRMED
- **File:** kashif_strategy.py:704
- **Issue:** With the regime gate closed, every ticker is rejected at the gate. The regime-closed receipt IS generated, but the path `decision_receipts_dir` defaults to `"."` and the receipts may be written in whatever CWD launched the script. No files appeared in the project root after a full 490-bar run.
- **Fix:** Use an explicit output directory (e.g., `daily_ops_log/`) for decision receipts, and verify file creation in tests.

---

## Summary by Severity

| Severity | Count | Finding Numbers |
|----------|-------|-----------------|
| CRITICAL | 3     | #30, #31, #38   |
| High     | 10    | #19, #20, #23, #24, #26, #33, #34, #35, #36, #37, #41, #42 |
| Medium   | 10    | #16, #17, #25, #27, #29, #32, #39, #40, #43, #44 |
| Low      | 9     | #14, #15, #18, #21, #22, #28, #45 |

## Recommended Fix Order (minimum path to first trade signal)

1. Fix regime gate (#30) — store daily high/low counts as a running time series
2. Fix VCP monotonicity (#31) — skip rule_a for single-contraction bases
3. Write a runner script (#4) — Cerebro + EGX data fetch + pre-filter + strategy + sizer
4. Wire fundamentals_screen (#2) — fetch quarterly_income_stmt, handle NaN, call compute_composite
5. Set `qualifies = True` (#1) — when all pipeline stages pass
6. Cache RS snapshot once per bar (#36) — move to next() before per-ticker loop
7. Guard fundamentals crashes (#33, #34, #35) — PEG <= 0, empty eps, None margin
8. Add .gitignore and requirements.txt (#5, #6)
