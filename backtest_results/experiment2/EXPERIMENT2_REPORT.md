# Experiment 2: final report

**Verdict: FAIL.** On fresh 2017–2021 data, the tuned Minervini SEPA strategy lost money (−3.2% total), while the mid/small-cap benchmark gained +80%. The pre-registered changes made things worse, not better. There is no evidence of an edge. Do not trade this strategy with real money, with or without leverage.

Written 2026-09-26. Every number comes from committed files:
- `kashif_data/experiment2/validation2_results.json`
- `EXPERIMENT2_REPORT_DATA.json`
- `dev_grid.csv`

The validation ran **once**, under a lock that was committed and pushed first:
- claim `d59d521`;
- results `3c034de`;
- lock `f3103e6`.

---

## 1. The answer to "can it make 200% a year?"

No. Not this strategy, and not honestly.

On data never used for any decision, the best version the development search could find returned **−0.6% a year**. Leverage multiplies whatever edge exists. With a negative edge, leverage multiplies the loss:

| Leverage on the validated pick | CAGR 2017–2021 | Max drawdown |
|---|---|---|
| 1× | −0.6% | −24% |
| 2× | −8.1% | −47% |
| 3× | −15.9% | −66% |
| 4× | −23.9% | −80% |

*(Daily rebalanced, with a 6% yearly borrowing cost.)*

- **Development results were misleading.** The same pick made 25.7% a year on 2022–2026, the data it was chosen on. The gap between 25.7% and −0.6% is what choosing the best of 1,188 backtests does.
- **The Deflated Sharpe Ratio warned in advance.** It was 0.41 at N = 1,188: the development Sharpe was not distinguishable from luck after the search. The fresh-data test confirmed it.

## 2. What was tested

- Pre-registered in `PREREGISTRATION.md`, with amendments 1–3 committed before any development result was read.
- Only the two drags measured in experiment 1 changed: defensive mode and the regime gate. Amendment 3 added two families from the strategy's own config: "let winners run" exits, and the config's position sizing.
- The design: 11 variants × 108 parameter combinations = **1,188 development backtests** on 2022-01-03..2026-09-24.
- The pick was chosen by a fixed rule, then run **once** on 2017-01-03..2021-12-31. No run had ever traded that window.
- **Arm B** is experiment 1's frozen strategy, as a reference.

## 3. Development (2022–2026, in-sample)

| Variant | What changed | Median Sharpe | Best Sharpe | Median CAGR |
|---|---|---|---|---|
| V0 | experiment 1 as-is | 0.19 | 0.61 | 0.8% |
| **V1** | defensive mode off | **0.82** | **1.41** | 9.2% |
| V2 | defensive size-only | 0.69 | 1.23 | 5.3% |
| V3 | 2-of-3 regime gate | 0.33 | 0.82 | 1.7% |
| V4 | V1 + 2-of-3 gate | 0.75 | 1.26 | 6.6% |
| V5 | V1 + let-winners-run exits | 0.59 | 0.91 | 5.7% |
| V6 | V1 + config sizing | 0.62 | 1.22 | 8.4% |
| V7 | V1 + both | 0.54 | 0.83 | 7.5% |
| V8 | V4 + let-winners-run | 0.50 | 0.93 | 4.8% |
| V9 | V4 + config sizing | 0.55 | 1.01 | 6.6% |
| V10 | V4 + both | 0.63 | 1.01 | 9.7% |

- **The pick:** V1, RS ≥ 90, breakout volume 1.2×, max stop 10%, 4 positions.
  - Development: Sharpe 1.42, CAGR 25.7%, max drawdown −15.2%, 84 trades, positive in both halves.
  - An independent auditor re-derived the pick from the rule with its own code and got the same top 10, in the same order.
- **Warning signs visible before validation:**
  - Deflated Sharpe: 0.41 vs zero, and 0.06 on excess over the benchmark (N = 1,188).
  - The pick sat on a corner of the grid, so its score rested on only 5 runs.
  - 3 trades made 64% of its closed-trade profit, and its median trade lost 5.7%.
- **In-sample lessons:**
  - Defensive mode was the biggest drag: V0's median CAGR is 0.8% against V1's 9.2%.
  - The "let winners run" exits (V5, V7, V8, V10) did worse, not better.

## 4. Validation (2017–2021, fresh data, run once)

| | Total | CAGR | Sharpe (Lo SE ±0.45) | Max DD | Trades | Verdict |
|---|---|---|---|---|---|---|
| **Arm A, the pick** | **−3.2%** | **−0.6%** | −0.01 | −24.2% | 80 | **FAIL** |
| Arm B, experiment 1 frozen | +31.9% | +5.7% | 0.60 | −14.2% | 159 | FAIL |
| MDY/IJR 50/50 | +80.2% | +12.5% | 0.62 | −42.3% | | |
| S&P 400+600 equal-weight* | +147.3% | +19.9% | 0.87 | −43.0% | | |
| SPY | +130.4% | +18.2% | 0.98 | −33.7% | | |

