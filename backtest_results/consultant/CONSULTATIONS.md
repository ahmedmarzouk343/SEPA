# Consultation log

Each entry records the question, a short answer (conclusion first), the sources (tags refer to KNOWLEDGE_BASE.md) and the confidence. This is methodology advice for a virtual-money research project, not investment advice.

---

## C1: 2026-09-27. Mechanical VCP detector vs Minervini, the AI chart judge, and backtest trust

**Asked by:** the lead.

**Context read:**
- backtest_results/experiment3/minervini_check/RESULT.md, FIX_TESTS_RESULT.md and SOURCES.md;
- vcp_detection.py and entry_timing.py.

**Problem statement:** 50 of his 52 disclosed buys pass our trend/RS filters, but the detector rejects most of his entry charts ("contraction count out of range", "monotonicity failed", "no daily base in weekly window", "awaiting breakout").

### Q1. Where does our mechanical VCP detector most likely depart from how Minervini judges a base?

**Conclusion.** The detector's verdicts are driven mainly by the *scale* of its swing detector and by hard ratio vetoes. His verdicts are driven by right-side tightness, volume dry-up and where the pivot sits. The top five departures, most damaging first:

**1. Swing detection sets the contraction count, and it is blind to the final tight area.**
- *What the code does:*
  - `detect_swings()` finds peaks and troughs on a **5-bar rolling-median-smoothed close**.
  - The prominence threshold is **1.0 × the last bar's ATR(14)**, with a minimum distance of 3 bars (vcp_detection.py L92-96, L185-196).
  - A final contraction of 3-8% that lasts a week or two, typical of his footprints (e.g. "31/3" in "40W 31/3 4T"), often moves the *smoothed close* by less than one ATR. That applies especially to volatile growth stocks, whose ATR is already 3-5% of price.
  - The last and most important "T" is then never detected.
- *Knock-on effects:*
  - The count falls below 2, giving "contraction count out of range" (STAA, SKY, MRNA, NUE, SCHW).
  - Or a noisy left side adds extra swings.
  - The "last contraction", and so the pivot, is assigned to an older, wider swing.
- *A smaller issue:* depths use the raw High and Low at the smoothed-series indices, so they can be off by a bar or two. That distorts the ratio tests in point 2.
- *How he works:* he counts "T"s by eye at whatever scale the base shows, and describes a typical base as 2-6 contractions ending in a small final one [S12][S14].

**2. Monotonicity is a hard per-step veto; for him it is a loose rule of thumb.**
- *What the code does:* it requires final ≤ 0.75 × first **and** every step ≤ 1.5 × the prior (L117-118, L505-512).
- *How he works:*
  - His guidance is that each contraction is about half the prior one, "plus or minus a reasonable amount" [S12][S14].
  - He reads the progression across the whole base, and treats a shakeout or undercut as constructive, not disqualifying [S14].
  - A single middle leg that overshoots (a shakeout, or an earnings-day wick) fails our rule B. That is the likely cause of the "monotonicity failed" rejections (GM, AXON, DVA).
- *Housekeeping:* the module docstring still says the tolerance is 130%, while the constant is 1.50. This is documentation drift worth fixing, so that the receipts can be trusted.

**3. Base segmentation resets on any marginal new high, and only the most recent base is examined.**
- *What the code does:*
  - `identify_bases()` starts a new base whenever a peak's raw High exceeds the base's first peak by any amount (L266-274).
  - Only `w_bases[-1]` and `d_bases[-1]` are then validated (entry_timing.py L139, L216).
  - A pivot probe or "pivot leakage" [S16], a squat [S14], or a right side slightly above the left high (reported in real VCPs [S23]) splits one base into a fragment with 1 contraction. The fragment then fails the count check.
- *The weekly gate (L129-147):* it requires a validated weekly base, found by the same ATR-prominence method with 2-bar smoothing. Short 3-6-week VCPs, which fall inside his 3-65-week range [S21], may produce no weekly swing at all. That fits APP's "no daily base in weekly window".
- *How he works:* he reads daily and weekly together, and does not require a separate weekly structure first.

**4. The pivot and trigger are defined differently from his entries.**
- *What the code does:*
  - The pivot is the High at the last detected peak (L586-590).
  - A buy requires a daily **close** above the pivot **and** volume ≥ 1.4× the 50-day average, *including today*, on that same bar (L597-650).
  - The breakout is invalidated if a later close falls below the 20-day SMA (L657-683).
- *How he works:*
  - The pivot is the top of the final *tight* area [S12]. He also takes **cheat, low-cheat and 3C** pivots in the lower-to-middle third of the base [S18][S19][S20].
  - He buys as price trades through the pivot, not after a confirming close.
  - He expects some breakouts to slip back just below the pivot within 1-2 weeks [S14].
  - No breakout-volume multiple from him is verified; the 1.4× is our calibration [S26].
