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

### Amendment 3 addendum: data freeze record

Written on 2026-09-26 (about 05:00 EDT), before the development bundle was built and before any development result. Nothing below changes a rule. It records the final data.

- **Split table: 197 events,** 172 of them added in this project.
  - 101 from the 2014-2021 research, 7 missed stock dividends, 3 from the identity check (PLUS 2021-12-13 2:1, IVT 2021-08-05 1:10, PECO 2021-07-02 1:3), and 70 from a universe-wide restatement scan (54 tickers; recall 112/115 on known events). The scan includes CBSH 2022-2025 and TR 2022-2026 stock dividends, which the 2021+ table had missed.
  - The same event found twice is kept once (±5 days).
  - One lead ruling: SIRI 2024-09-09, a 1-for-10 share exchange applied for per-share continuity. Yahoo booked it as a split, and the registrant restated per-share history.
  - Not merged: ALLY 2014 and TRU 2015 (unverified, pre-IPO).
- **Split evidence** (`us_fundamentals/verify_splits_vs_restatements.py`): each company's first-filed EPS is compared with its own post-split restatement. In `test_split_adjustment.py` TEST 7, a restatement-confirmed event passes even where the NI/EPS proxy cannot resolve it. Events with neither restatement nor proxy evidence are listed as UNVERIFIED, kept on their filing text.
- **History breaks, 30 rows** (`kashif_engine/data/history_breaks.csv`, from the identity check):
  - price cuts: AA, PPLI, IVT, PECO;
  - SPAC and bankruptcy lineage (price and fundamentals): CHRD, WSC, PR, MGY, VRRM, AHCO, MP, RSI, HIMS, MIR, DAVE;
  - reverse mergers and fresh starts (fundamentals only): KNTK×2, ASTH, OPCH, SKY, DCOM, MTCH, CRC, VAL, GPOR, TDW, BTU, WFRD, LEU;
  - one bad bar: PRG 2021-04-06.
- **Pipeline bugs found by the 2020+ diff,** fixed and root-caused before the final store:
  1. A fiscal-year change (CWST April→December 2014) was read as a missing year, shifting every later fiscal year by one.
  2. FY share counts were not renumbered with the annuals.
  3. The Q4 share derivation restated quarterly shares for a split even when the 10-K's FY shares were not restated. AGNT/EXPI Q4 2020 EPS came out 0.47 instead of 0.05.

  Check 5 now compares against the neighbouring ±6 quarters (secular dilution such as MARA's is not an error), and rejects only when both total NI and NI to common are off (CELH).
- **Two more fixes from an independent audit** of 40 random 2015-2019 rows against press releases (by a peer session), before the final store:
  1. **Lookahead:** the 8-K overlay took the FIRST Item 2.02 after quarter end, but pre-announcements are Item 2.02 too (WING 2019-01-14 "preliminary sales", 44 days before the full release). It now takes the LATEST 2.02 on or before the 10-Q/10-K filing, which is never earlier than the results release. This also affected the 2020+ data experiment 1 used.
  2. **Asymmetry:** a later value within rounding of the first-reported one (≤0.5%, ≤1¢ EPS) keeps the first-reported value and its 10-Q date. The pre-2021 10-K quarterly note (rounded to $0.1M) used to date 12-18% of 2014-2020 Q1-Q3 rows to the next year's 10-K.
  - Known limitation: genuinely restated quarters (e.g. AIN 2018, the CWEN drop-down recast) keep the restated value dated at the restating filing. The store holds one version per quarter, so such a quarter is invisible between its 10-Q and the restatement. That is conservative, and more frequent before 2021.
  3. **Q4 basis:** Q4 was derived as FY (from the 10-K, restated) minus the ORIGINAL Q3 10-Q's 9-month YTD. When the 10-K restated Q1-Q3, that mixed bases (AIN Q4 2018: EPS 0.43, against 0.54 on one basis and in the press release). Q4 is now FY minus the restated quarters whenever any of them was restated beyond rounding.
  4. **Q4 window and arbitration:** Q1-Q3 of a fiscal year must end 60-300 days before its year end. With history from 2012 an annual can be missing (QRVO FY2017/2019, TLN around its bankruptcy), and "every quarter since the last annual" took the wrong year's quarters (QRVO Q4 FY2020 EPS 2.20 instead of 0.43).
     - The restated-quarters derivation (fix 3) is used only when the 10-K's own 3-month Q4 fact can arbitrate between the two derivations.
     - On 48 Q4 EPS values that changed by 3¢ or more against the committed store, the four-quarter sum was checked against the 10-K's annual EPS. That check found the regressions fixed here. Mid-year splits (RUSHA, AAON 2023) make the check itself unreliable; for those, the new values match the companies' reported Q4 EPS.
- **Correction, from an adversarial code review by a peer session:** the sentence above, "Rejection only makes a screen fail, so it is conservative", is **false** in general.
  - By the screen's own rules, a missing quarter inside Q2's four-growth-value window, or a missing annual EPS, makes Q2 or Q4 SKIP, which counts as a pass. The screen says so for Q4: "must not reject a stock purely for a gap in the annual feed".
  - So a rejected mid-history EPS can turn a Q2/Q4 FAIL into a pass. Only a rejected latest or year-ago quarter is strictly conservative (the screen returns SKIP).
  - This leniency is the strategy's rule and applies identically in both windows. It is kept, not changed.
  - Affected by this amendment's removals: the 17 Check-5 rows (11 tickers), and quarters before a history break. A break is treated like a new listing, the natural analogue for a de-SPAC or fresh start. FIZZ is excluded entirely (latest EPS missing → SKIP).
  5. **Q4 EPS from the company's own fact:** when the 10-K's 3-month Q4 EPS disagrees with NI / derived shares (by >5¢ and >10%) and is plausible, it replaces the derivation. Plausible means |EPS| < 1000, the sign of Q4 NI, and EPS × Q3 diluted shares within 50% of Q4 NI. Derived Q4 shares break in merger and split years (KNX 2017: 6.01 against the reported 2.50). The audit counted 24 such fiscal years among 303 restated ones.
  - **Audit result on the final store** (40 random 2015-2019 rows against press releases): EPS 36/38, revenue 36/38, NI 36/37, release date 31/38, with **zero** dates earlier than the results release. The remaining mismatches are one-day 8-K lags, recasts dated at the recasting filing, an mREIT revenue definition, and late dates.
  - **Known residuals, reported and not fixed:**
    - the validation window's Q1-Q3 rows are dated more than 120 days after quarter end 9-15% of the time, against 2-5% after 2021 (genuine restatements dated at the restating filing), a handicap for the validation window;
    - some Q4 EPS in restated fiscal years stay off (TRN 2018, and the NI-and-EPS-disagree bucket);
    - identical 10-Q/10-K values dated at the 10-K when the fiscal-year tags differ (JBSS).
