# Evaluation set: "Did the AI agree with Minervini?"

Anonymised daily-bar windows for Minervini's disclosed stock buys, each with 5 matched controls. Data only; no LLM was called to build it.
Build script: `scratchpad/exp4/build_eval.py` (First Trial session), which is deterministic with seed 31.

## Files

| File | Contents |
|---|---|
| `windows.parquet` | `id, bar, o, h, l, c, v`. 138 windows × 250 bars = 34,500 rows. No tickers or dates. |
| `key.csv` | `id → ticker, date, label` (`MINERVINI_BUY` / `CONTROL`), plus the extra columns below. **Never show this file to the model.** |

Extra `key.csv` columns:
- `match_group`: links each buy to its 5 controls. Score within groups, not pooled.
- `date_precision`, `stated_date`, `anchor_rule`: how the window end was chosen.
- `passes_tt_core`, `rs_pct`: our trend template and RS on the anchor date.
- `source_confidence`: from the disclosed-trades CSV.

## How it was built

- **Buys:** BUY rows from `minervini_disclosed_trades.csv` with an exact or month date: 46 rows.
  - The 3 ETFs (XLE, IBIT, IWN) are dropped, leaving 43.
  - 20 are skipped: 19 have no price file (NNOX, UAVS, GBOX, ZIM, BNTX, HSKA, TSP, SE, SNAP, SQ, RVLV, UPST, ASYS, SRTS, YELL, LMB, NMM, RNA, TATT), and MP has only 56 clean bars after its SPAC break.
  - **23 buys kept.** NUE appears twice (2021-08-09 and 2021-11).
- **Window end (the "anchor"):**
  - Exact date: that trading day, or the last trading day before it.
  - Month-only date (6 buys: NUE Nov-21, AIG, CARR, NVDA, CCL, UBER): the last trading day **before** the month. This way no bar from the unknown buy day, or later, can leak in. The cost is that the setup may not have finished forming.
- **Controls:** 5 per buy, from the same anchor date, drawn with seed 31. Each passes `tt_core` and has `rs_pct ≥ 70` in `panels/US_1500`.
  - No ticker he ever disclosed, in any row, is used as a control.
  - No (ticker, date) is reused.
  - All 23 groups got 5 controls: 115 controls from 111 distinct tickers.
- **Prices:** from `prices.load()`. That means split-adjusted OHLCV, not dividend-adjusted, with the project's price corrections and history-break cuts applied.
  - Every window needs 300 clean bars: 250 shown plus 50 for the volume average.
- **Anonymisation:**
  - Price: ÷ the window's first close × 100, so bar 0 closes at exactly 100.
  - Volume: ÷ the mean of the **previous** 50 bars' volume. The current bar is excluded, so a spike isn't damped by itself.
  - Bars are indexed 0-249; the ticker and dates are dropped.
  - ids are shuffled, so neither id nor row order reveals the label.
- **Checks:**
  - every window has 250 bars;
  - no NaNs;
  - bar-0 close = 100;
  - no bar has a high below its open/close or a low above them;
  - no duplicate (ticker, date).

## Counts

| | |
|---|---|
| Minervini buys | 23 (16 in 2021, 1 dated 2023-12 for a Jan-2024 buy, 4 in 2024, 2 in 2025) |
| Controls | 115 (5 per buy) |
| Windows | 138 |
| Buys that also pass our trend template and RS ≥ 70 | 18 |
| Buys that do not | 5: TSLA 2021-09 (TT fail), CCL 2025-08 (TT fail), UBER 2025-08 (TT fail), AAPL 2021-06 (RS 54), ANF 2021-01 (RS 66) |

## Caveats: read before scoring

1. **Small sample.** With 23 positives, a 95% interval on a hit rate is roughly ±20 points. The set can show gross agreement or disagreement, not fine differences.
2. **The last bar is his entry day, and it leaks.** Single-feature AUCs, buy vs control (0.5 = no signal):

   | Feature | AUC |
   |---|---|
   | Last bar's volume ratio | **0.75** |
   | Last bar's return | **0.67** |
   | Volume one bar earlier (bar 248) | 0.44 |
   | Return one bar earlier (bar 248) | 0.52 |
   | Distance from the 250-bar high | 0.43 |
   | 50-bar return | 0.49 |
   | RS | 0.56 |

   He buys on breakout days with volume, so the entry-day bar *is* most of the distinguishing signal. But it contains the day's close and full volume, which aren't known at a morning entry.

   **Score two variants:**
   - (a) bars 0-249, "at the close";
   - (b) bars 0-248, "the evening before".

   A judge that only works in (a) is mostly reading one volume bar. Any AI result should also beat the simple last-bar-volume baseline (AUC 0.75).
3. **Controls are pre-filtered, and 5 buys are not.** Every control passes TT + RS ≥ 70; 5 of his buys fail it. The trend-template label alone therefore isn't a clean signal. Report results on all 23, and on the 18 buys that pass the filter.
4. **Selection bias.**
   - His disclosed buys lean to publicised, often winning trades.
   - 19 of 43 are missing entirely: the small caps, IPOs and foreign names that are his most characteristic trades.
   - What remains is biased toward large, mature stocks.
5. **Controls aren't "stocks he rejected".** They are stocks he *didn't disclose*. He may have owned some, and many were probably fine setups. Low agreement doesn't prove the judge is wrong.
6. **Anonymisation isn't complete.** Rescaling hides the price level and dates. It doesn't hide the *shape*, and 2021-2025 is inside any current model's training data. Famous charts (TSLA 2021, NVDA 2023-24, MRNA 2021, APP 2024) may be recognisable from their path alone.
7. **Month-dated buys** (6) are anchored before the month, and their `stated_date` is imprecise. Consider scoring them separately.

## My view

**Is an AI chart judge worth trying? Yes, as a cheap, bounded experiment, not as the next strategy.**

The engine's failure is specific and measured. Our filters pass 50 of 52 of his names, but on a typical day ~255 stocks pass, and the mechanical VCP detector rejects most of his real entries. So the missing piece really is chart judgment. That's the one thing an image- or series-reading model might add, and this set can test it for a few dollars before anything is built.

**Biggest risk: we'll measure memory or leakage and call it skill.** Three routes lead there:
1. **Training-data recall of famous 2021-2025 charts**, as in caveat 6.
2. **The entry-day bar**, as in caveat 2: most of the signal is in that single bar.
3. **Tuning the prompt on this same set until it "agrees".**

The last is the most dangerous. It is exactly the in-sample trap that experiments 1-3 already fell into, and with 23 positives it would take very few prompt iterations to overfit.

**Mitigations I'd insist on:**
- Freeze the prompt before looking at any score.
- Score variant (b) as the headline, and report it against the 0.75 volume baseline.
- Include decoy windows:
  - time-reversed or mirrored copies of the same charts, to show whether the model reacts to real structure;
  - windows from after the model's training cutoff.
- Before any money-relevant decision, treat agreement with Minervini as a proxy only. The real test is still out-of-sample returns, on data the judge and the prompt have never seen.
