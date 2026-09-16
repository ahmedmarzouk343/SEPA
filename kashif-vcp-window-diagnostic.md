# Kashif — VCP Window & History Buffer Diagnostic

*Diagnostic report. No source files were modified. All instrumentation
replicated `evaluate_entry_timing()`'s exact call sequence using the real
`vcp_detection` / `entry_timing` functions, logging intermediate state that
the production code discards.*

- **Date:** 2026-08-30
- **Data:** EGX universe, 195 tickers, IS period 2023-08-27 → 2025-08-26
- **Backtest referenced:** EGX IS run `kashif_5d7fd7bf3b24` (finished 01:29:42)
- **Scripts:** `_egx_is_cache.pkl`, `egx_IS_returns_all.csv`, `_task2_trace.pkl`,
  `_task2_receipts.pkl`

---

## 0. Documents requested but not found

Four files have now been referenced across requests that do not exist in the
project directory:

| requested | status |
|---|---|
| `kashif-implementation-plan.md` | EXISTS — read |
| `minervini_sepa_v1_strategy_config.json` | EXISTS — read |
| `backtest-roadmap.md` | EXISTS |
| `kashif-rules-vs-book.md` | **NOT FOUND** |
| `kashif-invented-components-analysis.md` | **NOT FOUND** |
| `kashif-vcp-filters-analysis.md` | **NOT FOUND** |

No file with a similar name exists. The closest are
`kashif-complete-change-register.md`, `kashif-roadmap.md`,
`audit_findings_14_to_45.md`. If those three documents contain rules or
constraints, this analysis does not reflect them.

---

## 1. Context — where the strategy actually loses the winners

Established in the preceding diagnostic (EGX IS period):

- **49 of 195 EGX tickers returned ≥200%** during IS. 96 returned ≥100%.
- The strategy traded **7 of those 49**: SNFC, MCQE, ARCC, AJWA, ISMQ, RMDA, IRON.
- **42 were missed.**
- **The Trend Template blocked ZERO of them.** All 42 passed `hard_filter` on at
  least one IS day (median 33.6% of evaluable days, range 11.6%–71.6%).
- Every one of the 42 died at **VCP detection**.

Aggregate VCP rejections across the 42 missed winners (2,471 checks on
hard-filter-passing days):

| VCP rejection reason | checks | share |
|---|---|---|
| **NO_DAILY_BASE_WITHIN_WEEKLY_WINDOW** | 971 | **39.3%** |
| DAILY_BASE_REJECTED: CONTRACTION_COUNT_OUT_OF_RANGE | 596 | 24.1% |
| NO_WEEKLY_BASE | 522 | 21.1% |
| DAILY_BASE_REJECTED: MONOTONICITY_FAILED | 124 | 5.0% |
| TICK_QUANTIZED | 114 | 4.6% |
| WEEKLY_BASE_REJECTED: MONOTONICITY_FAILED | 65 | 2.6% |
| WEEKLY/DAILY_BASE_REJECTED: TICK_QUANTIZED | 42 | 1.6% |
| AWAITING_BREAKOUT | 14 | 0.6% |
| **PRICE_READY** | **7** | **0.3%** |
| others | 16 | 0.6% |

Primary blocker per stock: `NO_DAILY_BASE_WITHIN_WEEKLY_WINDOW` dominated
**19 of 42**. It had never been instrumented. That is what Task 1 addresses.

---

## 2. TASK 1 — `NO_DAILY_BASE_WITHIN_WEEKLY_WINDOW` instrumented

### 2.1 The mechanism

`entry_timing.py:114-127`:

