# Experiment 5: momentum/volatility breakout (MV1). Pre-registration

**Written and committed before any simulation of this strategy was run.**

## The idea being tested

Experiment 4 found that among fresh breakouts, the later big winners were the volatile, already-running ones. Eight simple window statistics, in a logistic regression fitted only on 2022-01 to 2025-08 data, picked them with AUC 0.80 on Sept 2025 – Mar 2026 breakouts. The AI chart judge scored 0.42.

This experiment asks whether that ranking makes money as a **portfolio**, with costs, a position limit and a fixed holding period.

## Honesty statement (read first)

The owner chose the Sept 2025 onward window. **It is not clean for this idea:**
- The clue was found in part on Sept 2025 – Mar 2026 breakouts (experiment 4, Step 3).
- Experiments 2 and 3 used the same period as development data.

Therefore:
- **A FAIL here is strong evidence.** The idea cannot make money even on data where its clue was seen, so it is dropped.
- **A PASS here is weak evidence.** It means only "worth a clean test", most cleanly on Jul 2015 – Dec 2016, a window no experiment has used. It does not mean "it works".

## Rules (frozen)

**Universe.**
- The 997 tickers in `kashif_data/experiment2/model_book_dev/days.parquet`: current S&P 400 + 600 members with price series.
- This means survivorship bias, which favours the strategy against the index. The random-priority null uses the same universe, so it controls for this.

**Signal: a fresh qualified breakout** at the close of day t, as in `kashif_data/experiment4/modelbook_eval/README.md`. It needs all of:
- a liquid day: raw close ≥ $10 and 50-day dollar volume ≥ $5M;
- Trend Template tt_1..tt_8b;
- RS percentile ≥ 70;
- close above the prior 50-day closing high;
- volume ≥ 1.2× its 50-day mean;
- fresh: no other qualified day for that ticker in the previous 20 trading days.

All of these flags are point-in-time, as of day t's close. No forward column is used for selection.

**Score.**
- The 8 window statistics (`ai_judge_batches._stats8`) on the 250 bars ending at day t: ATR14%, 20-bar return, 60-bar depth, 60-bar return, 250-bar return, distance from the 250-bar high, breakout-day relvol, and 10-bar volume dry-up.
- Scored by the logistic model fitted on the 293 samples of Fork 4's eval set dated before 2025-09-01. This is exactly the experiment-4 Step-3 baseline, refitted by the same deterministic code.

**Selection.**
- Only breakouts whose score is ≥ **T**.
- **T** = the 67th percentile ("top third") of scores over all fresh qualified breakouts dated 2022-01-03 to 2025-08-29.
- T uses pre-window data only. Its value is written into this file before the test run, in the section below.

**Portfolio.**
- $100,000 virtual capital; at most **6** positions.
- **Entry:** at the next day's open, highest score first.
- **Size:** min(cash, equity at the prior close ÷ 6), in whole shares.
- A ticker already held is skipped. There is no adding to positions.

**Exit, primary.** At the close of the **60th trading day** of the holding (the entry day counts as day 1). No stop.

**Variant S (reported, not decisive).** The same, plus a stop 8% below the entry fill:
- checked against the daily low;
- filled at the stop, or at the open if the price gaps below it.

**Costs.** The engine's US model (`kashif_engine.markets.US`):
- commission of max($1, $0.005 per share), capped at 1% of value;
- slippage of 5 bps + 10 bps × √(participation ÷ 1%), where participation is the order value ÷ 50-day dollar volume.

**Cash and dividends.**
- Cash earns 0.
- Stock prices are split-adjusted without dividends.
- The benchmark includes dividends. Both choices are conservative for the strategy.

**Window.**
- Signals from 2025-09-01 to 2026-09-23. Entries run to 2026-09-24.
- Every position still open is closed at the **2026-09-24** close, the last bar.

## Comparisons

1. **MDY/IJR 50/50**, daily rebalanced with dividends (`reports.benchmark_curves`), over the same dates.
2. **Random-priority null:** 500 portfolios with identical rules, choosing among **all** fresh qualified breakouts (no score threshold) in random order, seeds 0–499. This asks whether the ranking adds anything beyond "buy breakouts".
3. **Reported, not decisive:**
   - the bottom third (score ≤ 33rd percentile) under the same rules;
   - an equal-weight portfolio of current S&P 400/600 members;
   - maximum drawdown, trade count, win rate and exposure for each.

## Decision rule (one run, no changes after seeing results)

**PASS**, meaning worth a clean test, **only if both** hold for the primary strategy's total return:
- it beats MDY/IJR 50/50; **and**
- it beats the median of the 500 random-priority portfolios.

**Otherwise FAIL**, and the MV1 idea is dropped.

Code bugs found after the run may be fixed, but only if the fix does not change any rule above, and the fix and its effect are reported.

## Frozen numbers (filled in from pre-window data before the test run)

Computed by `run_exp5_mv1.py prepare` from breakouts dated 2022-01-03..2025-08-29 only, before any portfolio simulation.

| Number | Value |
|---|---|
| **T** (67th percentile) | **0.170749** |
| T33 (33rd percentile, bottom-third report) | 0.087711 |
| Pre-window fresh breakouts behind them | 2,544 |

**Pipeline check.** The 8 statistics recomputed from raw prices match all 505 of Fork 4's eval samples, to float32 rounding.
