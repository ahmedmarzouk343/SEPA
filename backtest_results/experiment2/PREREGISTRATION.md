# Experiment 2: pre-registration

Written and committed on 2026-09-26, before any experiment-2 backtest ran.

## Question

Can the two measured drags be removed and produce a strategy that beats its benchmark **on data never used for any decision**? The two drags are:

- defensive mode, active at about 80% of trade closes (11% profit cap, half size);
- a regime gate that is open 95% of the time.

## Data

- **Universe** *(superseded by Amendment 1: S&P 400+600 members only)*: the same 1,029 tickers as experiment 1 (current S&P 400/600 members plus 27 extras). The survivorship bias is larger the further back the window goes, and it is reported through the equal-weight benchmark gap.
- **Prices:** Yahoo, back-filled from 2014-06. Every 2019+ bar must be unchanged versus the experiment-1 cache, and this is checked.
- **Fundamentals** *(superseded by Amendment 1: back-filled to 2014, and 8-K dates back to 2014)*: back-filled to 2015 quarters.
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
- **Verdict** *(superseded by Amendment 1 point 2 and Amendment 2)*: arm A beats MDY/IJR 50/50 on **both** CAGR and Sharpe.
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

## Amendment 2

Made on 2026-09-26, after a second review by the parallel session and before any experiment-2 backtest.

1. **INVALID verdict.** If the independent auditor does not match the ledger exactly for an arm, that arm's verdict is **INVALID**, whatever its returns.
2. **Credit for the changes.** Arm A minus arm B daily returns get the same stationary bootstrap (one-sided, block 20, 10,000 resamples, seed 7). The two changes get credit only if **p < 0.10 and A's CAGR is above B's**. Otherwise the report says the changes were not shown to help.
3. **Deflated Sharpe.** The development-window DSR is also reported on daily excess returns over the MDY/IJR blend and over the equal-weight member basket. It uses var_sr = 1/(T-1), which assumes null, iid trials.
4. **Lock and panel.** The validation runner refuses to start with uncommitted code or rule files. The lock stores `git status --porcelain` and a hash of the US_idx panel, which the runner rebuilds from the price cache immediately before locking.
5. **Bundles.** Each bundle records the panel it was built on. The strategy refuses a bundle whose panel or universe does not match.

## Amendment 3

Made on 2026-09-26 (about 02:30 EDT). No experiment-2 development result had been read at this point. A first dev launch was stopped at 57/540 runs once the data under it was found to be changing. Those runs were moved to `kashif_data/experiment2_stale_runs_unread/` without being opened, and they are not used. **Where this amendment conflicts with the text above, it wins.**

1. **Data, final for both windows.** The split table and the store are frozen when the development bundle is built. Verified finds that arrive later are reported, not merged.
   - **Fundamentals** are rebuilt from 2014 quarters. The SEC extraction starts in 2012-07, so each quarter's value comes from its original filing. Release dates come from 8-K Item 2.02 back to 2014.
   - **The pre-registered check "every 2020+ value unchanged"** is replaced by a reported diff. Each class of change is root-caused, because the old store's earliest quarters were extracted with a later cutoff.
   - **101 verified 2014-2021 splits and stock dividends** are merged, including 7 stock dividends Yahoo missed (TR, SBSI, CBSH).
     - Rule: apply a split only if it was done by the registrant whose filings form the stored EPS series.
     - Excluded under that rule: AA 2016-10-05 (Alcoa Inc., not Alcoa Corp), OVV 2020-01-24 (Encana), OZK 2014-06-23 (no fundamentals), UA 2016-06-29 (Class C dividend handled in the EPS numerator).
     - A universe-wide scan for other missed stock dividends is running. Its VERIFIED rows are merged only if they arrive before the freeze.
   - **VTOL price correction:** Yahoo booked Era Group's 1-for-3 reverse split (2020-06-11, filing 0001140361-20-014075) as 1-for-2. Bars before 2020-06-12 are corrected ×1.5 at load time; the cache file is not edited.
   - **New pipeline check (Check 5):** an EPS whose implied share count (NI / EPS, split-adjusted) is more than 30× off the ticker's median is rejected, never rescaled. This covers FOUR's two Q4 EPS values from a bad share count, and pre-IPO quarters on another share basis.
   - **FIZZ EPS is dropped entirely.** Its XBRL tags EPS in cents as dollars and shares in thousands as units.
   - Rejection only makes a screen fail, so it is conservative.
2. **Six more variants,** factorial on the two defensive-off variants, V1 (OR gate) and V4 (2-of-3 gate):
   - `exit_mode: run` ("E"):
     - The largest-decline-on-volume signal becomes an exit-candidate *flag* (the config's own wording) instead of an exit.
     - The trailing stop becomes the 50-day line less the 5% buffer, raised every bar, with no 15% give-back.
     - Motivation, from experiment 1's trades (inside the dev window): only 4 (tune) and 9 (holdout) trades ever reached +20%. Distribution-bar exits kept +5-10% of +14-17% peaks.
   - `scaling: config` ("C"): the config v0.28.1 `performance_scaling`. The losing-streak step-down is REMOVED there, and the re-entry pilot is 75%. The code had kept the older 40%/20% step-downs and a 50% pilot.

   | ID | defensive | gate | exit_mode | scaling |
   |---|---|---|---|---|
   | V5 | off | 1 (OR) | run | v1 |
   | V6 | off | 1 (OR) | v1 | config |
   | V7 | off | 1 (OR) | run | config |
   | V8 | off | 2 of 3 | run | v1 |
   | V9 | off | 2 of 3 | v1 | config |
   | V10 | off | 2 of 3 | run | config |

   The grid is unchanged: 11 variants × 108 = **1,188 development backtests**.
3. **Selection, verdict and arms are unchanged.**
   - The pick is the best neighbour-median Sharpe over all 11 variants, under the same constraints.
   - Arm B stays V0 with experiment 1's frozen parameters. Defaults of the new switches reproduce experiment 1 exactly, and this is tested.
   - The Deflated Sharpe is reported with N = 1,188 (every run) and N = 50.
4. **No leverage and no return target in the rules.** The owner asked for the highest possible return (more than 200% a year).
   - The objective stays risk-adjusted: Sharpe, which leverage cannot improve.
   - The report states plainly what the untouched window shows.
   - Leverage would scale a real edge; it cannot create one.
5. **No LLM judgment in either window.** Every available LLM was trained on text covering 2017-2026, so an LLM "evaluating" a 2017-2021 news item already knows how the story ended. That is lookahead that no prompt can remove. An AI-agent catalyst evaluator can only be tested forward, from 2026-09-25, in paper trading.
