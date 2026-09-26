# Lessons from experiments 1 and 2, for experiment 3

Analyst memo, written 2026-09-26. It is **diagnosis, not tuning**: no backtest was run, no parameter was re-optimised, and nothing here was used to pick a variant. It reads only finished runs:
- the dev grid (1,188 runs, 2022-01-03..2026-09-24);
- the two one-shot validation arms (2017-01-03..2021-12-31);
- experiment 1's TUNE_final and HOLDOUT_primary;
- split-adjusted prices, used for forward looks from the entry dates the trades already had.

The scratch scripts are in the session scratchpad (`analyst/`), not in the repository.

## Summary (10 lines)

1. **Every dev-grid parameter effect comes from one period.** Only 2 runs exist in 2017–21, so a grid effect can be checked there only through trade-level proxies. The variant explains 38% of Sharpe variance; the four grid parameters together explain about 8%.
2. **In the grid, a higher RS threshold hurts.** RS 90 vs 70: ΔSharpe −0.14, with 67% of 396 matched pairs negative, 5 of 6 families agreeing, and the same result in both dev halves and in exp-1's grid. The stop cap is noise (ΔSharpe +0.005). Fewer positions raise CAGR only through exposure.
3. **Robust in both periods: high entry RS did not produce better trades inside this stop/exit machinery.**
   - Spearman(RS, trade return) was −0.24 [CI −0.36, −0.10] in 2017–21 and −0.20 [−0.32, −0.09] in 2022–26.
   - Entries with RS ≥ 95 averaged +0.2%, +0.2% and −0.6% per trade across the three samples, with win rates of 26–29% (RS < 90: 35–41%).
4. **Robust: the strategy is a stop-out machine.**
   - 55–63% of trades exit at the initial stop, after a median of 6–9 bars, at −7% to −9% each.
   - All the profit comes from the 12–31% of trades held more than 40 bars.
   - In 5 of 6 samples, net P&L is negative without the 5 best trades.
5. **Robust: stops mostly cut real losers.**
   - Only 10% (2017–21) to 17% (2022–26) of stopped trades closed ≥ +20% above entry within 60 days.
   - Stopped trades' 60-day forward return was still negative on average (−6.4% and −3.2%).
   - 38–40% of stopped trades later traded more than 20% below entry.
6. **Robust: the shake-outs concentrate in high-ATR and high-RS names.** Of stopped trades with ATR above 5%, 20% (2017–21) and 41% (2022–26) later rose 20%, against 3% and 7% for ATR below 3.5%. The shaken-out trades first fell a median 2.2–2.5 ATR, so a 2×ATR stop would have saved only about 35–42% of them.
7. **Robust: cash is the main reason for the shortfall.**
   - Average invested fraction was 26–35% in validation and 27–50% in dev.
   - For experiment 1's frozen config, the invested sleeve earned roughly what the benchmark would have earned on the same capital (within −2.9 to +0.8 pp a year) in both periods. The whole CAGR gap was cash.
   - With idle cash parked in MDY/IJR, arm B would have made 13.4% a year in 2017–21, against 12.5% for the blend.
8. **Robust: the strategy has low beta (0.15–0.36).** It beat the blend in the down year of each period (2018, 2022) and lagged in strong up years (2017, 2019, 2021 in validation; arm B in 2023–26).
9. **Fragile (one period only):**
   - the pick's edge (dev +25.7% CAGR, validation −0.6%);
   - its extended, stop-at-cap entries (+8.1% vs −2.0% per trade);
   - turning defensive mode off as an improvement;
   - "let-winners-run" exits being worse;
   - the ATR ≥ 6% bucket (−4.7% vs +8.9%);
   - the 21–40-bar holding bucket.
10. **For experiment 3:**
    - demote the RS ≥ 95 floor (H2) from the primary arm, or pair it with a volatility-aware stop;
    - add a cash-parked arm or overlay, which cuts tracking error from about 20% to about 7% and so tests stock selection instead of market direction;
    - use experiment 1's frozen config, not the pick, as the unchanged reference arm;
    - pre-register these diagnostics, so the forward period acts as a third, independent check.

## Samples and caveats

| Sample | Window | Config | Universe | Trades |
|---|---|---|---|---|
| VAL_A | 2017-01-03..2021-12-31 | V1 rs90 / vol 1.2 / stop .10 / 4 positions (the exp-2 pick) | current S&P 400+600 | 80 |
| VAL_B | 2017-01-03..2021-12-31 | V0 rs70 / 1.6 / .10 / 6 (experiment 1 frozen) | current S&P 400+600 | 159 |
| DEV_A | 2022-01-03..2026-09-24 | same as VAL_A (`x2_V1_rs_90_bre1.2_sto0.1_max4`) | same | 84 |
| DEV_B | 2022-01-03..2026-09-24 | same as VAL_B (`x2_V0_rs_70_bre1.6_sto0.1_max6`) | same | 200 |
| EXP1 | 2022-01-03..2024-06-28 plus 2024-07-01..2026-09-24 | experiment 1 frozen (= V0 rs70/1.6/.10/6) | larger: plus 27 hand-picked extras; older data build | 94 + 91 |

**Pooled** means A+B within a period, with duplicate ticker and entry-date pairs removed: 206 trades for 2017–21 and 255 for 2022–26. RS, ATR, volume ratio and pivot come from the arm's own `candidates.csv`: the `ORDER_SUBMITTED` row on the last signal date before entry. All 708 trades matched, with a median signal-to-entry gap of 1 day. Entry prices equal that day's open exactly.

**Caveats that apply throughout:**
- **Small samples.** Buckets hold 5–60 trades, and a single trade of +100% moves a bucket mean by several points. Rank statistics and win rates are more reliable here than means.
- **Overlap.**
  - A and B in the same period trade some of the same names. EXP1 overlaps DEV in calendar time, so it is not an independent period.
  - Trades inside one run overlap in time and share market moves, so the effective sample is smaller than the trade count, and the bootstrap confidence intervals below (which treat trades as iid) are too narrow.