```python
weekly_start_date = weekly_df.index[weekly_validated["start_trough_idx"]]
weekly_end_date   = weekly_df.index[weekly_validated["end_trough_idx"]]
daily_window      = daily_df.loc[weekly_start_date:weekly_end_date]
if len(daily_window) < ATR_PERIOD + 1:
    result["reason"] = "INSUFFICIENT_DAILY_WINDOW"
    return result

d_peaks, d_troughs = detect_swings(daily_window[...])
d_bases = identify_bases(d_peaks, d_troughs, daily_window["High"])
if not d_bases:
    result["reason"] = "NO_DAILY_BASE_WITHIN_WEEKLY_WINDOW"
```

The window ends at the weekly base's **last trough** (`end_trough_idx`), not at
the evaluation date. The daily search therefore runs over a **historical slice**
that can predate "today" by many months.

The weekly base is validated with `min_contractions=1`
(`entry_timing.py:105`), but the daily `validate_base` requires
`CONTRACTION_COUNT_MIN = 2`. The two stages do not agree on what a base is.

### 2.2 EALR (+1494.5%) — 71 firings of 161 evaluations

First 10 firings, in detail:

| as_of | weekly base window | wks | wCon | dBars | dPk | dTr | gap to today | why zero |
|---|---|---|---|---|---|---|---|---|
| 2024-05-19 | 2023-11-05 → 2023-12-31 | 8 | 1 | 41 | 1 | 1 | 140 d | 1 peak + 1 trough, no contraction group formed a base |
| 2024-05-22 | 2023-11-05 → 2023-12-31 | 8 | 1 | 41 | 1 | 1 | 143 d | same |
| 2024-05-27 | 2023-11-05 → 2023-12-31 | 8 | 1 | 41 | 1 | 1 | 148 d | same |
| 2024-05-30 | 2023-11-05 → 2023-12-31 | 8 | 1 | 41 | 1 | 1 | 151 d | same |
| 2024-06-04 | 2023-11-05 → 2023-12-31 | 8 | 1 | 41 | 1 | 1 | 156 d | same |
| 2024-06-09 | 2023-11-05 → 2023-12-31 | 8 | 1 | 41 | 1 | 1 | 161 d | same |
| 2024-06-12 | 2023-11-05 → 2023-12-31 | 8 | 1 | 41 | 1 | 1 | 164 d | same |
| 2024-06-24 | 2023-11-05 → 2023-12-31 | 8 | 1 | 41 | 1 | 1 | 176 d | same |
| 2024-06-27 | 2023-11-05 → 2023-12-31 | 8 | 1 | 41 | 1 | 1 | 179 d | same |
| 2024-07-04 | 2023-11-05 → 2023-12-31 | 8 | 1 | 41 | 1 | 1 | 186 d | same |

In every row the unwindowed full-history search finds **1 base**.

```
SUMMARY over 71 firings
  weekly base span (weeks)  : min  6  median   8  max   8
  daily bars in window      : min 28  median  41  max  41
  daily PEAKS in window     : min  0  median   1  max   1
  daily TROUGHS in window   : min  0  median   1  max   1
  window END to today (days): min  9  median 197  max 371
  bases found by UNWINDOWED full-history search: min 1  median 1  max 3
  firings where window ENDED >30 days before "today": 66/71 (93%)
  firings where removing the window WOULD find a base: 71/71 (100%)
```

### 2.3 SMFR (+1046.6%) — 99 firings