\*Current members only, so inflated by the same survivorship as the strategy's universe.

- **Pre-declared tests:**
  - Arm A vs the equal-weight basket: bootstrap p = 0.99.
  - A − B: CAGR −6.3 percentage points, p = 0.87, so **the changes get no credit**.
  - Both arms' independent audits match the ledger exactly, so this is not a bookkeeping failure.
- **By year, arm A vs the blend:**

  | Year | Arm A | Blend |
  |---|---|---|
  | 2017 | +4.5% | +13.9% |
  | 2018 | −2.7% | −9.9% |
  | 2019 | −6.2% | +24.3% |
  | 2020 | +21.8% | +12.5% |
  | 2021 | −16.7% | +25.5% |

  It lost in the two strongest bull years.
- **Arm A's 80 trades by exit:**

  | Exit | Trades | Average |
  |---|---|---|
  | Stop loss | 50 | −9% |
  | Distribution bar | 22 | +10% |
  | Trailing stop | 7 | +31% |
  | Breakeven stop | 1 | ≈0% |

  - Win rate 24%.
  - Average win +25%, average loss −8%.
  - Profit factor 0.90.
  - Invested only 26% of the time.

## 5. Why it fails (diagnosis)

1. **Mostly in cash in a strong market.** The screens pass few stocks, so exposure was 26–35%. From 2017 to 2021 the index roughly doubled; a strategy that is mostly in cash cannot keep up unless each trade is exceptional, and these were not.
2. **Breakouts mostly fail.** 50 of 80 trades hit the stop. With a 24% win rate, the few big winners have to pay for everything, and their size depends heavily on the period. Development had LQDA, ADMA and BTSG; validation did not.
3. **The filters don't find the leaders.** An in-sample study of the 447 stocks that doubled in 2022–2026 (`MODEL_BOOK_DEV.md`, by a peer session) found:
   - the funnel caught 2.7% of them;
   - only relative strength separated winners from losers;
   - the VCP pattern did not;
   - the winners were more volatile (4.6% vs 3.2% daily range), and tight stops shake exactly those out.
4. **Tuning chased noise.** The same pick ranked first on 2022–2026 and lost on 2017–2021: what was optimized was that period's handful of big winners.

## 6. Data integrity (what was fixed before the test, and what remains)

- **The data was rebuilt from 2014, and a series of bugs was fixed before any development result.** Each fix is recorded in the Amendment 3 addendum. The most important:
  - **Lookahead:** earnings dates sometimes came from *pre-announcements*, up to 44 days before the real results. Now fixed. This also affected experiment 1's data.
  - **Fake series:**
    - a +25,700% price jump (CHRD);
    - EPS stored in cents as dollars (FIZZ);
    - SPAC shells used as "last year" (MP, HIMS, RSI and others: 30 history breaks);
    - Q4 EPS derivation errors (AIN, QRVO, KNX, PTON, ROKU and others).
  - **Splits:** 172 missing splits and stock dividends added. 148 were confirmed by each company's own restated numbers; 0 contradicted.
- **Independent audits against press releases** (80 random rows):
  - 2015–2019: EPS 36/38 and release dates 31/38.
  - 2022–2026: EPS 34/37 and release dates 38/40.
  - **Zero lookahead dates.**
- **Known residuals** (reported, not fixed):
  - About 23 Q4 EPS values in restated years are off by 3–10%.
  - The validation window's quarterly data is 3–5× more often "late" (restated quarters are dated at the restatement). This handicaps the validation window, but it is small next to a 12-point-a-year shortfall.
  - The universe is *today's* index members. That excludes the winners promoted to the S&P 500 and the losers that were delisted. The equal-weight benchmark carries the same bias.
- **Code:** two adversarial reviews by a peer session (30 findings, then 10) led to guards that make the validation impossible to run twice, or without its lock. The engine test suite passes 49/49.

## 7. What next

- **This strategy should not get real money.** Two pre-registered experiments on two independent periods both failed.
- **Experiment 3** (`backtest_results/experiment3/PREREGISTRATION_DRAFT.md`, a draft for the owner):
  - Forward **paper** trading from 2026-09-28. Arms built from the model-book findings: an RS ≥ 95 floor, a simpler breakout entry instead of VCP, and softer fundamentals vetoes. Plus the AI-agent news-rating arm, which **cannot be backtested honestly** because every LLM has read what happened next.
  - The power calculation is sobering. Confirming a Sharpe of 1.0 takes **about 4.5–6 years** of live data; 12 months can only confirm a Sharpe above about 2.
  - Arm A's placeholder (the experiment-2 pick) should be dropped: it failed.
- **For better research data:** a point-in-time universe with delisted stocks (e.g. Norgate Data or CRSP) would remove the survivorship problem that no free source can fix.