- **Survivorship.** The universe is today's index members. Stocks that later fell out (delisted, or dropped from the index) are missing, and so are those promoted to the S&P 500. This inflates the forward "rose 20%" rates and the equal-weight benchmark: EW members made 19.9% a year against 12.5% for MDY/IJR in 2017–21.
- **Confounding by config.**
  - In the V0 arms (B, EXP1), defensive mode caps the stop at 6% and the profit target at +11%. 79% (VAL_B), 87% (DEV_B) and 77% (EXP1) of their trades were entered in defensive mode. Their stop distance is therefore mostly the defensive cap, not a property of the setup. The V1 pick arms (A) are the clean read on stop distance.
  - A and B differ in five settings at once, so A − B cannot be attributed to any single one.
- **One-period grid.** The grid covers 2022–26 only. Its blend return was just 6.0% a year there (12.5% in 2017–21), so "beating the blend" in dev was easy.

---

## Q1. Dev-grid parameter effects (2022–26 only)

Method: each comparison holds the variant and the other three parameters fixed, then compares the top level of one parameter with its bottom level. "Monotone" means Sharpe moves in the same direction at every step of that parameter.

**Paired effects (1,188 runs):**

| Parameter (top − bottom level) | Pairs | Mean ΔSharpe | Pairs with ΔSharpe>0 | Mean ΔCAGR (pp) | Pairs with ΔCAGR>0 | Fully monotone (Sharpe), up / down | Families with same sign (Sharpe) |
|---|---|---|---|---|---|---|---|
| rs_threshold (90 − 70) | 396 | −0.143 | 33% | −3.1 | 23% | 15% / 38% | 5 of 6 |
| stop_max_pct (0.10 − 0.06) | 396 | +0.005 | 52% | +0.7 | 61% | 22% / 22% | 4 of 6 |
| max_positions (12 − 4) | 297 | −0.051 | 38% | −3.5 | 22% | 8% / 24% | 4 of 6 |
| breakout_volume (1.6 − 1.2) | 396 | −0.061 | 38% | −1.9 | 31% | 13% / 26% | 5 of 6 |

**By variant family (mean of the matched-pair differences):**

| Family | ΔSharpe rs 90−70 | ΔSharpe stop .10−.06 | ΔSharpe max 12−4 | ΔSharpe vol 1.6−1.2 | ΔCAGR rs 90−70 | ΔCAGR stop .10−.06 | ΔCAGR max 12−4 | ΔCAGR vol 1.6−1.2 |
|---|---|---|---|---|---|---|---|---|
| F1 defensive full (V0,V3) | −0.08 | +0.02 | −0.07 | +0.07 | −0.9 | +0.4 | −1.5 | +0.2 |
| F2 defensive size-only (V2) | +0.10 | +0.12 | −0.07 | −0.05 | −0.3 | +3.0 | −3.9 | −1.3 |
| F3 defensive off (V1,V4) | −0.26 | +0.08 | −0.08 | −0.09 | −4.7 | +2.4 | −5.1 | −2.2 |
| F4 run exits (V5,V8) | −0.11 | −0.15 | +0.05 | −0.12 | −2.3 | −1.7 | −1.7 | −2.0 |
| F5 config sizing (V6,V9) | −0.18 | +0.11 | −0.19 | −0.10 | −3.9 | +3.2 | −7.0 | −3.4 |
| F6 run+config (V7,V10) | −0.20 | −0.10 | +0.04 | −0.08 | −4.9 | −2.0 | −2.2 | −2.5 |

**Level means and the mechanism (exposure):**

| Parameter | Level | Mean Sharpe | Mean CAGR | Mean exposure | Mean trades | Mean win rate | Dev half-1 return | Dev half-2 return |
|---|---|---|---|---|---|---|---|---|
| rs_threshold | 70 | 0.61 | 7.5% | 47% | 153 | 28.2% | +15.6% | +23.5% |
| rs_threshold | 80 | 0.58 | 6.9% | 42% | 142 | 27.4% | +11.2% | +24.7% |
| rs_threshold | 90 | 0.47 | 4.5% | 27% | 104 | 26.4% | +10.4% | +12.2% |
| stop_max_pct | 0.06 | 0.56 | 6.0% | 35% | 146 | 25.7% | +12.0% | +19.2% |
| stop_max_pct | 0.08 | 0.54 | 6.1% | 39% | 133 | 26.9% | +11.7% | +19.7% |
| stop_max_pct | 0.10 | 0.56 | 6.7% | 42% | 120 | 29.5% | +13.4% | +21.6% |
| max_positions | 4 | 0.58 | 8.0% | 46% | 96 | 28.2% | +16.5% | +26.0% |
| max_positions | 6 | 0.56 | 6.7% | 42% | 127 | 27.3% | +13.2% | +21.7% |
| max_positions | 8 | 0.55 | 5.9% | 38% | 146 | 26.9% | +12.0% | +18.3% |
| max_positions | 12 | 0.53 | 4.5% | 30% | 163 | 27.0% | +7.8% | +14.7% |
| breakout_volume | 1.2 | 0.60 | 7.6% | 42% | 150 | 27.6% | +12.5% | +27.0% |
| breakout_volume | 1.4 | 0.51 | 5.6% | 39% | 132 | 27.1% | +10.5% | +18.7% |
| breakout_volume | 1.6 | 0.54 | 5.7% | 35% | 117 | 27.3% | +14.1% | +14.7% |

**Share of Sharpe variance explained (eta²):**

| Factor | Share |
|---|---|
| variant | 37.9% |
| rs_threshold | 5.1% |
| breakout_volume | 2.2% |
| max_positions | 0.5% |
| stop_max_pct | 0.2% |
| all five, additively | 45.8% |

The remaining 54% is parameter interactions and path noise.

**Noise yardstick.**
- One 4.7-year Sharpe has a Lo standard error of about ±0.46.
- The matched-pair differences have a standard deviation of 0.22–0.35.
- So a mean pair effect below about 0.05, or a pair share within 40–60%, is indistinguishable from noise.