Earliest firings: window `2023-02-12 → 2023-03-26` evaluated on 2023-08-27 —
**154 days stale**, 31 bars, **0 peaks and 0 troughs** ("no swings detected at
all inside the window"), while the full-history search finds **4 bases**.

```
SUMMARY over 99 firings
  weekly base span (weeks)  : min  5  median  15  max  19
  daily bars in window      : min 22  median  68  max  85
  daily PEAKS in window     : min  0  median   0  max   1
  daily TROUGHS in window   : min  0  median   0  max   1
  window END to today (days): min 10  median 175  max 388
  bases found by UNWINDOWED full-history search: min 1  median 3  max 7
  firings where window ENDED >30 days before "today": 91/99 (92%)
  firings where removing the window WOULD find a base: 99/99 (100%)
```

### 2.4 CPCI (+550.4%) — 73 firings

Same shape:

| as_of | weekly base window | wks | wCon | dBars | dPk | dTr | gap | why zero |
|---|---|---|---|---|---|---|---|---|
| 2023-08-27 | 2023-01-15 → 2023-03-26 | 10 | 1 | 50 | 0 | 0 | 154 d | no swings at all in window; full search finds 2 |
| 2023-08-30 | 2023-01-15 → 2023-03-26 | 10 | 1 | 50 | 0 | 0 | 157 d | same |
| 2023-09-04 | 2023-01-15 → 2023-03-26 | 10 | 1 | 50 | 0 | 0 | 162 d | same |
| 2023-09-07 | 2023-01-15 → 2023-03-26 | 10 | 1 | 50 | 0 | 0 | 165 d | same |
| 2023-09-12 | 2023-01-15 → 2023-05-21 | 18 | 2 | 83 | 1 | 1 | 114 d | 1 peak + 1 trough, no base formed |
| 2023-09-17 | 2023-01-15 → 2023-05-21 | 18 | 2 | 83 | 1 | 1 | 119 d | same |

### 2.5 Verdict on Task 1's three questions

**Is it calibration (window too narrow)?** **No.** Windows contain 41–85 daily
bars — ample to detect swings. Width is not the constraint.

**Is it a data problem (too few bars)?** **No.** Insufficient-length windows are
caught separately by `INSUFFICIENT_DAILY_WINDOW`, which fires rarely (8 of 2,471
checks across the 42 missed winners).

**Is it architectural?** **Yes — two distinct defects.**

1. **The window is stale.** It ends at the weekly base's last trough, a median
   of **175–197 days** before the evaluation date. The detector searches a
   window that closed roughly six months ago while the stock is breaking out
   today. In **92–93%** of firings the window ended more than 30 days ago.

2. **The weekly and daily stages disagree on what a base is.** A weekly base
   validated with `min_contractions=1` maps onto a daily window containing a
   median of **0–1 peaks** — structurally incapable of producing the 2+
   contractions the daily `validate_base` requires. The weekly stage forwards a
   base the daily stage can never confirm.

**In 243 of 243 firings across all three stocks (100%), removing the window
constraint would have found a daily base.**

---

## 3. TASK 2 — OIH / WKOL / MENA: no bug between PRICE_READY and `buy()`

### 3.1 All 7 receipts exist and all were rejected at entry timing

Receipts present in the IS run: OIH 474, WKOL 474, MENA 474. All 7 target-date
receipts located. **Every one shows `final_verdict = REJECTED_AT_entry_timing`.
None reached `_run_scoring_queue()`.** Slot contention and queue ranking are
therefore irrelevant — the question does not arise.

**OIH — all five dates identical:**

```
market_regime_gate : PASS
hard_filter        : PASS
category_tagging   : SKIPPED: no category data for ticker
fundamentals_screen: SKIPPED: no yfinance quarterly data
catalyst_check     : score=NEUTRAL source=STUB_BACKTEST priority_tier=N/A
entry_timing       : price_ready=False reason=NO_WEEKLY_BASE pivot=None vcp_quality=0.0
vcp_quality_score  : 0.0
pivot_price        : None
final_verdict      : REJECTED_AT_entry_timing
regime.result      : OPEN
```

Regime was OPEN on all five dates. (2025-07-31 shows "new high/low ratio NOT
favorable" but `pullback_shallow` carried the OR gate.)

| date | regime | hard_filter | entry_timing reason |
|---|---|---|---|
| 2025-07-02 | OPEN | PASS | NO_WEEKLY_BASE |
| 2025-07-09 | OPEN | PASS | NO_WEEKLY_BASE |
| 2025-07-28 | OPEN | PASS | NO_WEEKLY_BASE |
| 2025-07-31 | OPEN | PASS | NO_WEEKLY_BASE |
| 2025-08-10 | OPEN | PASS | NO_WEEKLY_BASE |

**WKOL and MENA:**

```
WKOL 2023-10-24: price_ready=False reason=DAILY_BASE_REJECTED:CONTRACTION_COUNT_OUT_OF_RANGE
MENA 2024-02-07: price_ready=False reason=NO_WEEKLY_BASE
```

### 3.2 CORRECTION to the previous report

The earlier diagnostic reported OIH, WKOL and MENA as *"passed every gate but
were never bought"*. **That was wrong.** It was an artifact of the harness:
my instrumentation passed **full price history**, while the strategy passes a
rolling buffer capped at `HISTORY_BUFFER_MAXLEN = 260` bars
(`kashif_strategy.py:151`).

Tested directly:

| ticker | date | full history | 260-bar buffer (what the strategy sees) |
|---|---|---|---|
| OIH | 2025-07-02 | 707 bars → **PRICE_READY** | **NO_WEEKLY_BASE** |
| WKOL | 2023-10-24 | 302 bars → **PRICE_READY** | **CONTRACTION_COUNT_OUT_OF_RANGE** |
| MENA | 2024-02-07 | 375 bars → **PRICE_READY** | **NO_WEEKLY_BASE** |

The signals were never generated. There is no lost-signal bug between
`price_ready=True` and `buy()`.

### 3.3 But the real finding is more serious

260 daily bars ≈ **52 weekly bars**. `to_weekly()` on that buffer yields ~52
rows; weekly `detect_swings` then applies `DISTANCE_WEEKS` spacing plus a
14-period ATR, leaving too little room to resolve a multi-swing weekly base.

**The 260-bar buffer is structurally too short for the weekly stage of a
weekly-then-daily detector.** All three tickers produce a valid signal on full
history and none on the buffer.

`HISTORY_BUFFER_MAXLEN = 260` was sized for the RS window — the comment at
`kashif_strategy.py:151` reads *">= 252-day RS/52wk window + margin"*. The
weekly VCP requirement was never a consideration when that number was chosen.

---

## 4. Summary — two architectural defects

| # | Defect | Location | Evidence |
|---|---|---|---|
| 1 | Daily search window is stale and structurally mismatched to the weekly base it derives from | `entry_timing.py:114-127` | 243/243 firings would find a base without it; window median 175–197 days old; median 0–1 peaks inside; 92–93% ended >30 days before evaluation |
| 2 | 260-bar history buffer starves the weekly stage | `kashif_strategy.py:151` | 3/3 tickers: PRICE_READY on full history, rejected on the buffer |

Both are **architectural, not calibration**. Neither is fixed by loosening a
threshold — consistent with the earlier forward-return test, which found that
loosening `CONTRACTION_COUNT_MIN` from 2 to 1 is **not** supported by the data
(the single-contraction bases did not outperform: 20d median +4.78% vs +3.06%,
but 40d −1.99pp and 60d −3.29pp worse, on 61 vs 73 unique bases).

## 5. Recommended next step — measure before changing

> **STATUS: ANSWERED.** Both measurements called for here were run on
> 2026-08-30. See §6 (Defect 2) and §7 (Defect 1) for actual numbers, and §8
> for the revised conclusion. The text below is retained as the reasoning that
> motivated the measurements.

Neither defect should be "fixed" before quantifying the fix:

1. **Defect 2 is the cheaper test.** Raising `HISTORY_BUFFER_MAXLEN` is a
   one-line change, but it increases memory and warm-up for every ticker in the
   universe. Before changing it, measure how many of the 42 missed winners a
   longer buffer would actually recover — that is a detection-only sweep, no
   backtest required.

2. **Defect 1 needs a design decision, not a parameter.** Options include
   extending the window to the evaluation date, aligning the weekly and daily
   contraction minimums, or dropping the window constraint entirely. Each
   changes what "a base" means, so each needs the same forward-return test that
   was applied to `CONTRACTION_COUNT_MIN` before anything is adopted.

**Caveat on all of the above:** these findings rest on 3 deeply-traced tickers
and 42 aggregate ones from a single market and a single 2-year period. They
identify precisely where to look; they do not by themselves justify a change.

---

# PART II — MEASUREMENTS (2026-08-30)

*Detection-only sweeps. No source files modified, no backtest run. Task 2
replicates `evaluate_entry_timing()` faithfully using the real
`vcp_detection` functions, with the window slice as the only variable.*

Method notes common to both tasks:

- Population: the **42 missed 200%+ winners** (`club200` minus the 7 traded).
- Evaluations run only on IS days where `hard_filter` actually passed,
  sampled every 5th such day (`STEP = 5`).
- Universe-wide cross-sectional RS percentile recomputed across all 195
  tickers, as the strategy does.
- Scripts: `_m_task1_buffer.pkl`, `_m_task2_window.pkl`.

---

## 6. TASK 1 — Defect 2 measured: buffer length

### 6.1 PRICE_READY recovery by buffer length

| buffer | tickers with ≥1 PRICE_READY | % of 42 | total ready-days |
|---|---|---|---|
| **260 (current)** | **0** | **0.0%** | **0** |
| 400 | 3 | 7.1% | 4 |
| 500 | 3 | 7.1% | 6 |
| 600 | 3 | 7.1% | 5 |
| 750 | 3 | 7.1% | 5 |
| FULL | 3 | 7.1% | 5 |

At the current 260-bar buffer, **zero** of the 42 missed winners ever produce a
signal — confirming the starvation is real. But unlimited history recovers only
**3 of 42 (7.1%)**, and **400 bars recovers all 3**. There is no additional
recovery from 500, 600, 750 or unlimited.

### 6.2 The three recovered tickers

| ticker | IS return | earliest PRICE_READY | stock peak date | signal before peak? |
|---|---|---|---|---|
| WKOL | +509% | 2023-10-24 | 2025-08-26 | **YES** |
| MENA | +405% | 2024-02-07 | 2025-02-24 | **YES** |
| OIH | +383% | 2025-07-07 | 2025-07-27 | **YES** |

All three signal before the peak, so all three would have been tradeable.

### 6.3 Memory cost

Formula as specified: `bars × 6 columns × 8 bytes`, per ticker.

| buffer | per ticker | ×195 (EGX) | ×503 (S&P 500) |
|---|---|---|---|
| 260 | 12.2 K | 2.32 M | 5.99 M |
| **400** | **18.8 K** | **3.57 M** | **9.21 M** |
| 500 | 23.4 K | 4.46 M | 11.51 M |
| 600 | 28.1 K | 5.36 M | 13.82 M |
| 750 | 35.2 K | 6.69 M | 17.27 M |

260 → 400 costs **+1.25 MB** (EGX) / **+3.2 MB** (S&P) by this formula.
The strategy stores Python dicts rather than a numpy array, so the true
footprint is roughly **20–30×** these figures — call it **+30–100 MB** on the
S&P universe. Still modest.

### 6.4 Verdict on Defect 2

Real but **low impact**: 7.1% recovery. If fixed at all, **400 bars is the
correct value** — every longer buffer is pure cost for zero additional
recovery. This is not where the value is.

---

## 7. TASK 2 — Defect 1 measured: window extended to evaluation date

Mode A = current behaviour (`daily_df.loc[weekly_start:weekly_end]`).
Mode B = window extended to the evaluation date (`daily_df.loc[weekly_start:]`).

### 7.1 Headline

```
200%+ WINNERS (missed)   n=42 tickers, 1,492 evaluation days
  Mode A    3 tickers signalled     5 signal-days
  Mode B   15 tickers signalled    33 signal-days

NON-WINNERS (<50% IS) control   n=20 tickers, 204 evaluation days
  Mode A    1 ticker  signalled     1 signal-day
  Mode B    2 tickers signalled     5 signal-days
```

**Mode B recovers 15 of 42 missed winners (35.7%) vs 3 (7.1%) — 5× more.**

### 7.2 The 14 newly recovered winners

| ticker | IS ret | first signal | peak date | timing |
|---|---|---|---|---|
| SCEM | +724% | 2025-01-27 | 2025-08-19 | BEFORE peak |
| CPCI | +550% | 2024-07-09 | 2025-08-17 | BEFORE peak |
| ATQA | +529% | 2023-11-01 | 2025-06-11 | BEFORE peak |
| SVCE | +457% | 2024-09-23 | 2025-08-24 | BEFORE peak |
| TMGH | +413% | 2023-12-25 | 2024-03-04 | BEFORE peak |
| ISPH | +412% | 2025-03-09 | 2025-08-17 | BEFORE peak |
| GBCO | +315% | 2024-10-01 | 2025-08-18 | BEFORE peak |
| EGAL | +305% | 2024-07-07 | 2025-03-18 | BEFORE peak |
| PHDC | +302% | 2024-08-11 | 2025-07-09 | BEFORE peak |
| SPIN | +242% | 2025-04-29 | 2025-07-09 | BEFORE peak |
| RREI | +221% | 2024-10-10 | 2025-08-14 | BEFORE peak |
| OLFI | +213% | 2025-04-29 | 2025-06-30 | BEFORE peak |
| AMER | +206% | 2024-09-23 | 2025-06-01 | BEFORE peak |
| WCDF | +203% | 2024-09-29 | 2025-08-26 | BEFORE peak |

**14 of 14 fire before the stock's peak.** ATQA signals 2023-11-01 against a
2025-06-11 peak — 19 months of runway.

### 7.3 False-positive control — the critical test

Control group: 20 tickers randomly sampled (`seed=20260830`) from those
returning **<50%** during IS.

New false positives introduced by Mode B:

| ticker | IS return | signal-days | first signal |
|---|---|---|---|
| ADIB | +2% | 4 | 2023-09-14 |
| MHOT | **−62%** | 1 | 2024-07-09 |

Control signal rate: **Mode A 1/20 (5%) → Mode B 2/20 (10%)**.

### 7.4 Precision

Winners and control pooled; precision = signalling winners / all signalling
tickers.

| mode | winners | false pos | total signalling | **precision** | signal-days (win / non-win) |
|---|---|---|---|---|---|
| A | 3 | 1 | 4 | **75.0%** | 5 / 1 |
| B | 15 | 2 | 17 | **88.2%** | 33 / 5 |

**Mode B buys 12 additional winners for 1 additional false-positive ticker.**

### 7.5 Verdict on Defect 1

The question this task was designed to answer — *does the window constraint do
real work, or does removing it flood the pipeline with noise?* — has a clear
answer: **the constraint was suppressing signal, not noise.** Removing it
recovers 5× the winners **and raises precision by 13.2 points**.

---

## 8. Revised conclusion

| defect | recovery | precision effect | cost | priority |
|---|---|---|---|---|
| **1 — stale daily window** | **15/42 (35.7%)** | 75.0% → **88.2%** | none (slice change) | **HIGH** |
| 2 — 260-bar buffer | 3/42 (7.1%) | n/a | +30–100 MB (S&P, dict overhead) | LOW |

Defect 1 is where the value is. Defect 2 is a cheap adjunct at **400 bars** —
never more.

### Three limits on these numbers, stated plainly

1. **MHOT is a genuine warning.** Mode B signalled on a stock that finished
   **−62%**. Aggregate precision improved, but the failure mode is real: that
   position would have been stopped out at −10%.

2. **A signal is not a trade.** The 15 recovered tickers would still compete
   for 6 slots against every other candidate, and the strategy has already
   shown it can hold a winner badly — SNFC returned **+1136%** over IS and the
   backtest lost **−10.1%** on it. Recovering the signal does not recover the
   return.

3. **The n=20 control is thin.** One extra false positive on 20 names is not a
   precise estimate of the false-positive rate. Before committing to a change,
   widen the control to 60–80 non-winners and add a middle band (50–200%
   returns). That is cheap and would firm up the precision figure considerably.

   > **STATUS: DONE.** See §9. The widened control **reverses the
   > recommendation** under the stated decision gate.

**No code has been changed.** These are measurements only.

---

# PART III — WIDENED CONTROL (2026-08-30)

## 9. Stratified n=75 control group

### 9.1 Construction

Excluded: all 49 `club200` tickers (42 missed + 7 traded winners).
Eligible pool: 146. Seed `20260830`.

| target band | requested | available | selected |
|---|---|---|---|
| <0% (losers) | 25 | **22** | **22 (all)** |
| 0–50% (weak) | 25 | 42 | 25 |
| 50–200% (middle) | 20–30 | 82 | 28 |
| **total** | 60–80 | — | **75** |

**Shortfall recorded:** only 22 tickers in the whole EGX universe returned <0%
during IS, so the losers band is 22 rather than 25. It cannot be widened.

**Of the 75, only 51 had any `hard_filter`-passing day** in IS and were
therefore evaluable at all. Rates below are over the 51 evaluable.

### 9.2 Results

```
Mode A:  5/51 control tickers signalled (9.8%)   13 signal-days
Mode B: 14/51 control tickers signalled (27.5%)  20 signal-days
```

### 9.3 False-positive rate by return band

| band | n | evaluable | Mode A | rate | Mode B | rate |
|---|---|---|---|---|---|---|
| <0% | 22 | 13 | 1 | 7.7% | **2** | **15.4%** |
| 0–50% | 25 | 11 | 0 | 0.0% | **3** | **27.3%** |
| 50–200% | 28 | 27 | 4 | 14.8% | **9** | **33.3%** |

### 9.4 Every control ticker Mode B signalled

| ticker | band | IS ret | A days | B days | first B signal |
|---|---|---|---|---|---|
| MHOT | <0% | −62% | 0 | 1 | 2024-07-09 |
| EFIH | <0% | −2% | 0 | 1 | 2024-08-01 |
| ADIB | 0–50% | +2% | 0 | 4 | 2023-09-14 |
| AMOC | 0–50% | +2% | 0 | 3 | 2023-10-17 |
| NINH | 0–50% | +39% | 0 | 1 | 2023-11-12 |
| PRDC | 50–200% | +69% | 0 | 1 | 2024-11-05 |
| ORWE | 50–200% | +71% | 0 | 1 | 2024-08-05 |
| JUFO | 50–200% | +75% | 0 | 1 | 2024-10-08 |
| ECAP | 50–200% | +79% | 0 | 1 | 2023-10-26 |
| ACGC | 50–200% | +105% | 0 | 1 | 2023-10-15 |
| ELKA | 50–200% | +113% | 0 | 1 | 2024-12-11 |
| MTIE | 50–200% | +121% | 2 | 1 | 2024-10-24 |
| ZEOT | 50–200% | +126% | 0 | 2 | 2024-12-19 |
| ASCM | 50–200% | +199% | 0 | 1 | 2023-11-01 |

### 9.5 Updated precision — and the decision gate

| mode | winners | false positives | total signalling | **precision** |
|---|---|---|---|---|
| A | 3 | 5 | 8 | **37.5%** |
| B | 15 | 14 | 29 | **51.7%** |

```
DECISION GATE (as specified)
  Mode B precision = 51.7%
    >= 80%  -> proceed with fixing Defect 1
    <  70%  -> do NOT fix; the constraint is doing real work
  VERDICT: DO NOT FIX
```

**Under the stated gate, the answer is DO NOT FIX Defect 1.** The n=20 estimate
of 88.2% was optimistic by 36.5 points; widening the control cut it in half.

### 9.6 MHOT — isolated, not systematic

The specific question asked: does MHOT represent a systematic failure mode?

```
<0% band: 2/13 evaluable losers signalled under Mode B (15.4%)
signalling losers: EFIH (-2%), MHOT (-62%)
```

**Isolated.** Only 2 of 13 evaluable losers signal, and one of them (EFIH, −2%)
is essentially flat rather than a decliner. MHOT at −62% is the single genuine
bad signal in the entire 75-ticker control. Mode B is **not** systematically
firing on declining stocks.

---

## 10. The composition caveat — stated because it changes the reading

The 51.7% figure is arithmetically correct but the label "false positive" is
carrying weight it cannot support, for one concrete reason:

**Two of the 14 "false positives" are stocks the backtest actually traded.**

| ticker | IS ret | reality |
|---|---|---|
| **ASCM** | +199% | **The single best trade of the EGX run: +10,749 (+217.6%)** |
| **MTIE** | +121% | Traded in the backtest |

ASCM missed the 200% club by **1.2 percentage points** and was the run's largest
winner. Counting a signal on it as a false positive is not defensible.

Nine of the 14 returned **+69% to +199%**.

### 10.1 Precision as a function of where the "winner" line is drawn

| winner defined as IS ≥ | Mode A | Mode B |
|---|---|---|
| 200% | 37.5% | **51.7%** |
| 150% | 37.5% | 55.2% |
| **100%** | **75.0%** | **69.0%** |
| 50% | 87.5% | **82.8%** |
| 0% | 87.5% | **93.1%** |

The verdict flips with the threshold. At ≥200% Mode B looks better than Mode A
(51.7% vs 37.5%); at ≥100% it looks worse (69.0% vs 75.0%); at ≥50% and ≥0% it
is close or better again.

### 10.2 Return distribution of everything each mode signals on

| | Mode A | Mode B |
|---|---|---|
| tickers signalled | 8 | 29 |
| median IS return | +145% | **+203%** |
| mean IS return | +217% | +221% |
| worst signal | −12% | **−62%** |
| share ≥100% | 6/8 (75%) | 20/29 (69%) |
| share <0% | 1/8 | 2/29 |

Mode B's signal set has a **higher median return** (+203% vs +145%) and a
similar mean, but a worse tail (−62% vs −12%) and a slightly lower share of
≥100% names.

---

## 11. Final recommendation

**Do not fix Defect 1 on this evidence.** That is the stated gate's answer, and
I am not going to argue around it — the honest summary is that **the widened
control did not confirm the n=20 result**, and a measurement that moves 36
points when the sample widens is not a measurement to act on.

What the data supports saying:

- Mode B **is not** noise-flooding. It signals on stocks with a **higher median
  return** than Mode A, and only 2 of 13 evaluable losers.
- Mode B **does** roughly triple the control signal rate (9.8% → 27.5%) and
  admits the only genuinely bad name in the sample (MHOT, −62%).
- The precision verdict is **threshold-dependent and therefore unstable**,
  which is itself a reason not to commit.

### 11.1 What would actually settle it

Precision on a return threshold is the wrong instrument — it discards position
sizing, stops, and holding period. ASCM is the proof: a +199% "false positive"
that the strategy traded for its single largest gain.

The decisive test is a **paired backtest** — identical configuration, Mode A vs
Mode B as the only variable — compared on realized return, max drawdown, Sharpe
and trade count. That measures what the change is worth after the stop-loss has
dealt with MHOT and the sizer has dealt with slot contention, neither of which
a detection sweep can model.

Until that is run, Defect 1 stays unfixed.

### 11.2 Defect 2 is unaffected

Nothing here changes §6. Defect 2 remains a real but low-impact issue (7.1%
recovery, all of it captured at **400 bars**). It is independent of the window
question and could be fixed separately at low risk.

**No code has been changed.** These are measurements only.