- *Effect:*
  - His earlier entries show up as "awaiting breakout" (PAG).
  - Some legitimate breakouts fail the volume test (PYPL at 1.2×).
  - Normal pullbacks are treated as failures.

**5. The detector ignores what he weighs most (volume dry-up, tightness, context) and polices what he treats loosely.**
- *Volume:* on the US daily path no volume contraction is tested at all. `require_volume_dryup` is only switched on for EGX weekly bases, and the single-contraction allowance is off by default (L539-549; entry_timing.py L59-62, L141-144, L217-220).
- *Tightness:* nothing measures narrow daily ranges or tight closes near the pivot.
- *Context:*
  - Relative strength during the base is not checked.
  - The base number or stage is always "neutral" (`base_number=None`, docstring deviation #4).
- *How he works:* he stresses volume drying up on the right side and at the pivot, tight action, pivot integrity, and early versus late-stage bases [S12][S14][S15][S16].
- *Effect:* the detector can reject his well-formed bases on geometry while accepting loose bases that have no supply check. That is a double failure, which explains why it disagrees with him in both directions.

**Why these five:**
- The receipts in FIX_TESTS_RESULT.md map directly onto #1-#4.
- #5 explains why loosening the geometry alone would probably add false positives rather than recover his edge.

**Confidence:**
- High that #1-#4 are real departures, since they are code facts compared with his published guidance.
- Medium on how much each one contributes. That has not been measured.
- *What would change my view:* re-running his in-universe entry dates with (a) prominence scaled down (e.g. 0.5× ATR, no smoothing on the right side) and (b) rule B removed. If most rejections survive both, then #1-#2 are not the main cause.

### Q2. If an AI judges anonymized charts, which criteria should it be given verbatim (in our own words), and which should be left to its judgment?

**Conclusion.**
- Keep everything that can be measured unambiguously **in code, before or after the AI**. Give the AI **a short, sourced description of what a good base looks like, framed as tendencies** rather than thresholds.
- Leave to its judgment only the things he himself judges by eye: what counts as a contraction, whether a middle leg is a shakeout, where the tight area and pivot are, and whether the volume shows supply drying up.
- Require structured output, so that code can re-check the numbers the AI reports.

**A. Keep in code, not in the prompt.** These are deterministic and already sourced; the AI should never override them:
- the trend template and RS (they already agree with him: 50 of 52 pass);
- liquidity and universe;
- the fundamentals *ranking*, not a veto [S3];
- earnings-date proximity;
- the market overlay [S2][S31];
- stop distance and position sizing [S2][S15].

**B. Give the AI verbatim, in our words.** Each item is phrased as "typically", with its source:
1. The stock is in an established uptrend. The base is a pause in that uptrend, with the first pullback measured from the base's high.
2. Pullbacks usually get smaller from left to right, typically **2-6 of them**, each roughly half the previous one with generous tolerance. The last one is small, often under ~10% and sometimes 3-5% [S12][S14].
3. Bases usually last **3-65 weeks**. Constructive bases usually correct **10-35%** (sometimes up to ~40%); a decline of about 60% or more is not a setup [S15][S21][S24].
4. Volume should shrink as the base matures, and be *lowest in the final tight area*. Heavy selling on the right side is a negative [S12][S14][S24].
5. The pivot is the top of the final tight area, not necessarily the highest point of the base. Valid early pivots ("cheat", "low cheat") can form in the lower-to-middle third of the base; a handle in the upper third is a normal pivot [S18][S19].
6. A buy is only sensible if the stop can go just below the tight area within **~8-10%** of the entry. His average loss is about 4-5% [S2].
7. Warning signs:
   - wide, loose swings;
   - a large expansion of down-volume near the pivot;
   - a very extended late-stage base;
   - a base forming below a falling 200-day average [S24][S15].

**C. Leave to the AI's judgment.** This is the part the mechanical detector gets wrong:
- whether a wiggle counts as a contraction, and at what scale to read the base;
- whether a larger middle leg is a shakeout (acceptable) or a breakdown;
- whether a slightly higher right-side high is still the same base;
- the choice between a standard pivot and a cheat or low-cheat pivot;
- whether the tight area is "tight enough";
- whether the volume pattern reads as dry-up or distribution;
- a 1-5 quality grade with a short reason.

**D. Required output fields.** These let the code re-check the AI:
- base start;
- approximate contraction depths as a list;
- pivot price and pivot type;
- proposed stop price;
- volume dry-up (yes/no/unclear);
- verdict and grade;
- confidence.

The code then checks that:
- the stop distance is ≤ 10%;
- the price is not extended beyond a set tolerance above the pivot;
- the reported depths are consistent with the actual bars.

If the checks fail, the verdict is void.

**E. Guardrails for a fair test:**
1. *Point-in-time rendering.* Show bars only up to the decision date. Remove the ticker, dates, absolute price levels (use a % axis) and any annotations that give away the calendar.
2. *Model knowledge.* LLMs can use knowledge of the training period, even through anonymized inputs; the effect is larger for famous names [S43].
   - Charts of well-known 2021-2026 winners are the most likely to be recognized.
   - Treat any historical accuracy on his disclosed trades as **calibration only, not evidence**.
3. *Freeze before testing.* Fix the prompt, model version and sampling settings before any run, under the same lock discipline as the engine. Use temperature 0 or a majority vote, and measure how stable repeated judgments are.
4. *Calibration set.*
   - Positives: his disclosed in-universe entries.
   - Negatives: *matched* stocks drawn from the ~255 same-day trend-template passers.
   - Report recall on his entries **and** the acceptance rate among the 255. If the judge accepts most of the 255, it is not selective. He typically holds a handful of positions [S14][S15].
5. *Where the evidence must come from.* Both historical windows are already consumed. Real evidence for an AI judge can therefore only come from **forward paper trading with virtual money**.

**Confidence:**
- High on the division between A, B and C and on the guardrails.
- Medium on the specific numeric tendencies in B. Several come from book summaries, not primary text (see the KB gaps).

### Q3. What would a professional check before trusting any backtest of this method?

**Conclusion.** First, is it actually a test of *his method*: the universe, entries, exits, sizing and market overlay? Second, could the result be an artifact: survivorship, lookahead, fills, costs, overfitting, or a few lucky trades? Only then look at the return versus the benchmark. The checklist, in priority order:

1. **Does it test the method or a proxy?**
   - He trades the whole US market.
   - His win rate is about 50%, and the edge comes from losses of about 4-5% against much larger gains, plus progressive exposure and holding cash for months [S1][S2][S28][S29].
   - A test of selection only, with fixed sizing and no feedback overlay, tests something else. It should be labeled that way.
2. **A point-in-time, survivorship-free universe.** It must include delisted stocks and IPOs. Current index members are biased [S40][S41]. Fundamentals must be as-filed and dated from the announcement (the project already does this for EPS).
3. **Fill realism at the pivot.**
   - A buy-stop at the pivot versus the next open after a close-confirmation. Gaps through the pivot, slippage on breakout-day volume, and small-cap spreads.
   - Screens that ignore frictions lose most of their gross edge; beating the indices needed frictions under about 0.6% [S35].
4. **Overfitting accounting.**
   - How many variants were tried (prominence, ratio tolerances, volume multiple, windows)?
   - Report the probability of backtest overfitting or a deflated Sharpe ratio [S44], and test sensitivity to each constant ±20-30%.
   - A result that holds only at the calibrated constants (e.g. 1.4× vs 1.2×) is not trustworthy.
5. **Validate the detector itself before the P&L.**
   - Measure precision and recall of the pattern detector against hand-labelled charts or his disclosed entries.
   - Our detector's recall on his entries is very low [S41]. Its P&L therefore says little about the VCP.
6. **Trade-level distribution.**
   - Look at win rate, the average win/loss ratio (he targets 2-3:1 or more [S14]), and how much of the result comes from the top 5 trades (use a bootstrap).
   - Count the trades. A few dozen trades cannot separate skill from luck.
7. **Regime split.**
   - Report results separately for bull phases, bear phases and "tricky" phases. VCP successes cluster in bull phases [S39].
   - Check that the overlay actually moves the system to cash when his own gauge would: pivot failures and a shrinking buyable list [S31][S32].
8. **The right benchmark and exposure.**
   - Compare against a size-matched, equal-weight index.
   - Report raw and cash-swept figures side by side, and state the average exposure. The project already does this with MDY/IJR.
9. **Out-of-sample discipline.**
   - Parameters must be frozen before the holdout.
   - The design must not be motivated by the test period's winners. Our fixes were motivated by his 2021-2026 picks [S41].
   - Screen outperformance also tends to decay after publication [S35].
10. **Don't borrow credibility from his record.**
    - His contest results are single-account, single-year, broker-statement-verified results. They are not a GIPS audit, and they come from a self-selected field [S4][S5][S8].
    - They say nothing about whether *our mechanical rules* have an edge.

**Confidence:** high. These are standard professional checks, and each one maps onto a known weakness in this project's history.

**Sources for C1:** S1, S2, S3, S4, S5, S8, S12, S14, S15, S16, S18, S19, S20, S21, S23, S24, S26, S28, S29, S31, S32, S35, S39, S40, S41, S43, S44, plus code references to vcp_detection.py and entry_timing.py (line numbers as of 2026-09-27).

**Overall confidence:**
- Q1: high on the existence of the departures, medium on their ranking.
- Q2: high on the structure, medium on the numeric tendencies.
- Q3: high.