**Cross-check against experiment 1's own grid** (2022–24H1, V0, the larger universe, the older data build; same calendar period, so not independent):
- rs 90 − 70: ΔSharpe −0.24, with 17% of pairs positive;
- stop .10 − .06: ΔSharpe +0.16, 64% positive;
- max 12 − 4: ΔSharpe −0.21, 22% positive;
- vol 1.6 − 1.2: ΔSharpe −0.14, 33% positive.

The directions agree with experiment 2.

**Verdicts (one period only):**

| Parameter | Effect size | Monotonic? | Consistency | Reading |
|---|---|---|---|---|
| **rs_threshold** | **Large.** The biggest grid effect: −0.14 Sharpe, −3.1 pp CAGR | Mostly; the 80→90 step carries it (−0.11 vs −0.03 for 70→80) | 5 of 6 families (not V2), both dev halves, exp-1's grid | Real in 2022–26. The mechanism is exposure: 47% → 27%, fewer trades, and a slightly lower win rate. The pick (rs 90) sat against this main effect, on a corner. |
| **max_positions** | Large on CAGR (−3.5 pp), small on Sharpe (−0.05) | CAGR yes (8.0 → 4.5%); Sharpe weakly | Reverses in the run-exit families | Almost pure exposure (46% → 30%): fewer slots mean bigger positions in a strategy that rarely fills its slots. It is a leverage knob, not an edge. |
| **breakout_volume** | Medium (−0.06 Sharpe) | **No.** 1.2 is best, 1.4 worst, 1.6 in between. Dev half 1 favours 1.6 and half 2 favours 1.2 | Reverses in the defensive-full family | Treat as noise, apart from the exposure it adds. |
| **stop_max_pct** | About zero overall (+0.005) | No | The sign depends on the exit family: +0.08 to +0.12 with v1 exits, −0.10 to −0.15 with run exits | An interaction with the exit rule, not a main effect. The 10% cap raises the win rate from 25.7% to 29.5% but loses more per stop. |

---

## Q2. Trade-level patterns, 2017–21 vs 2022–26

Cells read: **n / mean % / median % / win %**. The pooled columns carry the period comparison; the per-arm columns show where each figure comes from.

### 2a. Entry RS percentile

| Bucket | 2017–21 pooled (VAL A+B) | 2022–26 pooled (DEV A+B) | 2022–26 exp-1 (TUNE+HOLDOUT) | VAL_A (pick, 17–21) | DEV_A (pick, 22–26) | VAL_B (frozen, 17–21) | DEV_B (frozen, 22–26) |
|---|---|---|---|---|---|---|---|
| 70–80 | 41 / +2.4 / −3.6 / 44 | 35 / +1.0 / −2.9 / 49 | 34 / +0.2 / −4.0 / 41 | – | – | 41 / +2.4 / −3.6 / 44 | 35 / +1.0 / −2.9 / 49 |
| 80–90 | 53 / +2.7 / −5.3 / 40 | 62 / +0.4 / −6.0 / 35 | 59 / −0.6 / −6.1 / 32 | – | – | 53 / +2.7 / −5.3 / 40 | 62 / +0.4 / −6.0 / 35 |
| 90–95 | 63 / +0.6 / −6.0 / 30 | 63 / +6.5 / −5.1 / 40 | 34 / +2.0 / −5.8 / 41 | 44 / +0.5 / −6.1 / 25 | 34 / +11.1 / −3.9 / 44 | 32 / −0.4 / −5.1 / 34 | 38 / +1.4 / −6.1 / 39 |
| 95–98 | 27 / +6.8 / −4.8 / 44 | 51 / −0.2 / −6.1 / 25 | 24 / −1.3 / −6.1 / 25 | 18 / +7.0 / −3.4 / 44 | 29 / +0.6 / −6.8 / 28 | 18 / +3.3 / −5.4 / 39 | 31 / +0.1 / −6.1 / 29 |
| 98–100 | 22 / −7.8 / −10.2 / 5 | 44 / +0.7 / −6.2 / 27 | 34 / −0.1 / −6.1 / 32 | 18 / −9.0 / −10.2 / **0** | 21 / +5.4 / −10.1 / 33 | 15 / −2.7 / −6.2 / 27 | 34 / −1.4 / −6.1 / 26 |

**Rank correlation of trade return with entry features.** Values are Spearman with 95% bootstrap intervals (500 resamples, trades treated as iid).

| | 2017–21 pooled (n=206) | 2022–26 pooled (n=255) | 2022–26 exp-1 (n=185) |
|---|---|---|---|
| RS percentile | **−0.24 [−0.36, −0.10]** | **−0.20 [−0.32, −0.09]** | −0.13 [−0.28, +0.01] |
| RS, partial on ATR and stop distance | −0.18 | −0.05 | −0.07 |
| ATR14 % | −0.04 [−0.19, +0.10] | −0.24 [−0.36, −0.11] | −0.17 [−0.31, −0.03] |
| Initial stop distance | −0.27 [−0.43, −0.13] | −0.30 [−0.43, −0.16] | −0.25 [−0.41, −0.09] |
| Entry extension over pivot | −0.09 [−0.22, +0.05] | −0.08 [−0.20, +0.04] | −0.14 [−0.27, +0.00] |
| Spearman(RS, ATR) | 0.31 | 0.51 | 0.52 |

**Results by RS band:**

| RS band | 2017–21 | 2022–26 dev | exp-1 |
|---|---|---|---|
| Trades: < 90 / 90–95 / ≥ 95 | 94 / 63 / 49 | 97 / 63 / 95 | 93 / 34 / 58 |
| Win rate: < 90 / 90–95 / ≥ 95 | 41 / 30 / **27%** | 40 / 40 / **26%** | 35 / 41 / **29%** |
| Mean return: < 90 / 90–95 / ≥ 95 | +2.5 / +0.6 / **+0.2%** | +0.6 / +6.5 / **+0.2%** | −0.3 / +2.0 / **−0.6%** |

