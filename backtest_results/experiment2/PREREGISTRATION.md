# Experiment 2: pre-registration

Written and committed on 2026-09-26, before any experiment-2 backtest ran.

## Question

Can the two measured drags be removed and produce a strategy that beats its benchmark **on data never used for any decision**? The two drags are:

- defensive mode, active at about 80% of trade closes (11% profit cap, half size);
- a regime gate that is open 95% of the time.

## Data

- **Universe:** the same 1,029 tickers as experiment 1 (current S&P 400/600 members plus 27 extras). The survivorship bias is larger the further back the window goes, and it is reported through the equal-weight benchmark gap.
- **Prices:** Yahoo, back-filled from 2014-06. Every 2019+ bar must be unchanged versus the experiment-1 cache, and this is checked.
- **Fundamentals:** back-filled to 2015 quarters.
  - Pre-2020 release dates stay the SEC filing dates, since the 8-K overlay only covers 2020+. That is conservative.
  - Pre-2021 stock splits are verified by an independent session before the validation window is prepared.
  - Every 2020+ value must be unchanged, and this is checked.
- **Catalyst:** OFF. It showed zero effect in experiment 1.

## Development window (in-sample; may be used freely)

**2022-01-03 .. 2026-09-24.** This covers experiment 1's tuning window and its already-consumed holdout.

### Variants

Only the two measured drags change. Everything else is the experiment-1 strategy.

| ID | defensive_mode | regime_min_conditions |
|---|---|---|
| V0 | full (experiment 1) | 1 (OR gate, experiment 1) |
| V1 | off | 1 |
| V2 | size_only (half size; no 6% stop cap, no 11% target) | 1 |
| V3 | full | 2 (2 of 3 conditions) |
| V4 | off | 2 |

### Grid

The same as experiment 1 for each variant:

- RS {70, 80, 90}
- breakout volume {1.2, 1.4, 1.6}
- max stop {6, 8, 10}%
- max positions {4, 6, 8, 12}

That is **5 × 108 = 540 backtests**, each over the full development window.

### Selection rule

1. The objective is the **neighbour-median daily Sharpe** (rf = 0), with neighbours meaning one grid step in one parameter within the same variant. Failing neighbours count as −inf.
2. Hard constraints:
   - at least 60 closed trades;
   - max drawdown ≤ 25%;
   - auditor passed;
   - **positive total return in both halves** (2022-01-03..2024-06-28 and 2024-07-01..2026-09-24, measured on the combination's own equity curve).
3. The pick is the single combination (variant + parameters) with the highest objective among those meeting every constraint.

## Validation window (fresh, run ONCE)

**2017-01-03 .. 2021-12-31.** No experiment-2 or experiment-1 backtest has ever traded in it.

- **Arm A (verdict):** the pick.
- **Arm B (reference):** V0 with experiment 1's frozen parameters (RS 70 / 1.6 / 10% / 6).
- **Benchmarks:** MDY, IJR, MDY/IJR 50/50, SPY, and the equal-weight S&P 400+600 basket rebalanced monthly (whose gap is labelled "survivorship + weighting").
- **Verdict:** arm A beats MDY/IJR 50/50 on **both** CAGR and Sharpe.
- **Also reported:**
  - the Lo (2002) Sharpe standard error;
  - returns per calendar year against the benchmark;
  - the membership split (hand-picked extras vs index members);
  - exit reasons;
  - the auditor result.
- **Lock:** `kashif_data/experiment2/VALIDATION_LOCK` stores the SHA-256 of this file, the selection and the config, plus the git commit. Code refuses any other run that trades in the window, and refuses a second validation run.
- **If the pick fails,** that is the result. Any further change is validated only by forward paper trading from 2026-09-25.

## Amendment 1

Made on 2026-09-26, after an adversarial review by a parallel session and before any experiment-2 backtest. **Where this amendment conflicts with the text above, it wins.**

1. **Universe.** Current S&P 400 + S&P 600 members only. The 27 hand-picked extras (NVDA, AMZN, MSFT, GOOGL, SMCI, ...) are removed from ranking, regime breadth and trading, in both windows.
2. **Verdict**, three outcomes, fixed now.
   - **PASS** requires all of:
     - arm A's CAGR **and** Sharpe beat **both** the MDY/IJR 50/50 blend **and** the equal-weight, monthly-rebalanced current-member S&P 400+600 basket (which carries the same survivorship as the universe);
     - a one-sided stationary block bootstrap (mean block 20 days, 10,000 resamples, seed 7) of arm A's daily excess return over that equal-weight basket gives **p < 0.10**.
   - **FAIL:** arm A's CAGR is below the MDY/IJR 50/50 blend.
   - **INCONCLUSIVE:** anything else.
3. **Reading arm B.** The two changes get credit only for arm A minus arm B, which share the window, universe and data. If arm B also PASSes, the win is attributed to the window and universe, not to the changes.
4. **Data.**
   - Fundamentals are back-filled to **2014** quarters, so the Q2 and Q4 screens have full history from January 2017.
   - Pre-2021 splits are merged only after primary-source verification.
   - 8-K press-release dates are extended back to 2014, so both windows use the same release-date method.
   - The validation window stays 2017-01-03 .. 2021-12-31.
5. **Known distortions, declared now so they can't later be used as excuses or as reasons to change rules:**
   - the Q4-2017 GAAP EPS one-offs from the US tax reform;
   - the ASC 606 revenue-concept switch in 2018;
   - COVID-2020 earnings swings.
6. **Reporting the pick's development result.** Report its Deflated Sharpe Ratio (Bailey & López de Prado) with N = 540 and N = 50 effective trials. A development Sharpe below about 1.3 is consistent with zero edge after selection among 540 trials.
7. **Lock contents.** The lock also stores a SHA-256 of the price cache and the fundamentals store, and `run_validation2.py` is committed before the first development run.
