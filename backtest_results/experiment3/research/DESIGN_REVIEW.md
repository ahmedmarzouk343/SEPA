# Experiment 3: design review (statistician)

Written 2026-09-26. The reviewer was read-only on the repo. This review covers `backtest_results/experiment3/PREREGISTRATION_DRAFT.md`, as committed in 7857cac.

- **Every empirical number here comes from the development window only** (2022-01-03..2026-09-24):
  - the 1,188 experiment-2 dev runs (`kashif_data/experiment2/runs/`);
  - the model-book ticker-day table (`kashif_data/experiment2/model_book_dev/days.parquet`, `tt_px.parquet`);
  - MDY and IJR from `kashif_data/prices/US/`.
- **No 2017–2021 cross-section was opened for this review.** Only the already-published experiment-2 validation aggregates are quoted.
- **Scratch scripts** (not in the repo) are in `%TEMP%\claude\...\scratchpad\statistician\`: `port_stats.py`, `signal_stats.py`, `matched_stats.py`, `power.py` and `counts.py`.

---

## 0. Summary of recommendations

1. **Run experiment 3a**, a one-shot pseudo-out-of-sample check of the frozen B1/B2/B3 on 2017–2021. It can only kill (see §1).
   - It is legitimate because H1–H5 and the arm table were committed in 7857cac (14:34:47 +0300), before the validation was claimed (d59d521, 14:42:50) and before its results existed (3c034de, 14:49:06).
   - The forward test stays valid whatever 3a shows, as long as the rule that maps 3a outcomes to forward arms is committed before 3a runs.
2. **Change the primary metric.** Today it is raw excess over MDY/IJR. It should become **swept excess**: the arm with its idle cash held in the benchmark, minus the benchmark, i.e. x_t = r_arm,t − e_{t−1}·r_bench,t.
   - The raw excess has 18% tracking error (TE) because the arms are only 26–50% invested.
   - It also carries a built-in drag of about −(1−β)·E[r_bench] ≈ −5 to −6% a year even with zero skill.
   - Swept excess halves the TE (about 8.4–11.6%) and removes the drag.
3. **Benchmark for the test: the equal-weight basket of the frozen 2026-09-25 universe**, including delisting returns. Going forward it has no survivorship bias, and it is the arms' own opportunity set.
   - MDY/IJR stays as an investability gate: PASS also requires the swept arm's CAGR to be above the blend's.
4. **Be honest about power.** The draft's arithmetic is correct, but "excess Sharpe 1.0" means about +18% a year over the blend, which is not a realistic alternative.
   - With the swept metric, a max-4 book needs a true **+11% a year** of swept alpha to be detected at 80% power in 5 years.
   - Plausible edges of 2–4% a year take 38–150 years.
   - The forward test can therefore **falsify, or catch a very large edge**. It cannot confirm a modest one.
5. **Shrink the confirmatory set to 1 primary and 2 secondaries.**
   - Primary: the portfolio arm (B1 by default).
   - Secondaries (Holm over 2, at α 0.05/0.10): S1 is the primary arm's signals as a calendar-time portfolio; S2 is the arm-C LLM rating as a within-day signal contrast.
   - A is dropped. B2, B3, portfolio C, B4 and every pairwise contrast become pre-registered **descriptive** results.
6. **Signal-level measurement is necessary, but its gain is smaller than it looks.**
   - B1 gives about 82 de-duplicated signals a year (about 200 candidate-days).
   - They cluster (design effect 2.4–2.9 by month; calendar-time TE 22–30%), so the effective N is only about 16–60 a year.
   - Against the EW universe, per unit of true signal alpha, signal-level power is about the same as the book's.
   - The real gains are:
     - contrasts that cancel the common factor: an RS-matched benchmark roughly halves TE, which means 3–5× fewer years;
     - arm C's within-day rating test, which is the only feasible test of the LLM;
     - freedom from slot, exit and sizing path noise.
7. **Early stopping.**
   - Keep the Haybittle–Peto efficacy looks (p < 0.005 at 24 and 36 months).
   - Make the 24-month futility look **non-binding**, and base it on the same statistic as the test. The draft mixes "excess Sharpe ≤ 0" with "excess CAGR ≤ 0".
   - Replace the 100-trade minimum with 60, because max-4 arms trade only about 18–30 times a year.
   - Relabel the 25% drawdown kill as **FAIL (risk)**, not FAIL (no edge).
8. **Recalibrate the "broken arm" flag.** "Fewer than 10 trades in 6 months" fires in **48%** of half-years for a correctly working max-4 arm (dev). Flag on signal counts instead: fewer than 12 de-duplicated signals, or 0 entries, in a half-year with the regime gate open.
9. **Harness requirements:**
   - pre-commit and push, with timestamps witnessed by the remote and by an external timestamping service (git commit dates are set by the client);
   - each day's order file pushed **before the next open**;
   - raw, unadjusted snapshots, with a hash chain;
   - a frozen code and environment lock;
   - a rule that a day not witnessed on time takes no new entries;
   - a rehearsal proving the forward harness equals the backtest engine day by day;
   - health-only dashboards between looks.
10. **Set expectations now.** In-sample, the evidence for B1 on the metric that decides money is weak: its signals' calendar-time 60-day excess has IR 0.40, t ≈ 0.9, and the 20-day excess is negative. A realistic prior for the forward IR is at most about 0.3. Both 3a and the forward test are best seen as falsification tests.

---

## 1. Experiment 3a: legitimate, with rules

### 1.1 Is it legitimate?

**Yes, as a falsification screen. It is not confirmation.** Three facts decide this:

1. **The definitions pre-date the exposure, provably.**
   - `MODEL_BOOK_DEV.md` (H1–H5) and `PREREGISTRATION_DRAFT.md` (arms B1, B2, B3, C and P-1) were added in commit **7857cac at 14:34:47 +0300**.
   - The 2017–2021 window was claimed at **d59d521, 14:42:50**, and its results were written at **3c034de, 14:49:06**.
   - The model book's own "Rules followed" states that nothing in 2017–2021 was looked at.
   - So the arms were not derived or tuned on 2017–2021. This is the property that matters most.
2. **3a cannot harm the forward test.** Selecting or dropping arms on data independent of the forward data does not change the forward test's type-I error, conditional on the selection. The condition is that the forward rules, including how 3a outcomes map to forward arms, are frozen **before** 3a runs. At worst, contamination in 3a wastes forward power by dropping a good arm or keeping a bad one. It cannot create a false forward PASS.
3. **3a is the largest sample available before 2031.**
   - Five years at once gives SE(IR) ≈ √(1.0–1.3 / 5) ≈ 0.45–0.51.
   - No forward look before 2031 is that precise.

The model book says each hypothesis is "to be validated forward, not on 2017–2021", and the draft says 2017–2021 "is not used here". Those guards protected experiment 2's one-shot window, which is now locked, so they have done their job.
- 3a is still a **deviation from committed text**.
- It must be adopted by a dated amendment that states this reason, before 3a runs.

### 1.2 How big is the contamination?

| Channel | Size | Control |
|---|---|---|
| Arm definitions (H1, H2, H3, H5 and the arm table) | **None.** They were committed before exposure. | Implement exactly the 7857cac text. |
| Implementation details the text leaves open: H3's "ranking penalty" size, H2's tie-breaks, B3's exact early-path test, ranking order | **Potentially the whole margin.** Choosing the best of k = 3 options with knowledge of the window buys E[max] ≈ 0.85 SE, which is about 0.4 IR on a 5-year screen, the same size as the kill threshold's SE. | Fix every open detail by a neutral rule written before the run (§1.3 step 1c), and have a peer diff-review the code against the 7857cac text. |
| Non-entry settings (exits, stop, slots, sizing, gate) | **None, if inherited.** Changing them now, for example max positions 4 → 8, would be a choice made after seeing A's 2017–2021 result. | Inherit `selection2.json` (sha256 0f256910…) exactly: V1, defensive off, OR gate, stop 10%, max 4 positions, volume 1.2×. Only RS changes, 90 → 95, per H2. |
| The lead knows experiment 2's 2017–2021 outcome (A lost 0.6% a year; 50 of 80 trades stopped; 2019 and 2021 were bad) | **Moderate, but it shifts the prior down; it does not bias the screen.** B1 shares A's machinery, so the lead expects B1 to struggle too. It becomes a bias only if it steers the open details above. | As above. Also report B1 − A, a paired contrast on the same window, where A is fixed and known. |
| General knowledge of the 2017–2021 market (the 2018 Q4 sell-off, the 2020 crash and rebound, the 2021 small-cap boom) | Low. Anyone has it, and it cannot have shaped rules written before exposure. | None needed. |
| Data changes after exposure | **High if allowed.** | Use experiment 2's frozen validation inputs byte for byte: the bundle, the panel and the hashes in `VALIDATION_LOCK`. No data fixes. The known residuals (late restated quarters) are declared now. |
| Survivorship (current members only) | Structural. Arm and EW basket share it, but momentum names delist more often, so the screen probably **favours** the arms. | Accept it. It makes the screen lenient (fewer kills), which suits a kill-only screen. Declare it. |
| LLM lookahead | Would be total. | Arm C is excluded from 3a, as the draft says. |

**Overall:** the contamination is small **if** zero degrees of freedom remain. Label the results "**pseudo-out-of-sample**: definitions fixed before the data were seen; analysts not blind to the period or to experiment 2's results; survivorship-biased universe".

### 1.3 The protocol

1. **Freeze.** A single commit, pushed and tagged `exp3a-freeze`, **before any 2017–2021 run**, containing:
   - a. the final experiment-3 forward pre-registration, including the mapping rule in step 6;
   - b. this 3a protocol and its verdict rule, as a dated amendment that notes the deviation from the model book's "not on 2017–2021";
   - c. the code for B1, B2 and B3, with unit tests. Every detail not fixed by the 7857cac text is listed with its neutral default. Proposed defaults:
     - **H2:** rank by RS percentile descending; ties broken by the engine's existing rank score, then by ticker.
     - **H3:** a single Q2 or Q4 failure ranks below every candidate that passes all four checks (a lexicographic penalty, so there is no magnitude to choose).
     - **H5:** tt_1, tt_2 and tt_7 on the same bar, RS ≥ 95, with the same breakout trigger and the same fundamentals rule as B2.
   - d. a peer diff review signed off in the commit message;
   - e. non-entry settings taken from `selection2.json` by hash;
   - f. the data: experiment 2's validation bundle, panel, price and store hashes;
   - g. a passing rehearsal on a dev slice (2024-01-02..2024-06-28, as in experiment 2).
2. **Run once**, under a new claim and lock (`VALIDATION3A_LOCK`): claim, push, run, results, lock. The runner refuses a second run.
   - The experiment-2 lock and results are never modified.
   - Only B1, B2 and B3 run, once each.
3. **Outputs per arm:**
   - the primary screen statistic, the mean daily **swept excess over the equal-weight current-member S&P 400+600 basket**, with bootstrap CI;
   - the same against the MDY/IJR blend;
   - the unswept excess (the draft's metric);
   - CAGR, maximum drawdown, trades, exits and calendar years;
   - the signal-level calendar-time 60-day excess against the EW basket;
   - B − A as a paired daily difference;
   - the auditor result.
4. **Verdict per arm: KILLED, NOT FALSIFIED or UNSCREENED.**
   - **KILLED** if the swept excess over the EW basket has a point estimate ≤ 0.
   - **UNSCREENED** if the auditor does not match. There is no rerun; the arm goes forward with a note.
   - **NOT FALSIFIED** otherwise.
   - Crossing the 25% drawdown is reported as a **flag**, not a kill. A crash drawdown is evidence about risk, not about edge.
5. **Error rates of the kill rule** (5 years; VIF 1.0 / 1.3; see T9):

   | True swept IR | 0 | 0.25 | 0.5 | 0.75 | 1.0 |
   |---|---|---|---|---|---|
   | P(killed) | 50% / 50% | 29% / 31% | 13% / 16% | 5% / 7% | 1% / 3% |

   A stricter bar (observed IR ≤ 0.2) would kill a true-0.5 arm 25–28% of the time, which is too harsh for a contaminated, survivorship-biased screen.
6. **Mapping to the forward test** (fixed in step 1):
   - The forward **primary** is the first NOT FALSIFIED (or UNSCREENED) arm in the fixed order **B1 → B2 → B3**.
   - Killed arms leave the confirmatory family. They may keep running forward at no cost, labelled "killed in 3a", as descriptive results only.
   - If all three are killed, there is no confirmatory portfolio test. The forward experiment keeps S2 (the arm-C rating test) and the descriptive log, and the owner decides whether the B family continues at all.
   - Nothing else may change because of 3a: no parameters, metrics, thresholds, looks or definitions.
7. **What a 3a pass means.** "Not falsified" is **necessary, not sufficient**.
   - It may never be quoted as evidence of an edge.
   - It is never pooled with forward data in a confirmatory test. The 3a estimate may be shown next to the forward estimate, clearly labelled.
   - The combined programme (survive 3a, then pass forward) has P(false PASS | IR 0) ≈ 0.5 × 0.10 = 0.05, and power at IR 1.0 of about 0.99 × 0.83 ≈ 0.82, assuming the same IR in both periods.

**Is 2016 an alternative untouched window?** No.
- One year gives SE(IR) ≈ 1.0, which is useless as a screen.
- The 400-bar VCP lookback and the fundamentals screens are incomplete before 2017, because the price cache starts in 2014-06.

---

## 2. Power: formulas and tables

**Formulas.**
- The test series is daily, x_t. Its annualised information ratio is IR = μ_ann/σ_ann; for excess over a benchmark this equals the "excess Sharpe".
- After T years, Z = IR·√(T/VIF) + N(0,1). This is Lo (2002) with daily data: SE(ŜR) = √((1 + SR_d²/2)/n) ≈ 1/√T, because SR_d = SR/√252 ≈ 0.
- Years for power 1−β at one-sided α: **T = VIF·((z₁₋α + z₁₋β)/IR)²**.
- Minimum detectable IR: **MDE_IR(T) = (z₁₋α + z₁₋β)·√(VIF/T)**. In return units, MDE_%/yr = MDE_IR × TE.
- Power: **Φ(IR·√(T/VIF) − z₁₋α)**.
- VIF is the Newey-West (Bartlett, 20 lags) long-run variance divided by the variance.
- Clustered signals: **deff = (SE_cluster/SE_iid)²** and **N_eff = N/deff**.
- The sequential designs were simulated as Brownian motion in information time (400k paths, seed 7).
- Expected raw excess with zero skill: **E[r_arm − r_b] ≈ α − (1−β)·E[r_b]**.
- Swept excess: **x_t = r_arm,t − e_{t−1}·r_b,t**, with e_{t−1} = 1 − cash/equity at the previous close. Its expected value with zero skill is about −costs.

### T1. Noise measured in the development window (1,188 runs; medians unless stated)

| Quantity | All runs (P10–P90) | V1 max-4 | Pick (V1 RS90 1.2 10% ×4) |
|---|---|---|---|
| Exposure (invested share) | 0.38 (0.14–0.66) | 0.45 | 0.50 |
| β to the blend | 0.27 (0.09–0.50) | 0.32 | 0.36 |
| **TE of raw excess vs the blend (draft metric)** | **18.2% (16.9–19.7%)** | 18.6% | 20.4% |
| Mean raw excess vs the blend | **−1.7%/yr** | +3.2% | +16.5% |
| β-adjusted alpha (in-sample) | +4.1%/yr | +9.0% | +21.6% |
| **TE of swept excess vs the blend** | **8.4% (4.4–14.4%)** | 11.6% | 14.8% |
| TE of swept excess vs the EW universe (V1 runs) | 8.7% | 11.6% | 15.1% |
| Trades a year | **26 (17–43)** | 21 | 18 |
| VIF, raw / swept | 0.78 / 0.94 | 0.79 / 1.0 | 0.76 / 0.90 |

- The blend's own volatility over the period was 20.3%. The draft's metric mostly measures the market, and its zero-skill mean is negative.
- The draft's assumed 40–90 trades a year is not what the inherited max-4 settings produce.

### T2. The draft's power claims, recomputed (all correct as arithmetic)

| Claim | Draft | Recomputed |
|---|---|---|
| Years to 80% power, IR 1.0, α .10 / .05 | 4.5 / 6.2 | 4.51 / 6.18 |
| MDE IR at 1 / 2 / 3 / 5 years | 2.1 / 1.5 / 1.2 / 0.95 | 2.12 / 1.50 / 1.23 / 0.95 |
| Power at IR 1.0 after 1 / 2 / 3 / 5 years | 39 / 55 / 67 / 83% | 39 / 55 / 67 / 83% |
| Haybittle–Peto 80%-power IR at 24 / 36 months | 2.4 / 2.0 | 2.42 / 1.97 |
| Futility stops a true IR 1.0 | 8% | 7.9% |
| Strictest Holm step (4 secondaries), years at IR 1 | 0.025, 7.9 | 7.85 (8.4 with B4) |
| Trades needed | 180–410 | 80–135 at the realistic 18–30 trades a year |
| 1.3× variance inflation | about 6 years | Measured VIF is 0.8–1.1; 1.3 is conservative |

**The error is the effect size, not the arithmetic.** Against the blend, IR 1.0 means +18.5% a year of excess return.

### T3. Years to 80% power by IR (VIF 1.0 / 1.3)

| IR | α = .10 | α = .05 |
|---|---|---|
| 0.25 | 72 / 94 | 99 / 129 |
| 0.50 | 18 / 23 | 25 / 32 |
| 0.75 | 8.0 / 10.4 | 11.0 / 14.3 |
| 1.00 | 4.5 / 5.9 | 6.2 / 8.0 |
| 1.50 | 2.0 / 2.6 | 2.7 / 3.6 |

### T4. Power at α = .10, VIF 1

| IR | 1 yr | 2 yr | 3 yr | 5 yr | 10 yr |
|---|---|---|---|---|---|
| 0.25 | 15% | 18% | 20% | 23% | 31% |
| 0.50 | 22% | 28% | 34% | 44% | 62% |
| 0.75 | 30% | 41% | 51% | 65% | 86% |
| 1.00 | 39% | 55% | 67% | 83% | 97% |

### T5. The key table: minimum detectable annual excess (80% power, α .10, VIF 1), by metric

| Metric | TE | 1 yr | 2 yr | 3 yr | 5 yr |
|---|---|---|---|---|---|
| Raw excess vs the blend (draft)* | 18.5% | 39% | 28% | 23% | 18% |
| **Swept, max-4 book** | 11.6% | 25% | 17% | 14% | **11%** |
| Swept, max-8 book (not recommended: it changes an inherited setting) | 8.2% | 17% | 12% | 10% | 7.8% |
| Signals, calendar-time 60-day, vs EW universe | 25% | 53% | 38% | 31% | 24% |
| Signals, 60-day, vs RS≥95-matched EW (B1) | 13.9% | 30% | 21% | 17% | 13% |
| Signals, 60-day, vs RS≥95-matched EW (B3) | 9.9% | 21% | 15% | 12% | 9.4% |

\*The raw metric also starts about 5–6%/yr in the hole: −(1−β)·E[r_b] with β ≈ 0.3 and E[r_b] ≈ 8%. With 80% power at 5 years, **the true stock-selection alpha would have to be roughly 18% + 6% ≈ 24% a year in raw-excess units**.

**Comparing like with like.** Take the signal alpha a, the excess of a fully invested portfolio of the arm's signals.
- The swept book earns about e·a with e ≈ 0.45, so its 5-year MDE is 11.0%/0.45 ≈ **24% a year of a**.
- Signals against the EW universe also give **24%**.
- Signal-level measurement against the universe therefore adds **no power per unit of true alpha**. The gain comes only from matched benchmarks and contrasts.

### T6. Years to 80% power by true annual alpha (α .10, VIF 1)

| True alpha in that metric's units | 2% | 4% | 6% | 10% | 15% |
|---|---|---|---|---|---|
| Raw vs the blend (TE 18.5%), before the exposure drag | 386 | 96 | 43 | 15 | 6.9 |
| Swept, max-4 (TE 11.6%) | 152 | 38 | 17 | 6.1 | 2.7 |
| Signals vs RS-matched benchmark (TE about 12%) | 162 | 41 | 18 | 6.5 | 2.9 |

### T7. Sequential design, simulated

| True IR | Draft: P(PASS) | Draft: P(binding futility stop) | Recommended (futility non-binding): P(PASS) |
|---|---|---|---|
| 0 | 0.092 | 0.50 | 0.101 |
| 0.25 | 0.219 | 0.36 | 0.237 |
| 0.5 | 0.408 | 0.24 | 0.436 |
| 0.75 | 0.622 | 0.14 | 0.656 |
| 1.0 | 0.799 | 0.079 | 0.830 |

- The recommended design keeps Haybittle–Peto p < 0.005 at 24 and 36 months and α .10 at 60 months.
- Its type-I error is 0.101–0.102 (two simulation runs). To hold exactly 0.10, use a final one-sided α of 0.098.

### T8. Futility rule "observed IR ≤ c": P(stop)

| Look | c | IR 0 | IR 0.25 | IR 0.5 | IR 1.0 |
|---|---|---|---|---|---|
| 12 months | 0 | 50% | 40% | 31% | 16% |
| 24 months | 0 | 50% | 36% | 24% | 8% |
| 24 months | −0.25 | 36% | 24% | 14% | 4% |

### T9. 3a kill screen (5 years, kill if observed IR ≤ c)

| c | VIF | IR 0 | 0.25 | 0.5 | 0.75 | 1.0 |
|---|---|---|---|---|---|---|
| **0** | 1.0 | 50% | 29% | **13%** | 5% | 1% |
| 0 | 1.3 | 50% | 31% | 16% | 7% | 3% |
| 0.2 | 1.0 | 67% | 46% | 25% | 11% | 4% |

### T10. Signal counts and effective sample size (dev, liquid days, de-duplicated with a 20-day gap per ticker)

| Signal set | Candidate-days/yr | Signals/yr | Month-cluster deff (60d) | N_eff/yr (month) | N_eff/yr implied by calendar-time TE | 60d per-signal SD | Calendar-time 60d TE vs EW |
|---|---|---|---|---|---|---|---|
| A-like (TT, RS90, fundamentals PASS, VCP) | 116 | 33 | 1.36 | 24 | — | 22.5% | 25.5% |
| **B1** | 200 | **82** | 2.36 | 35 | **≈16** | 23.9% | 25.4% |
| B2 | 382 | 154 | 2.90 | 53 | — | 24.3% | 22.6% |
| B3 | 443 | 174 | 2.87 | 61 | ≈22 | 25.0% | 22.4% |

- The RS≥95 names as a group (about 46 names) have **21.7% TE** against the EW universe. The common momentum and sector factor, not idiosyncratic noise, dominates.
- **In-sample calendar-time evidence.** These are upper bounds: in-sample, among about 40 cuts, and with survivorship.
  - B1's signals vs EW: 60-day **+10.0%/yr (IR 0.40, t ≈ 0.86)**; 20-day **−22.8%/yr**.
  - B1 vs the RS≥95-matched basket: 60-day +2.3%/yr, 20-day −29.7%/yr. The breakout timing adds nothing visible over simply holding RS≥95 names.
  - B3 vs EW: 60-day +12.4%/yr (IR 0.55, t ≈ 1.2).
  - B3's added early-Stage-2 signals: 60-day per-signal mean **+9.2%** (n = 108), against B1's +2.3% (n = 372).
  - B2's added single-Q2/Q4-failure signals: +1.4% (n = 348), which is consistent with H3's "no worse" claim.
- The model book's support came from **tail rates and medians**. On the **mean**, which is what decides money, it is weak.

### T11. Arm C as a within-day signal contrast

The contrast is STRONG_POSITIVE against the other rated candidates, over 60 days. Assumptions: 20% rated STRONG_POSITIVE; per-signal SD 15–24%; deff 1.5–2.5.

| Candidates rated a year | MDE after 1 yr | 2 yr | 3 yr |
|---|---|---|---|
| 200 (the B1 set only) | 6.9–8.9% | 4.9–6.3% | 4.0–5.1% |
| 400 (broad set, recommended) | 4.9–10.1% | 3.4–7.1% | 2.8–5.8% |

The portfolio arm C differs from B1 only on days with more candidates than free slots, so its contrast is mostly path noise. The within-day contrast is the only feasible confirmatory test of the LLM.

---

## 3. Recommended arms and verdict rules

### 3.1 Arms and endpoints

| Role | Item | Test statistic | Rule |
|---|---|---|---|
| **Primary** | Portfolio arm **P**: B1 by default, or the 3a fallback B2, then B3 | Mean daily **swept excess over the frozen-universe EW basket** (total return, monthly rebalance, delisting-inclusive). Stationary block bootstrap, one-sided, block 20, 10,000 resamples, seed 7. | Haybittle–Peto: p < 0.005 at 24 and 36 months; α = 0.10 (or 0.098) at 60 months |
| Secondary S1 | **P's signals**, calendar-time | Each de-duplicated qualification (first qualifying close per ticker after ≥ 20 trading days without one), entered at the next open and held 60 trading days. Daily equal-weight excess over the frozen-universe EW basket. Same bootstrap. | Holm over {S1, S2} at a family α of 0.10 (steps 0.05 and 0.10), final look only |
| Secondary S2 | **Arm C rating**, within-day | Rate **every candidate in the broad set** (regime + TT-or-early + RS ≥ 70 + 50-day-high close on ≥ 1.2× volume; fundamentals not required). Daily return of the equal-weight STRONG_POSITIVE holdings minus the equal-weight other rated holdings, each held 60 days. Same bootstrap. | As S1 |
| Descriptive, pre-registered, with CIs and no claims | B2 and B3 portfolio arms; portfolio arm C against B1; B4 if signed off; raw excess against the blend (the draft's metric); B1 signals against the RS≥95-matched basket (H1 given H2); B2-added against B1 (H3); B3-added against B1 (H5); doubling and +50% rates; 20-day horizons | — | — |
| Descriptive control | **100 random-entry placebo clones of P**: same engine, gate, exits, stops, slots, sizing and costs; entries drawn deterministically (seed = hash of date and clone id) from liquid universe members | P's swept excess reported as a percentile of the placebos | — |
| Dropped | **Arm A** | It failed on both windows (the experiment-2 report agrees) | The B arms still inherit A's non-entry settings **by the hash of `selection2.json`** |

### 3.2 Verdicts for P

| Verdict | Condition |
|---|---|
| **PASS** | p below the look's boundary, **and** the swept arm's CAGR is above the blend's and the EW basket's, **and** at least 60 closed trades, **and** the auditor matches, **and** the arm was not killed |
| **FAIL (no edge)** | The swept excess (arithmetic mean) has a point estimate ≤ 0 at 60 months |
| **FUTILE (non-binding)** | The observed swept IR is ≤ 0 at 24 months. This is reported; the arm keeps running unless the owner stops it, and if stopped it gets FAIL (no edge). |
| **FAIL (risk)** | The arm's own (unswept) equity is more than 25% below its peak. The signal-level log continues. |
| **INVALID** | An auditor mismatch that was not resolved, or more than 10 INVALID trading days, or an unexplained break in the hash chain |
| **INCONCLUSIVE** | Anything else |

S1 and S2 each get PASS (Holm-adjusted p < its step), FAIL (point estimate ≤ 0) or INCONCLUSIVE.

### 3.3 Flags (investigate, and fix forward only)

- **Signal count:** fewer than 12 de-duplicated P signals in a half-year. The dev range is 34–56, and 81–141 candidate-days.
- **Entries:** 0 entries in a half-year while the regime gate was open on at least 50% of days.
- **Missed days:** more than 5% of days LATE or MISSED in any quarter.

---

## 4. Early stopping and kill rules: assessment

- **Haybittle–Peto efficacy** at p < 0.005 costs almost nothing (T7), but it only fires for an IR of about 2 or more. Keep it.
- **Binding futility** buys nothing in a paper test.
  - Continuing costs about nothing.
  - The draft does not use the looser final boundary that a binding rule would allow.
  - It stops 24% of true-IR-0.5 arms.
  - Make it non-binding. It then does not inflate the type-I error, and the final test is unchanged.
- **Consistency.** The draft's §3 table says "excess Sharpe ≤ 0", while its verdict table says "excess CAGR ≤ 0".
  - With arm vol about 10–17% and blend vol about 20–23%, geometric and arithmetic excess differ by roughly ½(σ_b² − σ_a²) ≈ 1.5–2.5% a year, in the arm's favour on CAGR.
  - Use the arithmetic mean of the tested series everywhere.
- **The 100-trade minimum** makes both early looks unreachable, since 18–30 trades a year means 100 trades takes 3.5–5.5 years. Use 60, as in experiment 2.
- **The 25% drawdown kill** is a risk rule, not evidence.
  - In 2017–2021, A reached −24.2%, and a 2020-type crash would breach 25% for most arms at once.
  - Keep it if that is the owner's tolerance, but label it FAIL (risk) and keep logging the signal-level endpoints, which do not depend on the portfolio surviving.

---

## 5. Signal-level forward design (question 4)

- **Record every qualification** for every arm's rule, for the RS≥95-matched control and for the broad set used for C. Log it at the close, before any fill, with:
  - ticker;
  - rule flags: TT criteria, RS, volume ratio, 50-day high, fundamentals class, VCP state;
  - ATR;
  - rank;
  - whether the book bought it.
- **Outcomes:** the next open to the close 20 and 60 trading days later. Use total returns, and on delisting use the delisting or cash-out price. Subtract the frozen-universe EW total return over the same interval.
- **Inference is calendar-time only**, by the Jegadeesh–Titman portfolio. Pooled per-signal t-tests overstate N by the design effect of 2.4–2.9 or more (T10).
- **What it buys:**
  - the entry rule is judged free of slot, exit and sizing noise;
  - contrasts can use matched controls (T5: TE falls from 25% to 10–14%);
  - C's test becomes feasible (T11);
  - health monitoring is fast (candidates a month from day 1).
- **What it does not buy:** more power per unit of alpha on "does it beat the universe" (T5).

---

## 6. What the forward harness must guarantee (question 5)

1. **Pre-commitment, witnessed.** The pre-registration, code, config, universe file, prompt, model id and environment lock (hash of `pip freeze` or a lockfile, and the Python version) are committed, **pushed** and tagged before Day 1's signal time.
   - Git author and commit dates are set by the client and can be forged. The witnesses are:
     - the remote's push record;
     - an external timestamp (RFC 3161 TSA or OpenTimestamps) of each day's log hash, stored in the next day's log.
2. **Signal before outcome.** Day t's file (inputs hash, candidates, ratings and orders for t+1) must be **pushed before 09:30 ET on t+1**.
   - A file pushed later is **LATE**.
   - If the day-t raw snapshot's hash was not witnessed before the t+1 open, the day is **MISSED**: no new entries from that day, while stops and exits are still applied mechanically from actual prices.
   - This removes any outcome-dependent choice about which days get processed.
3. **Raw snapshots.** Store the API responses exactly as fetched:
   - **unadjusted** OHLCV;
   - splits and dividends as reported;
   - the fetch time in UTC from an NTP-synced clock;
   - SEC filings with their EDGAR **acceptance** timestamps, which drive the 16:00 ET usability rule;
   - for C, the full document set with publication timestamps and hashes.

   Replays use these snapshots, never a later download. Later Yahoo adjustments rewrite history.
4. **Hash chain.** Each daily file contains the SHA-256 of the previous file, the snapshot hash, the code commit, the config hash, the environment hash, the prompt hash and the model id.
   - The log branch is protected: no force-push, append only.
   - A correction is a new entry that points to the old one.
5. **Code freeze.**
   - Before each run, the job checks that `git rev-parse HEAD` equals the frozen commit, that `git status --porcelain` is empty, and that the environment hash matches. Otherwise it refuses to run and logs the refusal.
   - Fixes are amendments that apply forward only, and they start a labelled segment.
   - The confirmatory tests use the **whole series** (intention to treat).
6. **Equivalence rehearsal.** Before Day 1, run the harness day by day over a recent dev slice (for example 2026-06..2026-09) from snapshot-format inputs. It must reproduce the backtest engine's ledger for the same dates **exactly**, for every arm.
7. **Audit.**
   - Weekly: `independent_auditor` replays each arm from the log.
   - At each look: a full deterministic replay from the raw snapshots by an independent session.
8. **Benchmarks from the same snapshots.** MDY and IJR total return, and the frozen-universe EW basket with delisting handling, computed by frozen code.
9. **Arm C.**
   - Pin a dated model snapshot id, temperature 0, no tools or browsing.
   - Log the provider's returned model string on every call.
   - A failed call means NEUTRAL, logged.
   - If the model is retired, a new segment starts. S2 pools the segments, stratified by segment, as pre-registered.
10. **Results-blind operation.**
    - Between looks, dashboards show health only: signal counts, fills, LATE/MISSED days, auditor status. They show no P&L.
    - Every amendment states whether its author had seen any arm's performance.
11. **Virtual money only**, as the draft requires: no broker SDK, credentials or order routing anywhere in the repository or environment.

---

## 7. Changes to make to the draft

1. **§ "Why forward" and the 2017–2021 sentence:** add Amendment 3a (§1 here): a one-shot pseudo-out-of-sample kill screen, with its rationale, the provenance (7857cac before d59d521), and the mapping rule.
2. **§1 Arms:** drop A as an arm. State that the B arms inherit `selection2.json` (sha256 0f256910…) exactly, with RS 90 → 95 as the only non-entry-trigger change.
3. **§1:** write the neutral defaults for every unspecified detail (the H2 tie-breaks, H3's lexicographic penalty, B3's exact path) before 3a.
4. **§1 Arm C:** the confirmatory test becomes the within-day rating contrast (S2) over a **broad** candidate set, rated regardless of free slots. Portfolio arm C becomes descriptive.
5. **§1 P-1/B4:** if signed off, it is descriptive, not in the Holm family.
6. **§1:** add 100 random-entry placebo clones of P (descriptive).
7. **§2 Mechanics:** add the harness guarantees in §6 here: external timestamps, pushed before the next open, MISSED means no entries, unadjusted raw snapshots, environment lock, equivalence rehearsal, protected append-only branch, health-only dashboards.
8. **§2:** the EW frozen-universe basket must include delisted names until delisting, with their cash-out or last price, from the same snapshots.
9. **§3 Primary metric:** raw excess over the blend becomes **swept excess over the frozen-universe EW basket**. PASS also requires the swept CAGR to be above the blend's and the EW basket's. Raw excess over the blend becomes descriptive.
10. **§3 Power:**
    - replace "40–90 trades/yr" with the measured 18–30 for max-4 settings;
    - re-anchor the table on T5 and T6, and state that IR 1.0 in the draft's units means +18.5% a year;
    - add the in-sample calendar-time evidence (T10), so that expectations are set.
11. **§3 Decision schedule:**
    - make futility non-binding;
    - use one statistic (the arithmetic mean swept excess);
    - lower the minimum to 60 closed trades;
    - optionally use a final one-sided α of 0.098 to hold the overall rate at 0.10.
12. **§3 Verdicts:** split FAIL into FAIL (no edge) and FAIL (risk); add FUTILE (non-binding).
13. **§4 Multiple testing:**
    - one primary (P) plus S1 and S2 under Holm over 2 (0.05 / 0.10);
    - B2, B3, portfolio C, B4 and every contrast are descriptive;
    - the primary may change only through the pre-committed 3a fallback (B1 → B2 → B3), never on forward data.
14. **§5 Kills:**
    - the drawdown kill becomes FAIL (risk), and the signal log continues;
    - replace "fewer than 10 trades in 6 months" with the signal-count and entry flags in §3.3 here;
    - add the LATE/MISSED rate flag.
15. **§5:** state that arms killed in 3a may run forward as descriptive only, labelled "killed in 3a".