**Reading:**
- **Both periods agree:** within the trades this machinery takes, higher RS at entry gives a *lower* win rate and no better average.
- High-RS names are more volatile (the RS–ATR correlation is 0.3–0.5), so they hit the stop more often.
- In 2022–26 that volatility explains the RS effect (the partial correlation is −0.05). In 2017–21 it does not (−0.18).
- The one strong RS bucket, 90–95 in 2022–26, is DEV_A's few big winners (mean +11.1%, median −3.9%).

**This does not contradict the model book.** The model book measured ticker-day doubling rates with no stop and no exit rule. The trades here have both. Most of the right tail that high RS offers is converted into stop-outs before it pays.

### 2b. Initial stop distance

In the engine, the stop sits 3% below the pivot, clipped to between 4% and the cap. The 4% floor therefore means the entry was at most about 1% above the pivot, and "at the cap" means an extended entry. In the V0 arms, most trades sit at the 6% defensive cap.

| Bucket | 2017–21 pooled | 2022–26 pooled | 2022–26 exp-1 | VAL_A | DEV_A | VAL_B | DEV_B |
|---|---|---|---|---|---|---|---|
| 4% floor | 11 / +9.1 / −0.3 / 45 | 17 / +1.2 / −4.2 / 35 | 12 / +2.6 / −4.2 / 33 | 6 / +11.7 / −2.2 / 33 | 10 / +4.2 / −1.9 / 50 | 8 / +2.6 / −2.2 / 38 | 11 / +2.8 / −4.2 / 27 |
| 4–7% | 113 / +1.4 / −5.7 / 36 | 159 / +0.6 / −6.1 / 35 | 144 / −0.2 / −6.1 / 34 | 17 / +3.5 / −5.5 / 24 | 13 / +3.5 / −5.1 / 23 | 121 / +0.9 / −6.1 / 38 | 167 / +0.7 / −6.1 / 38 |
| 7–10% | 15 / −4.4 / −8.2 / 7 | 13 / +1.7 / −8.1 / 38 | 4 / +5.3 / +5.2 / 75 | 14 / −4.2 / −8.5 / 7 | 11 / +1.8 / −8.3 / 36 | 1 / −7.4 / −7.4 / 0 | 2 / +1.4 / +1.4 / 50 |
| at the 10% cap | 67 / +1.4 / −6.7 / 36 | 66 / +5.5 / −10.1 / 35 | 25 / −0.6 / −10.1 / 32 | **43 / −2.0 / −10.1 / 28** | **50 / +8.1 / −10.1 / 36** | 29 / +4.4 / −3.4 / 41 | 20 / −4.3 / −10.2 / 25 |

**Reading:**
- **Both periods:** entries at the 4% floor (bought within about 1% of the pivot) were positive in every sample, from +1.2% to +11.7% per trade. The counts are tiny (6–17 per cell), so this is weak evidence.
- **Only one period:** the pick's extended, at-the-cap entries. They made 60% of DEV_A's trades and most of its profit (+8.1% average), but lost in validation (−2.0% average).
- The negative Spearman on stop distance is partly mechanical: a wider stop means a bigger loss when it is hit.

**Entry open vs pivot** (the cleaner variable across configs):

| Bucket | 2017–21 pooled | 2022–26 pooled | exp-1 |
|---|---|---|---|
| 0–2% above | 14 / +3.7 / +4.3 / 50 | 20 / +2.2 / −4.2 / 35 | 15 / +1.8 / −4.2 / 33 |
| 2–4% | 25 / +3.4 / −5.4 / 32 | 23 / +1.9 / −5.7 / 30 | 18 / −0.2 / −5.4 / 33 |
| 4–7% | 29 / −0.8 / −6.2 / 24 | 32 / −1.2 / −6.2 / 25 | 27 / −0.4 / −6.1 / 33 |
| ≥ 7% | 133 / +0.7 / −6.1 / 35 | 175 / +2.5 / −6.1 / 37 | 121 / −0.1 / −6.1 / 35 |

- 0–2% was positive in all three samples, and 4–7% was negative in all three. The pattern is not monotone, because ≥ 7% is flat to positive. Weak evidence.

### 2c. Holding period (bars)

| Bucket | 2017–21 pooled | 2022–26 pooled | 2022–26 exp-1 | VAL_A | DEV_A | VAL_B | DEV_B |
|---|---|---|---|---|---|---|---|
| 1–5 | 53 / −4.6 / −6.2 / 13 | 82 / −3.7 / −6.1 / 15 | 62 / −3.3 / −6.1 / 16 | 18 / −8.7 / −10.0 / 0 | 18 / −7.7 / −8.2 / 0 | 51 / −2.5 / −6.1 / 22 | 73 / −2.5 / −6.1 / 19 |
| 6–10 | 28 / −4.2 / −6.2 / 14 | 43 / −3.5 / −6.2 / 21 | 31 / −3.1 / −6.2 / 19 | 12 / −7.9 / −7.6 / 0 | 11 / −8.8 / −10.2 / 0 | 26 / −2.0 / −6.2 / 23 | 35 / −1.6 / −6.1 / 29 |
| 11–20 | 42 / +0.3 / −6.1 / 38 | 42 / −3.2 / −6.2 / 26 | 29 / −1.6 / −6.1 / 31 | 13 / −6.2 / −9.2 / 8 | 14 / −8.4 / −10.2 / 14 | 33 / +2.9 / −0.3 / 48 | 38 / −0.6 / −6.1 / 34 |
| 21–40 | 34 / −2.1 / −6.1 / 26 | 41 / +5.4 / +2.0 / 56 | 40 / +3.1 / +3.5 / 57 | 12 / −8.0 / −9.9 / 0 | 16 / +8.9 / +1.1 / 56 | 23 / +0.7 / −4.8 / 39 | 30 / +3.9 / +9.5 / 60 |
| 41–80 | 30 / +9.1 / +3.0 / 63 | 34 / +10.1 / +9.0 / 68 | 19 / +7.8 / +2.4 / 68 | 16 / +13.3 / +4.4 / 62 | 15 / +16.5 / +14.9 / 60 | 16 / +5.4 / +3.0 / 69 | 21 / +8.1 / +7.2 / 76 |
| 81+ | 19 / +22.5 / +19.2 / 84 | 13 / +39.9 / +30.0 / 85 | 4 / +20.9 / +16.7 / 75 | 9 / +22.2 / +21.4 / 89 | 10 / +47.4 / +38.0 / 100 | 10 / +22.7 / +18.0 / 80 | 3 / +14.6 / −6.1 / 33 |

**Reading:**
- **Both periods:** trades that last 10 bars or fewer lose, at −3% to −9% on average with 0–23% winners. Everything is earned by trades held more than 40 bars.
- **Only one period:** the 21–40-bar bucket loses in 2017–21 (VAL_A: 0 wins in 12) and wins in 2022–26.
- **Concentration:** removing each sample's 5 best trades leaves net P&L negative everywhere except DEV_A:

  | Sample | Net P&L without its 5 best trades |
  |---|---|
  | VAL_A | −$45.7k |
  | VAL_B | −$1.2k |
  | DEV_B | −$8.0k |
  | EXP1_TUNE | −$21.0k |
  | EXP1_HOLD | −$3.7k |
  | DEV_A | **+$15.8k** (the only exception) |

### 2d. Exit reason

| Exit | 2017–21 pooled | 2022–26 pooled | 2022–26 exp-1 | VAL_A | DEV_A | VAL_B | DEV_B |
|---|---|---|---|---|---|---|---|
| STOP_LOSS | 115 / −7.7 / −6.2 / 0 | 156 / −7.4 / −6.2 / 0 | 113 / −6.9 / −6.2 / 0 | 50 / −9.0 / −10.0 / 0 | 50 / −8.7 / −10.1 / 0 | 88 / −7.0 / −6.2 / 0 | 122 / −6.9 / −6.2 / 0 |
| DISTRIBUTION_BAR | 40 / +9.1 / +1.4 / 55 | 39 / +17.6 / +5.4 / 74 | 23 / +6.9 / +1.9 / 65 | 22 / +10.0 / +2.8 / 55 | 24 / +25.6 / +13.8 / 83 | 19 / +8.5 / +1.1 / 58 | 16 / +4.7 / +1.3 / 62 |
| TRAILING_STOP | 11 / +28.8 / +23.6 / 100 | 11 / +31.1 / +24.2 / 100 | 7 / +15.9 / +7.3 / 100 | 7 / +30.7 / +23.6 / 100 | 10 / +33.1 / +27.1 / 100 | 4 / +25.6 / +21.3 / 100 | 3 / +28.6 / +24.3 / 100 |
| DEFENSIVE_PROFIT_TARGET | 38 / +13.0 / +12.4 / 100 | 49 / +12.7 / +12.3 / 100 | 42 / +12.5 / +12.3 / 100 | – | – | 46 / +12.9 / +12.4 / 100 | 59 / +12.8 / +12.3 / 100 |
| BREAKEVEN_STOP | 2 / −0.3 / −0.3 / 0 | – | – | 1 / −0.3 / −0.3 / 0 | – | 2 / −0.3 / −0.3 / 0 | – |

**Reading:**
- **Both periods:**
  - Stop-loss exits make up 55–63% of trades in every sample, at −7% to −9% each.
  - Trailing-stop exits (+16% to +33%) are rare: 2–4% of trades in the frozen arms and 9–12% in the pick arms.
  - The defensive +11% target caps V0's winners at about +12.5% in every sample.
- **Only one period:** distribution-bar exits averaged +25.6% in DEV_A (median +13.8%), against +10.0% (median +2.8%) in VAL_A.

### 2e. ATR at signal (supporting table)

| Bucket | 2017–21 pooled | 2022–26 pooled | 2022–26 exp-1 |
|---|---|---|---|
| < 2.5% | 47 / +0.4 / −5.2 / 28 | 37 / +2.4 / −1.4 / 49 | 30 / +1.1 / −2.2 / 43 |
| 2.5–3.5% | 63 / +1.1 / −6.1 / 35 | 94 / +1.7 / −6.1 / 37 | 70 / +0.5 / −6.1 / 37 |
| 3.5–4.5% | 55 / +1.0 / −6.2 / 38 | 55 / +2.7 / −6.1 / 35 | 37 / −1.4 / −6.1 / 30 |
| 4.5–6% | 33 / +2.1 / −4.4 / 36 | 52 / +3.5 / −6.1 / 29 | 37 / +1.3 / −6.1 / 32 |
| ≥ 6% | 8 / **+8.9** / −5.2 / 38 | 17 / **−4.7** / −10.1 / 12 | 11 / **−5.2** / −6.2 / 18 |

- The ≥ 6% ATR bucket has opposite signs in the two periods, and n = 8 in 2017–21. It is fragile.

---

## Q3. Stop-outs: the "shaken out" rate

Definition: a stopped trade (exit STOP_LOSS) that **closes ≥ 20% above its entry price within 60 trading days of entry**, counting entry as day 0. Only trades with a full 60-day window are counted, which drops 2 DEV_A, 2 DEV_B and 2 EXP1 trades from the end of 2026. This is a forward look from the trades' own entry dates, used only for diagnosis.

| | VAL_A | VAL_B | DEV_A | DEV_B | EXP1 | **2017–21 pooled** | **2022–26 pooled** |
|---|---|---|---|---|---|---|---|
| Trades (with a full 60-day window) | 80 | 159 | 82 | 198 | 183 | 206 | 251 |
| Share of all trades exiting at the stop | 62.5% | 55.3% | 59.5% | 61.0% | 61.1% | 55.8% | 61.2% |
| Stopped trades | 50 | 88 | 48 | 120 | 111 | 115 | 152 |
| Median bars to stop | 7.5 | 6 | 9 | 6 | 7 | 7 | 7 |
| Stopped within 5 bars | 36% | 45% | 33% | 48% | 45% | 40% | 43% |
| **Shaken out: close ≥ +20% within 60 days** | **14.0%** | **10.2%** | **16.7%** | **16.7%** | **13.5%** | **10.4%** | **17.1%** |
| 95% CI (Clopper–Pearson) | 6–27 | 5–19 | 7–30 | 10–25 | 8–21 | 6–18 | 11–24 |
| Of which reached +20% only after the stop exit | 12.0% | 10.2% | 14.6% | 16.7% | 13.5% | 9.6% | 16.4% |
| The same, measured on intraday highs | 26% | 14% | 19% | 21% | 17% | 17% | 21% |
| The same, within 120 days | 34% | 28% | 31% | 31% | 26% | 28% | 32% |
| Non-stopped trades reaching +20% (close, 60 days) | 40% | 51% | 68% | 47% | 50% | 50% | 52% |
| Stopped trades: 60-day forward return, median / mean | −4.0 / −6.3% | −3.9 / −6.5% | −6.1 / −3.4% | −6.1 / −3.4% | −7.1 / −3.7% | −3.7 / −6.4% | −5.4 / −3.2% |
| Shaken-out trades: median dip before reaching +20% | −11.1% | −8.1% | −11.7% | −10.6% | −9.5% | −8.6% | −11.3% |
| The same, in ATR multiples | 2.5 | 2.3 | 1.9 | 2.4 | 2.5 | 2.4 | 2.2 |

**Did the stops cut real losers or noise?** Pooled figures:

| | 2017–21 | 2022–26 | exp-1 |
|---|---|---|---|
| Realised mean at the stop | −7.7% | −7.4% | −7.0% |
| Same trades, return 60 days after entry | −6.4% | −3.2% | −3.7% |
| Share that were ≥ 20% below entry at day 60 | 17% | 19% | 21% |
| Share that traded ≥ 20% below entry within 60 days | 38% | 40% | 37% |

**Shake-out rate by entry features** (pooled stopped trades):

| | 2017–21 | 2022–26 |
|---|---|---|
| ATR ≤ 3.5% | 3% (n=61) | 7% (n=68) |
| ATR 3.5–5% | 18% (n=39) | 18% (n=57) |
| ATR > 5% | **20%** (n=15) | **41%** (n=27) |
| RS ≤ 90 | 8% (n=48) | 12% (n=52) |
| RS 90–95 | 3% (n=34) | 12% (n=33) |
| RS > 95 | **21%** (n=33) | **24%** (n=67) |

**Stop width vs volatility:**

| | 2017–21 | 2022–26 | exp-1 |
|---|---|---|---|
| Median initial stop, in ATR | 2.07 | 1.75 | 1.70 |
| Stops tighter than 2 ATR | 42% | 62% | 69% |

The shaken-out trades' dip before recovery:

| Shaken-out trades whose dip stayed within… | 2017–21 | 2022–26 | exp-1 |
|---|---|---|---|
| 2 ATR | 42% | 35% | 40% |
| 3 ATR | 83% | 81% | 67% |

**Baseline over all candidate signals.** Each is entered at the next open and held 60 days, with no stop.

| Candidates from | Signals | Close ≥ +20% within 60 days | A 10% intraday stop would hit first | Of those stop-hit-first, later ≥ +20% |
|---|---|---|---|---|
| VAL_B (17–21) | 421 | 26.1% | 52.3% | 5.9% |
| DEV_B (22–26) | 424 | 27.4% | 50.5% | 9.8% |
| VAL_A (17–21) | 378 | 25.9% | 62.4% | 9.3% |
| DEV_A (22–26) | 566 | 29.9% | 60.8% | 12.8% |

**Reading:**
- **Both periods:**
  - Most stops are right. 83–90% of stopped trades never recover to +20% within 60 days, and their average path keeps going down.
  - The shake-outs that do happen are concentrated in high-ATR and high-RS names.
  - About half of all candidates hit a −10% level before a +20% close.
- **Difference between periods:** the shake-out rate was higher in 2022–26 (17% vs 10%; the confidence intervals overlap). It was also more concentrated in high-ATR names (41% vs 20%), consistent with the model book's finding that volatility collides with the stop.
- **Implication:** a stop of about 3 ATR would have kept about 80% of the shaken-out winners. It would also widen the loss on the other 83–90% of stopped trades, whose forward path averages −3% to −6%. Whether that nets out positive cannot be judged from this data without tuning, and should not be.

---

## Q4. Exposure and the cost of cash

Invested fraction = (equity − cash) / equity, daily.

**Counterfactual:** each day, the strategy's return plus (yesterday's cash fraction) × (the benchmark's return that day). This parks idle cash in the index at no cost. It is rough: it ignores the friction of selling the index to fund entries, and it adds index beta and drawdown.

**Gap decomposition** (arithmetic, annualised): benchmark − strategy = cash part + invested part.
- cash part = cash fraction × benchmark return;
- invested part = invested fraction × (benchmark return − strategy return per invested dollar).

A negative invested part means the invested capital beat the benchmark.

**Against the MDY/IJR 50/50 blend:**

| Sample | Average invested | CAGR | Blend CAGR | CAGR with idle cash in blend | Gap (arithmetic) | … from cash | … from the invested sleeve | Beta to blend |
|---|---|---|---|---|---|---|---|---|
| VAL_A (pick, 17–21) | 26.0% | −0.6% | 12.5% | 9.0% | 14.7 pp | 11.8 pp | +2.8 pp (sleeve lagged) | 0.15 |
| VAL_B (frozen, 17–21) | 34.7% | 5.7% | 12.5% | **13.4%** | 8.5 pp | 9.6 pp | −1.1 pp (sleeve beat) | 0.17 |
| DEV_A (pick, 22–26) | 50.5% | 25.7% | 6.0% | 29.5% | −16.5 pp | 4.6 pp | −21.1 pp | 0.36 |
| DEV_B (frozen, 22–26) | 26.7% | 3.0% | 6.0% | 8.5% | 4.7 pp | 7.0 pp | −2.4 pp | 0.18 |
| EXP1 TUNE (22–24H1) | 29.7% | −0.2% | 0.3% | −0.3% | 2.4 pp | 1.8 pp | +0.6 pp | 0.19 |
| EXP1 HOLDOUT (24H2–26) | 31.0% | 3.6% | 13.2% | 16.5% | 10.4 pp | 13.3 pp | −2.9 pp | 0.21 |

**Against the survivorship-matched equal-weight benchmark** (current S&P 400+600 members, rebalanced monthly):

| Sample | EW CAGR | CAGR with idle cash in EW | Cash part | Invested part |
|---|---|---|---|---|
| VAL_A | 19.9% | 14.2% | 16.7 pp | +4.5 pp |
| VAL_B | 19.9% | 18.6% | 14.2 pp | +0.8 pp |
| DEV_A | 10.2% | 32.3% | 6.8 pp | −19.3 pp |
| DEV_B | 10.2% | 11.5% | 9.9 pp | −1.3 pp |
| EXP1 HOLDOUT | 16.7% | 18.2% | 14.7 pp | −1.2 pp |

**Whole dev grid (1,188 runs):**
- The average invested fraction was 39% (IQR 24–52%).
- The cash part had a median of 6.4 pp a year; the invested part had a median of −4.4 pp (IQR −7.1 to −2.1).
- 47% of runs beat the blend's CAGR as they were. 97% would have with idle cash in the blend, but the dev blend made only 6.0% a year.

**Invested fraction by year:**

| Sample | Year 1 | Year 2 | Year 3 | Year 4 | Year 5 |
|---|---|---|---|---|---|
| VAL_A (2017–21) | 34% | 22% | 32% | 24% | 19% |
| VAL_B (2017–21) | 31% | 60% | 22% | 11% | 49% |
| DEV_A (2022–26) | 23% | 47% | 68% | 45% | 76% |
| DEV_B (2022–26) | 12% | 36% | 42% | 21% | 19% |

- The pick's exposure halved out of sample (50% → 26%). The number of candidates the funnel passes, and therefore exposure, is itself period-dependent.

**Calendar-year returns vs the blend:**

| Year | Blend | Arm A | Arm B |
|---|---|---|---|
| 2017 | +13.9 | +4.5 | +6.5 |
| 2018 (down year) | −9.9 | −2.7 | **+10.9** |
| 2019 | +24.3 | −6.2 | −0.2 |
| 2020 | +12.5 | +21.8 | +1.9 |
| 2021 | +25.5 | −16.7 | +9.7 |
| 2022 (down year) | −15.3 | −4.1 | −6.7 |
| 2023 | +16.1 | +33.6 | +10.9 |
| 2024 | +11.2 | +32.0 | +4.5 |
| 2025 | +6.6 | +13.8 | +5.5 |
| 2026 (to 09-24) | +13.2 | +52.8 | +0.6 |

**Tracking error and information ratio vs the blend** (annualised):

| Sample | As is: TE / IR / MaxDD | Idle cash in blend: TE / IR / MaxDD |
|---|---|---|
| VAL_A | 22.3% / −0.66 / −24% | 9.3% / −0.30 / −45% |
| VAL_B | 21.6% / −0.39 / −14% | **7.0% / +0.16** / −45% |
| DEV_A | 20.4% / +0.81 / −15% | 14.8% / +1.42 / −25% |
| DEV_B | 18.3% / −0.25 / −10% | 6.9% / +0.35 / −24% |
| EXP1 HOLDOUT | 17.0% / −0.61 / −15% | 6.7% / +0.43 / −24% |

**Reading:**
- **Both periods:** for the frozen config, the invested sleeve roughly matched the benchmark: within −2.9 to +0.8 pp a year against either the blend or the EW benchmark. The shortfall is almost entirely cash (7–14 pp a year).
- **Both periods:** as the strategy runs, about 70% of its tracking error vs the blend is cash vs index. The test of "beat the blend" is then mostly a test of market direction: it wins in down years and loses in up years.
- **Only one period:** the pick's sleeve beat the blend by about 20 pp a year in dev and lagged it by about 3 pp in validation.
- **Caveat:** parking cash in the index turns a strategy with a 10–24% drawdown into one with a 24–45% drawdown (the 2020 crash). Under the draft's absolute 25% kill rule, such an arm would have been killed in 2020.

---

## Q5. What holds in both periods, and what does not

### Robust lessons (both periods)

| # | Lesson | Evidence |
|---|---|---|
| R1 | **Higher entry RS did not give better trades inside this machinery.** RS ≥ 95 entries: mean about 0, win rate 26–29%, against 35–41% for RS < 90. | Spearman −0.24 (2017–21) and −0.20 (2022–26), both CIs excluding 0; exp-1 −0.13. Consistent with the grid's rs 90 < rs 70 (one period, run level). |
| R2 | **The payoff is extreme right-skew.** 55–63% of trades stop out, fast (median 6–9 bars); win rate 24–39%; all profit comes from the 12–31% of trades held more than 40 bars; net P&L is negative without the 5 best trades in 5 of 6 samples. | Every sample. |
| R3 | **Stops mostly cut real losers.** 10–17% shake-out rate; the stopped trades' own 60-day path averages −3% to −6%; about 40% of them later traded 20% or more below entry. | Every sample. |
| R4 | **Shake-outs cluster in high-ATR and high-RS names,** and the typical shaken-out trade dipped about 2.2–2.5 ATR first. | ATR > 5%: 20% and 41%; RS > 95: 21% and 24%, against single digits for low-ATR names. |
| R5 | **Cash drag is the main cause of the shortfall.** Exposure is 26–50%, and the invested sleeve of the frozen config is roughly benchmark-neutral. | Both periods, both benchmarks, the whole dev grid. |
| R6 | **Low beta (0.15–0.36):** the strategy protects in down years and lags in up years. | 2018, 2022 vs 2017, 2019, 2021 and 2023–26 (arm B). |
| R7 | **The frozen config sits in defensive, half-size mode most of the time.** 77–87% of its trades were defensive entries, which cuts exposure and caps winners at about +12.5%. | VAL_B, DEV_B, EXP1. |
| R8 (weak) | **Entries near the pivot did better.** Entries at the 4% floor, or 0–2% above the pivot, were positive in all three pooled samples; 4–7% above was negative in all three. | n = 11–20 per cell; not monotone. |

### Fragile (one period only)

| # | Pattern | 2022–26 | 2017–21 |
|---|---|---|---|
| F1 | The pick's edge (V1 rs90 / 1.2 / .10 / 4) | +25.7% CAGR; sleeve +21 pp vs the blend | −0.6% CAGR; sleeve −3 pp |
| F2 | The pick's extended, at-the-cap entries | +8.1% per trade (n=50) | −2.0% (n=43) |
| F3 | "Defensive mode off is the big fix" | V1 median CAGR 9.2% vs V0 0.8% | V0 arm B (+5.7%) beat V1 arm A (−0.6%), though five settings are confounded |
| F4 | Every grid parameter effect (RS threshold, max positions, volume, stop cap) and "let-winners-run exits are worse" | measured | untestable at run level; only R1 gives a trade-level echo |
| F5 | The ATR ≥ 6% bucket | −4.7% (n=17) | +8.9% (n=8) |
| F6 | The 21–40-bar holding bucket | +5.4% | −2.1% |
| F7 | Distribution-bar exit size (pick) | +25.6% | +10.0% |
| F8 | RS 95–98 positive, RS 98–100 disastrous | 95–98 −0.2%; 98–100 +0.7% | 95–98 +6.8%; 98–100 −7.8% (VAL_A 0 wins in 18) |
| F9 | Pick exposure | 50% | 26% |

---

## Recommendations for experiment-3 arms

Evidence labels:
- **STRONG**: consistent in both periods, in every sample, with a mechanical explanation.
- **MODERATE**: consistent sign in both periods, with confidence intervals excluding 0 in the pooled data, but trade-level and overlapping.
- **WEAK**: both periods but tiny n, or only one period.
- **PROCESS**: a design or reporting choice, not an empirical claim.

1. **Do not make the RS ≥ 95 floor (H2) the defining feature of the primary arm. MODERATE, against H2.**
   - In both periods, higher-RS entries had lower win rates and no better mean. In the grid, rs 90 < rs 70 (one period).
   - The model-book evidence for H2 is ticker-day doubling rates *without stops*. The trades show that the stop turns that right tail into stop-outs.
   - If H2 stays, pair it with a volatility-aware stop (item 3), and keep an otherwise identical RS ≥ 70 arm (for example B1 without H2) so that H2's contribution is measured rather than assumed.
   - Consider using RS only for ranking.
2. **Add a "cash-parked" arm, or at minimum a pre-registered overlay:** the same signals, with idle cash held in the MDY/IJR blend (or IJH/IJR ETFs). **STRONG for the diagnosis; expected excess about 0 ± a few pp.**
   - It removes the structural up-market lag (R5, R6).
   - It cuts tracking error vs the primary benchmark from about 17–22% to about 7–9%. At the same stock-selection alpha, that roughly triples the information ratio and the test's power (Q4 table). It turns "does it beat the blend?" into the question that matters: "does the invested sleeve beat the index?"
   - Its drawdown is index-like (−24% to −45% in these windows). An absolute 25% drawdown kill would have stopped it in 2020. It needs a **relative** kill instead, for example 15% below the blend.
3. **Volatility-scaled stop with risk-based sizing (P-1, B4): run it only as a secondary arm, and expect little. WEAK.**
   - What supports it (both periods): the stops that shook out winners were on high-ATR names, and 42–69% of stops were tighter than 2 ATR.
   - What limits it: only 35–42% of shaken-out winners stayed within 2 ATR (67–83% within 3 ATR), and the stopped trades that did not recover (83–90%) kept falling.
   - 1% risk sizing is essential: it keeps wider stops from also meaning larger dollar losses.
   - No stop multiple should be fitted to these numbers.
4. **The unchanged reference arm should be experiment 1's frozen config, not the experiment-2 pick. MODERATE.**
   - The pick is shown to be overfit (F1, F2, F9).
   - The frozen config has three out-of-sample windows (exp-1 holdout +3.6% CAGR, validation +5.7%), and its trade-level profile repeats across periods (R2, R3, R5, R7).
   - It still lagged every benchmark: it is the "least-bad, known" reference, not a candidate for money.
   - The draft says the B arms inherit every non-entry setting from arm A. Those settings then become experiment 1's (defensive full, 6 slots, 10% cap, 1.6× volume). Alternatively, state explicitly that defensive-off (V1) was supported in only one period (F3).
5. **Do not tune max positions or the stop cap for experiment 3. MODERATE, as "not an edge".**
   - Max positions only changes exposure, like leverage.
   - The stop cap's effect is about zero and changes sign with the exit rule.
   - If exposure is wanted, get it directly (item 2) rather than through slot count.
6. **"Don't chase" entry filter: log it, do not trade it yet. WEAK.** Record extension-over-pivot for every candidate. Entries within about 2% of the pivot were positive in both periods, but n is about 11–20.
7. **Pre-register these both-period diagnostics as descriptive outputs of every look. PROCESS.**
   - stop-out share and median bars to stop;
   - the shake-out rate (+20% within 60 days after a stop), by ATR and RS;
   - win rate by RS band;
   - invested fraction, and the cash-parked counterfactual with its cash/invested split;
   - top-5-trade concentration.

   The forward period is then a *third* independent test of R1–R8, which matters because the arms themselves are unpowered for years (a Sharpe of 1.0 needs about 4.5–6 years).
8. **Expect the forward test to be dominated by market direction** unless item 2 is adopted. **STRONG** (R5, R6): with 26–50% exposure and beta 0.15–0.36, one strong up-year for small caps produces a 10–40 pp shortfall regardless of signal quality (2019, 2021).
