# Experiment 4 research: lessons so far, and the risks of an AI chart judge

Skeptic/historian memo, written 2026-09-27. Read-only: no backtest, no model call, no commit. Everything here comes from the files cited on each line, plus four measurements taken read-only from the F0/F2 decision receipts (`kashif_data/minervini_fix/*/F*/decision_receipts.parquet`) and the disclosed-trades CSV. Model cutoffs are taken from the peer memo `CLEAN_WINDOWS_AND_LEAKAGE.md` in this folder; this memo does not repeat its full probe design.

**The proposal under review:** replace the mechanical VCP detector with an LLM that looks at anonymised chart windows and returns "base present / pivot / buy or no-buy".

**Short answer:** the idea can be tested honestly, but only on a small slice of history after the model's training cutoff, and only at the signal level. A portfolio backtest on 2017-2021 or 2022-2026 cannot be honest for any current LLM, whatever the prompt says. The smallest honest test is in Part 3. It costs about **$3-4** on Claude Haiku 4.5 (about $7-9 with a Sonnet 5 secondary arm), and it can only **falsify** the idea or catch a large effect.

---

## Part 1. Lessons learned so far

One line per lesson; the source file follows the dash.

### (a) Statistics and overfitting

1. The experiment-2 pick made +25.7%/yr on the data it was chosen on (2022-26) and −0.6%/yr (−3.2% total) on fresh 2017-21 data, against +80% for MDY/IJR. — `experiment2/EXPERIMENT2_REPORT.md` §1, §4
2. The same pick shows +113.9% on 2024-26: that is the in-sample number, and in-sample numbers look best because they were selected. — `experiment3/TESTS_NOW_RESULTS.md`
3. The Deflated Sharpe Ratio (0.41 at N = 1,188; 0.06 on excess over the blend) warned before validation, and the warning was right. — `EXPERIMENT2_REPORT.md` §3; `PREREGISTRATION.md`, operational record
4. B1 looked best in-sample (+21.6%) and was the worst out of sample (−23.8%, KILLED). — `TESTS_NOW_RESULTS.md`
5. Nothing tuned survived a second period: the pick's edge, "defensive off", RS 90, let-winners-run exits, and F1's wider universe. — `experiment3/TEAM_SYNTHESIS.md` §1.4; `minervini_check/FIX_TESTS_RESULT.md`
6. In experiment 1's grid, the median Sharpe was −0.26 and only 20 of 108 cells were positive; the best cell rested on one ADMA position. — `FINAL_BACKTEST_REPORT.md` §3
7. Walk-forward folds each picked a different combination; out-of-sample tests of 6-11 trades are anecdotes. — `FINAL_BACKTEST_REPORT.md` §3
8. A Sharpe of 0.46 over 2.2 years has a 95% CI of −0.92 to 1.84: short windows cannot tell skill from zero. — `FINAL_BACKTEST_REPORT.md` §0
9. Confirming a Sharpe of 1.0 takes about 4.5-6 years, and a 2-4%/yr edge takes decades, so tests can falsify but rarely confirm. — `PREREGISTRATION_DRAFT.md` §3; `research/DESIGN_REVIEW.md` T3-T6
10. Choosing the best of only 3 open implementation details, with knowledge of the window, buys about 0.85 SE, the same size as the kill threshold. — `DESIGN_REVIEW.md` §1.2
11. The model book's support came from tail rates and medians. On means, which decide money, B1's signals had IR 0.40 (t ≈ 0.9) at 60 days and negative returns at 20 days. — `DESIGN_REVIEW.md` T10
12. Signals cluster (design effect 2.4-2.9), so the effective N is about 16-60 a year; per-signal t-tests overstate the evidence. — `DESIGN_REVIEW.md` T10
13. The grid variant explained 38% of Sharpe variance and the four parameters about 8%; the other 54% was interactions and path noise. — `research/LESSONS_FROM_EXP1_EXP2.md` Q1
14. Net P&L was negative without the 5 best trades in 5 of 6 samples, so results rest on a handful of names. — `LESSONS_FROM_EXP1_EXP2.md` Q2c
15. From the literature: backtest Sharpe falls a median 73% live, anomalies lose 58% after publication, and backtest Sharpe explains R² < 0.025 of live results. — `research/LITERATURE_MEMO.md` Q8

### (b) Data integrity

1. Pre-announcement 8-Ks (Item 2.02) produced release dates up to 44 days early (WING 2019). The rule is now the latest 2.02 on or before the 10-Q/10-K, and this also affected experiment 1. — `PREREGISTRATION.md`, Amendment 3 addendum
2. Borrowed 8-K dates can still expose a restated value up to 59 days early (CPAY Q2 2016; an estimated 10-230 of 68,811 rows). — `minervini_check/SP500_DATA_AUDIT.md`
3. The first 2.02 after quarter end is not always the results release: MRNA's preliminary letter, HIG's pre-announcement, and CI's mis-indexed 8-K. — `SP500_DATA_AUDIT.md`
4. SPAC shells, bankruptcies and reverse mergers were being read as "last year" (MP, HIMS, RSI, CHRD and others), which led to 30 history breaks. — `PREREGISTRATION.md` addendum
5. 172 missing splits and stock dividends were added (197 events). Yahoo misses small recurring stock dividends (CBSH, TR, SBSI). Apply a split only if the registrant whose EPS is stored made it. — `PREREGISTRATION.md`; memory `project_eps_policy.md`
6. Store as-filed EPS and split-adjust at query time; never embed later split knowledge (TTEK $1.59, not $0.32). — memory `project_eps_policy.md`
7. Q4 = FY − 9M mixes bases when the 10-K restates Q1-Q3 (AIN 2018, QRVO FY2020 2.20 vs 0.43, KNX 2017, CI 2018 ProfitLoss). Every wrong value in the audit sample was a Q4 row. — `PREREGISTRATION.md` addendum; `SP500_DATA_AUDIT.md`
8. The 10-K quarterly note dated 3,219 rows up to 9 months late; moving dates to 8-Ks made them a median 5 days earlier. — `FINAL_BACKTEST_REPORT.md` §2
9. Unit and price errors: FIZZ stored EPS in cents as dollars, CHRD had a +25,700% jump, and VTOL's 1:3 reverse split was booked as 1:2. — `EXPERIMENT2_REPORT.md` §6; `PREREGISTRATION.md` Amendment 3
10. "Rejection is conservative" was false: a rejected mid-history EPS can turn a Q2/Q4 FAIL into a SKIP, which counts as a pass. — `PREREGISTRATION.md` addendum correction
11. The validation window's quarters are 3-5× more often late, because restatements are dated at the restating filing. This was declared in advance as a handicap. — `EXPERIMENT2_REPORT.md` §6
12. Survivorship: the universe is today's members. Equal-weight members made 19.9%/yr against 12.5% for MDY/IJR in 2017-21, an upper bound of about 7 points a year. — `LITERATURE_MEMO.md` Q8; `LESSONS_FROM_EXP1_EXP2.md` caveats
13. Checkpoints are ground truth; never edit one to match the code. — memory `feedback_checkpoints_immutable.md`
14. Every field rule (bank revenue = NII + noninterest income; NI attributable to the parent; the Q4 numerator) came from a concrete mismatch with a filing. — memory `project_fundamentals_definitions.md`
15. Every LLM has read 2017-2026, so an LLM "rating" past news already knows how the story ended; no prompt removes that. — `PREREGISTRATION.md` Amendment 3.5; `LITERATURE_MEMO.md` Q7
16. Masking is not a guarantee: models reconstruct entities and dates from minimal context (Lopez-Lira, Tang & Zhu). — `LITERATURE_MEMO.md` Q7
17. Known holes: 9 dual-class tickers (HSY, V, BRK-B and others) have no EPS, and APTV and IBKR have revenue gaps. — `SP500_DATA_AUDIT.md`

### (c) What the results say about the strategy

1. Every one-shot out-of-sample test lagged simply holding the index on raw returns: experiment 1's holdout, experiment 2's validation, experiment 3a (B1-B3), and F0-F2 on 2017-21. — `TESTS_NOW_RESULTS.md`; `FIX_TESTS_RESULT.md`
2. Cash drag is the main cause. Exposure was 26-50%, and the invested sleeve roughly matched the benchmark; with idle cash in the index, arm B would have made 13.4% against 12.5%. — `LESSONS_FROM_EXP1_EXP2.md` Q4; `TEAM_SYNTHESIS.md`
3. F0 with idle cash swept into the index tracked the blend in both periods (13.1% vs 12.5%; 6.1% vs 6.0%). That is index-like, not an edge. — `FIX_TESTS_RESULT.md`
4. It is a stop-out machine: 55-63% of trades hit the initial stop in a median 6-9 bars, and all the profit comes from the 12-31% of trades held more than 40 bars. — `LESSONS_FROM_EXP1_EXP2.md` Q2c, Q3
5. The stops mostly cut real losers: only 10-17% of stopped trades later closed 20% higher within 60 days. — `LESSONS_FROM_EXP1_EXP2.md` Q3
6. Higher entry RS gave worse trades inside this machinery (Spearman −0.24 and −0.20), with RS ≥ 95 win rates of 26-29%. — `LESSONS_FROM_EXP1_EXP2.md` Q2a
7. RS is the only filter that separated doublers ex-ante, measured per ticker-day with no stops. The stop converts that tail into stop-outs. — `experiment2/MODEL_BOOK_DEV.md`; `LESSONS_FROM_EXP1_EXP2.md` R1
8. **VCP did not separate winners in-sample.** Volume days with a rejected base did as well as VCP-ready days, and a plain 50-day-high breakout gave 2.2× the entries with outcomes at least as good. — `MODEL_BOOK_DEV.md`
9. The funnel caught 2.7% of the 2022-26 doublers. The Trend Template blocked 52%, fundamentals 30% and VCP 10%. — `MODEL_BOOK_DEV.md`
10. Defensive mode was on at 80-84% of closes, and its 11% target cut off the right tail. — `FINAL_BACKTEST_REPORT.md` §6
11. The OR regime gate was open 95% of days. Beta of 0.15-0.36 means the strategy wins in down years and lags in up years. — `FINAL_BACKTEST_REPORT.md` §6; `LESSONS_FROM_EXP1_EXP2.md` R6
12. The LLM catalyst layer changed zero trades, and "strong positive" filings were followed by weaker 60-day returns. — `FINAL_BACKTEST_REPORT.md` §4
13. 3 trades made 64% of the pick's dev profit. Its extended entries made +8.1% per trade in dev and −2.0% in validation. — `EXPERIMENT2_REPORT.md` §3; `LESSONS_FROM_EXP1_EXP2.md` F2
14. Minervini's disclosed buys: 62 of 77 were outside the universe, 12 of the 15 inside failed fundamentals, and the detector rejected most of his entries ("contraction count out of range", "monotonicity failed"). — `minervini_check/RESULT.md`; `FIX_TESTS_RESULT.md`
15. Widening to the S&P 1500 and softening fundamentals produced no arm that beat the index in both periods. — `FIX_TESTS_RESULT.md`
16. There is no peer-reviewed test of SEPA or VCP. FFTY (IBD 50) returned about 3.5%/yr since 2015, and a realistic long-only momentum edge is +2-3%/yr. — `LITERATURE_MEMO.md` Q3, Q8

### (d) Process

1. Pre-register before any run. Amendments are dated, and they win where they conflict with the original. — `PREREGISTRATION.md`
2. Each lock claim is committed and pushed before the run; the code refuses a second run, or a run without a lock. — `PREREGISTRATION.md` operational record; `TESTS_NOW_PREREG.md`
3. Withhold outcomes until the run is final. `build_catalyst_table` would have printed holdout returns early, and review caught it. — `FINAL_BACKTEST_REPORT.md` §7 #25
4. Adversarial peer reviews found real bugs: 30 and then 10 findings, F1-F8, the ClockBroker stop bug, the Sortino formula, and the EW benchmark that mixed in hand-picked names. — `EXPERIMENT2_REPORT.md` §6; `FINAL_BACKTEST_REPORT.md` §7
5. The independent auditor must match the ledger exactly, or the verdict is INVALID. — `FINAL_BACKTEST_REPORT.md` §5; `PREREGISTRATION.md` Amendment 2
6. Rehearse the exact one-shot code on an in-sample slice (2024-01..06) before the real run. — `PREREGISTRATION.md` operational record
7. An app restart killed the dev grid at about 1,050 of 1,188 runs. It resumed only after the finished runs' parameters were checked and hashes were recorded. — `PREREGISTRATION.md` operational record
8. When the data changed under a running grid, 57 runs were quarantined unread. Freeze the data before building the bundle, and report late finds instead of merging them. — `PREREGISTRATION.md` Amendment 3
9. Free-tier LLM APIs stalled catalyst scoring at 56%. Subagents and peer sessions finished it, each with an exclusive output file, and the lead committed. — memory `feedback_use_agents_when_rate_limited.md`; `FINAL_BACKTEST_REPORT.md` §12
10. LLM plumbing bugs: NaN was truthy, so the model was never called; 503 errors were read as quota exhaustion; unparseable answers were cached as NEUTRAL. — `FINAL_BACKTEST_REPORT.md` §7 #20-24
11. A blind second rater agreed with κ 0.89, yet the layer still could not discriminate. Reliability is not validity. — `FINAL_BACKTEST_REPORT.md` §4
12. Label contamination honestly: "pseudo-out-of-sample"; "not falsified" is never evidence of an edge. — `DESIGN_REVIEW.md` §1.2; `TEAM_SYNTHESIS.md`
13. Web sources were blocked (x.com, benzinga, archive) and not bypassed, so the Minervini sample leans toward publicised winners. — `minervini_check/SOURCES.md`
14. The forward harness needs order files pushed before the open, external timestamps, a hash chain and health-only dashboards. — `DESIGN_REVIEW.md` §6

### (e) The owner's preferences

1. Tests on real past data now, not year-long forward waits, with in-sample and out-of-sample explained plainly and with numbers. — memory `project_us_backtest_result.md`; `TESTS_NOW_PREREG.md`
2. The owner asked for 200%+/yr. The honest answer was "not here", and leverage multiplies a negative edge. — `EXPERIMENT2_REPORT.md` §1; `PREREGISTRATION.md` Amendment 3.4
3. Honest labels: in-sample, pseudo-OOS, survivorship-biased, "not falsified ≠ edge". — `TESTS_NOW_RESULTS.md`; `DESIGN_REVIEW.md`
4. Collaboration: "you are the leader". Delegate with exact input and output files and validate the outputs in code; only the lead commits and pushes. — memory `feedback_use_agents_when_rate_limited.md`; `reference_git_push.md`
5. Pushing is authorised, but peer-owned files stay out of commits. — memory `reference_git_push.md`
6. Virtual money only. Real money is the owner's decision alone and is never executed by an agent. — `PREREGISTRATION_DRAFT.md` §2
7. The owner's own questions drive experiments; the Minervini comparison was his. — `minervini_check/RESULT.md`
8. Judgement calls are surfaced, not decided silently. — `FINAL_BACKTEST_REPORT.md` §9
9. There is an LLM budget cap of $10 notional, enforced as a hard stop (the brief's "rule 8"; `BUDGET_USD = 10.0`). — `kashif_engine/catalyst/scorer.py`; `FINAL_BACKTEST_REPORT.md` §12

---

## Part 2. Critique of "an LLM judges anonymised charts instead of the VCP detector"

### 2.0 The prior is low, and the question is easy to mis-state

- **"Agrees with Minervini" is not "adds value".** His disclosed buys are publicised winners from a self-selected sample (`SOURCES.md`), and his competition record is not a systematic rule set. An LLM that accepts his entries may simply accept everything.
- **The project's own in-sample evidence says the pattern gate adds little.** VCP did not separate winners (`MODEL_BOOK_DEV.md`), and B1, which dropped VCP entirely for a plain breakout, was killed out of sample.
- **What an LLM would really do is loosen the base check.** It would accept more "almost-VCP" days. The measured effect of loosening the gate is more entries in a strategy whose invested sleeve already earns about the index.

### 2.1 Leakage: can an LLM recognise the stock or the date from an anonymised chart?

**Yes, in several ways.** Hiding the ticker and the axis dates is necessary but not sufficient.

| Channel | Example | Mitigation | Removes it? |
|---|---|---|---|
| Price and volume levels | A $900 stock with a 10:1 split history is NVDA | Rebase to 100; show volume as a multiple of its 50-day average | Mostly |
| File names, metadata, axis labels | `AAPL_2021-06-17.png`, PNG tEXt chunks, tick labels | Random IDs; strip metadata; no axis dates | Yes |
| **Market-wide shapes date the chart** | Mar-2020 crash and V-rebound, Q4-2018 drop, 2022 bear, Jan-2021 meme spikes, Apr-2025 tariff drop | None. Any 12-month window that contains one is dated to within weeks, and the model knows what the market did next | **No** |
| Famous single-stock paths | TSLA 2020, MRNA 2020-21, NVDA 2023-24, SMCI 2024, GME 2021 | None. The shape is the identity | **No** |
| Company priors ("distraction", Glasserman & Lin) | Recognising the stock brings its whole history | Anonymise; measure recognition | Partly |
| **Tool leakage** | A Claude Code subagent has Read, Grep, Bash and WebSearch; it can open `kashif_data/prices/` or search the ticker | The judge must be a **tool-less API call** that sees only the image and the prompt | Yes, if enforced |
| Few-shot leakage | Minervini's buys used as examples (§2.4) | Do not use them | Yes |
| **Researcher leakage** | The team knows the 2022-26 winners (LQDA, ADMA, BTSG; the model-book doublers) and can steer the prompt toward them | Freeze the prompt from book text before computing any outcome; code draws the sample from a seed; outcome code is committed before judgements exist | Partly |

**Probing leakage.** `CLEAN_WINDOWS_AND_LEAKAGE.md` §3 has a full five-panel design. Its essentials:

- **Guess the date:** "In which month does this window end?" Score the error in months against a volatility-only baseline, with panels that contain famous market-wide episodes.
- **Guess the ticker:** 5-way multiple choice (the true stock plus 4 same-sector, same-period, same-RS-band decoys). Chance is 20%. Add a free-text guess.
- **Guess the outcome (the decisive panel):** "Higher or lower than the market 20 trading days later?" Ask it on 200 pre-cutoff and 200 post-cutoff windows. The **memorisation gap** is pre-cutoff skill minus post-cutoff skill. If the gap is positive, the model uses outcome knowledge. Month-by-month skill around the stated cutoff shows the *effective* cutoff.
- **Limits of the probe:**
  - Failing proves leakage; passing does **not** prove its absence, because a model can use knowledge it cannot name.
  - Therefore pre-cutoff results are **never** used for performance claims, whatever the probe shows. The probe's jobs are to locate the effective cutoff and to show the owner, with numbers, why history before it is unusable.

### 2.2 Which historical window is clean?

Only decision dates after the model's **training-data** cutoff plus a buffer, and with the outcome horizon still inside our data (which ends 2026-09-24). From `CLEAN_WINDOWS_AND_LEAKAGE.md` §1-2:

| Model (vision) | Training data to | Clean decision dates | Scoreable at a 60-day horizon | Scoreable at a 20-day horizon |
|---|---|---|---|---|
| Claude Opus 5.5 (the model running these sessions) | Jun 2026 | from 2026-08-01 | **none** | about 18 days |
| Claude Sonnet 5 | Jan 2026 | from 2026-03-01 | about 4 months | about 5.5 months |
| **Claude Haiku 4.5** | **Jul 2025** | **from 2025-09-01** | **about 10 months** | about 11.5 months |
| Gemini 2.5 / 3.1 (cutoff undocumented; Jan 2025 is only *reported*) | ? | only after the probe fixes the effective cutoff | ? | ? |
| gpt-oss, Llama 3.x (**text-only**, no image input) | Jun 2024 / Dec 2023 | 2024-08 / 2024-02 | about 23 / 29 months | — |

- **2017-2021 and 2022 to mid-2025 are contaminated for every vision model**, and no prompt or probe can clean them. These are exactly the windows the project has already used many times:
  - 2017-21: experiment 2's validation, 3a, F0-F2, and the analyst's memo.
  - 2022-26: experiment 1's tuning and holdout, the 1,188-run grid, the ~40 model-book cuts, experiment 3's Test 1, and F0-F2.
- **The one usable slice**, Haiku 4.5's Sep-2025..Jun-2026, is clean *for the model* but not *for the team*. It sits inside windows the team has already studied. Label it **pseudo-out-of-sample** and freeze everything before any outcome is computed.
- **It is also a single market regime** of about 10 months. One regime cannot say whether the judge would survive a 2018-type or 2022-type market.
- **Haiku 4.5 retires "not sooner than 2026-10-15"** (peer memo). A historical result on Haiku cannot be carried into a forward test on Haiku. The forward judge would be a different model, so that is a new segment and a new test.
- **Text-only models** (longer clean windows) would have to read ~250 bars of numeric OHLCV text. That is a different task from "reading a chart", and 5-8k tokens a call, which is more expensive than an image.

### 2.3 Overfitting through prompt tuning

**Degrees of freedom:**

| Choice | Options |
|---|---|
| Rendering | candles, line or OHLC bars |
| Bar size | daily or weekly |
| Lookback | 6, 12 or 24 months |
| Volume | shown or hidden |
| MA overlays | on or off |
| Prompt wording | ~5 versions |
| Few-shot set | none, book examples, or disclosed buys |
| Model | ~3 |
| "Buy" confidence threshold | ~3 |

That is 3 × 2 × 3 × 2 × 2 × 5 × 3 × 3 × 3 = **9,720 configurations**. That is 8× experiment 2's grid, and prompt edits are free-text, so they are even easier to iterate without counting them.

**The best of k noise-only variants looks like an edge by selection alone.** Its expected score is about 1.5 SE at k = 10, 2.3 SE at k = 60, 2.7 SE at k = 200, and 3.2 SE at k = 1,000. An informal "tweak the prompt after looking at the misses" loop of 10 edits × 3 renderings × 2 models is k = 60, which gives a ~2.3-SE "edge" from nothing. That is the experiment-2 story (DSR 0.41 at N = 1,188) in a new costume.

**Rules:**
- Develop the prompt only on synthetic charts, and on real charts **without outcomes** (format compliance and yes-rate).
- Log every prompt, rendering and model as a hash.
- Freeze a single primary configuration before any outcome is computed.
- Pre-declare at most one secondary, with Holm over both.
- Report the DSR with N = every configuration ever scored against outcomes.
- A second prompt tried after seeing results needs a window that has not been scored. Historically there is none, so it goes forward only.

### 2.4 Minervini's disclosed buys as few-shot examples: circular and leaky

- **Measured from `minervini_disclosed_trades.csv`:** 30 BUY rows with exact dates. 18 are in our S&P 1500 price data: 14 in 2021 (the USIC list) and 4 in 2024 (MU, APP, AXON, DVA). **None falls after any vision model's cutoff plus buffer** (peer memo §2).
- **Circular.** Every one sits inside a test window. Showing them as examples and then testing agreement with his entries on the same period tests memory of the examples, not chart reading.
- **Leaky.**
  - The USIC 2021 list, and chart images of it, were published widely (monty-trader, Business Wire, threadreaderapp, TraderLion). A model may recognise those exact shapes.
  - The 2024 rows come from X posts that the model has likely read.
- **Tiny.** With 18 positives, a hit rate has a 95% CI of roughly ±23 points. It cannot separate "better than the detector (1 of 15)" from noise, except at the extremes.
- **Biased.** They are publicised winners, and the "HOLD" rows are not entry dates.
- **Acceptable alternatives:**
  - Zero-shot, from the written VCP rules (`feature-05-entry-timing-rules.md`, `vcp_calibration_spec.md`).
  - Or few-shot from pre-2017 book examples. These teach the pattern, are never test items, and fall outside every window. They are memorised too, which is harmless for teaching.
- Minervini's entries can serve only as a **labelled-contaminated, descriptive** face-validity check (Part 3, step 3).

### 2.5 Cost and rate limits

- **Budget:** a $10 notional cap with a hard stop (`scorer.py`); experiment 1 spent $0.027 notional on 230 free-tier calls.
- **Keys:** the project `.env` holds Google, Groq and Cerebras keys, not an Anthropic key (peer memo).
- **Free tiers:** they stalled at 56% coverage on about 400 text items. Thousands of image calls on a free tier would take days and **fail partially**. Partial coverage is a selection bias, because the days that got judged differ from the ones that didn't.

**Per-call assumption:**
- one ~1000×700 chart ≈ 930 image tokens (w×h/750);
- a ~800-token frozen prompt;
- ~150 output tokens of JSON, with thinking off.

**Prices** (Anthropic list, $/M input / output, from the claude-api reference cached 2026-06-24; the Batch API is 50% off):

| Model | $ / M in / out | Per call, real-time | Per call, batch |
|---|---|---|---|
| Haiku 4.5 | 1 / 5 | $0.0026 | **$0.0013** |
| Sonnet 5 | 2 / 10 | $0.0051 | **$0.0026** |
| Opus 5.5 | 4 / 20. Thinking cannot be disabled, so add ~1k thinking tokens | ~$0.03 | ~$0.015 |

**Judgements needed**, measured from the F0/F2 decision receipts: ticker-days that reached the VCP (entry-timing) stage per 5-year window.

| Run | Ticker-days | Ticker-weeks | Episodes (≥ 10-day gap) | Episodes (≥ 20-day gap) |
|---|---|---|---|---|
| F0, S&P 400/600, 2017-21 | 37,986 | 9,819 | 1,323 | 1,072 |
| F0, 2022-26 | 34,216 | 9,146 | 1,342 | 1,074 |
| F2, S&P 1500, fundamentals rank-only, 2017-21 | 110,676 | 42,214 | 11,499 | 7,283 |
| F2, 2022-26 | 97,535 | 38,022 | 10,641 | 6,815 |

- The brief's "~12,000" corresponds to F0's ticker-weeks or F2's 10-day episodes.
- A **portfolio backtest needs every day judged**, because the book decides daily. That is the ticker-days column.

**Cost of one full 5-year window, for one configuration:**

| Calls | Haiku 4.5, batch | Sonnet 5, batch | Opus 5.5 |
|---|---|---|---|
| 12,000 | ~$16 | ~$31 | ~$180-360 |
| 38,000 (F0, every day) | ~$49 | ~$97 | ~$570-1,100 |
| 111,000 (F2, every day) | ~$144 | ~$283 | ~$1,700-3,300 |

- **Every full-window run breaks the $10 cap, even on the cheapest model**, before multiplying by prompt variants. And the window would be contaminated anyway.
- **Claude Code subagents are not a loophole.** They cost session time, not metered dollars. But they run on the session model (Opus 5.5, June 2026 cutoff), they carry file and web tools, and they are not a pinned API snapshot.
- **Determinism.** Current Opus and Sonnet 5 models reject `temperature` with a 400, so the experiment-3 draft's "temperature 0" is impossible there. Reproducibility means storing every raw output and **never re-querying**.
- A failed call is logged as **MISSING**, never as NO or NEUTRAL (experiment 1's bug #24), and coverage must be at least 98%.

### 2.6 Survivorship

- **Universe.** Current S&P 400/600/1500 members only. Names promoted because they rose are in; names delisted or dropped are out.
- **The LLM probably tilts toward exactly those names.** Strong, clean charts are the ones that got promoted.
- **In the ~10-month clean slice** the bias is smaller: one year of index changes, and few delistings. It is still not zero, so declare it.
- **What reduces it:** a within-day contrast (judged-yes vs judged-no, on the same days, from the same universe) cuts the bias but does not remove it.
- **Minervini's buys:** 62 of 77 fall outside any universe we have, so an agreement test covers only 15-18 names (`RESULT.md`).

### 2.7 Further risks, briefly

- **Yes-rate pathologies.** A judge that says "buy" to 90% or to 3% of charts gives a weak contrast by construction. Calibrate the yes-rate without outcomes (step 1).
- **Pivot extraction.** Reading a pivot off an image is imprecise. Use the LLM's buy/no-buy on the detector's day set, and keep the engine's trigger and stop mechanics for any later portfolio test.
- **Horizon mismatch.** The literature's LLM edges last 1-2 days (`LITERATURE_MEMO.md` Q7), while this strategy holds for weeks.
- **Model drift.** Aliases can be refreshed. Pin the dated snapshot ID, and log the returned model string on every call.
- **App restarts.** They have killed long jobs before. The batch job must be resumable from stored outputs and must never re-ask a stored item.

---

## Part 3. The smallest honest test

**Question:** on dates the model cannot have seen, do the setups the LLM approves go on to beat the ones it rejects, and does it separate them better than the mechanical VCP detector on the same candidates?

- **Level:** signal level only. No portfolio backtest.
- **Model:** Claude Haiku 4.5 (the only documented vision model with ~10 scoreable months).
- **Optional secondary:** Sonnet 5 on its own ~4-month slice. It is the model that could actually continue forward.
- **Outcome of the test:** KILL or NOT FALSIFIED. Never "edge".

### Step 0: Freeze (no calls; half a day)

Commit and push `experiment4/PREREGISTRATION.md` before any API call, with a claim and lock like experiment 2's. It fixes:

- **Model.** The dated snapshot ID, its documented cutoff, and the clean window. For Haiku, decision dates run 2025-09-01..2026-06-26 (60-day outcomes; to 2026-08-26 for 20-day outcomes). For Sonnet 5, they run 2026-03-01..2026-06-26.
- **Rendering code, by hash.**
  - 12 months of daily candles, rebased to 100, with volume as a multiple of its 50-day average and the 50/150/200-day MAs.
  - No dates, no ticker and no index panel.
  - Random file IDs and stripped metadata.
- **Prompt, by hash.** Zero-shot, written from the book's VCP rules only. Output is JSON: `{base_present, n_contractions, pivot_pct_of_last_close, buy_now, confidence}`. Thinking is off, and there is no temperature parameter where the model rejects it.
- **Population and sample.**
  - The population is F2's pre-filtered ticker-days in the window: S&P 1500, Trend Template + RS + regime passed, fundamentals rank-only. Measured: 24,777 ticker-days in 2025-08-01..2026-06-30, of which 1,319 were detector PRICE_READY.
  - The sample is drawn by a seeded RNG: every detector-YES day and 900 detector-NO days, each thinned to one per ticker per 20 trading days. The cap is 1,500 judgements.
- **Outcome code, by hash.** The return from the next open to the close 20 and 60 trading days later, minus the equal-weight universe over the same days. Plus a path outcome that fits a stop-out machine: "+20% reached before −10%".
- **Verdict rules and the cost cap** (below).
- **Survivorship and contamination labels**, stated in advance.

### Step 1: Competence and yes-rate, with no outcomes (≈ 300 calls)

- **Competence check.** 100 synthetic textbook VCPs (uptrend, 2-4 contractions of shrinking depth, volume dry-up, breakout) against 100 volatility-matched random walks. There is no future, so nothing can leak.
  - **Pass:** accuracy ≥ 80% and pivot error ≤ 3%.
  - **Fail:** stop the project here. The model cannot read the pattern.
- **Prompt iteration** is allowed in this step only, and every version is logged. It must reach one frozen primary configuration within the step's budget.
- **Yes-rate calibration.** 100 real pre-cutoff pre-filtered charts, whose outcomes are **never computed**.
  - A yes-rate outside 10-70% means the judge is uninformative, and the test stops.
  - Nobody looks up what those stocks did.

### Step 2: Leakage probe (≈ 520 calls per model)

- Run the peer memo's panels A-E, including the 200 pre-cutoff + 200 post-cutoff outcome panel.
- **Pre-declared rule:** if month-by-month date or outcome skill stays elevated after the documented cutoff, move the window start past the *effective* cutoff and record that.
- Pre-cutoff data stays unusable for any performance claim, whatever the result.

### Step 3 (optional, descriptive only): agreement with Minervini (≈ 108 calls)

- 18 exact-dated in-universe buys, each with 5 matched non-picks: same date, Trend Template + RS passed, same sector where possible.
- **Report:** the LLM's buy rate on his entries against the controls, next to the detector's (1 of 15 near his date).
- **Label it** "pre-cutoff, publicised trades, contaminated: face validity only". It carries no decision.

### Step 4: The test (≈ 1,500 calls for Haiku, ≈ 700 for Sonnet 5)

- **Procedure:**
  - The judgements run as one batch job.
  - Raw outputs are stored, hashed and pushed **before** the outcome script runs.
  - They are never re-queried.
  - The outcome script, already committed, then runs once.
- **Primary statistic:** the 60-day excess return of LLM-yes minus LLM-no on the same days, as a calendar-time portfolio contrast. Use the stationary block bootstrap of experiments 2 and 3 (block 20, 10,000 resamples, seed 7).
- **Head-to-head, pre-declared as secondary:**
  - The same contrast for detector-yes minus detector-no.
  - The discordant cells:
    - LLM-yes & detector-no against LLM-no & detector-no: does the LLM find good setups the detector misses?
    - LLM-no & detector-yes against both-yes: does it veto bad detector picks?
  - The "+20% before −10%" hit rate for each group.
  - The 20-day horizon.
- **Verdict:**
  - **KILL** the AI-judge idea if the primary contrast's point estimate is ≤ 0, **or** if it is not above the detector's contrast on the same sample.
  - **NOT FALSIFIED** otherwise. The label is "pseudo-out-of-sample, one regime, survivorship-biased", and it is never quoted as an edge.
  - With Sonnet 5 as the secondary, the Holm correction is over 2.
- **Power, stated in advance:**
  - Assumptions: ~30% yes, a per-signal 60-day SD of ~24% (`DESIGN_REVIEW.md` T10), and a design effect of ~2.5.
  - The minimum detectable contrast is about **4.5 points per 60 days**, roughly 19% a year, at 80% power and one-sided α = 0.10.
  - The test can catch only a large effect or falsify. A modest real effect would most likely come out INCONCLUSIVE-looking. That is the honest price of having only 10 clean months.
- **Why no portfolio backtest.**
  - About 10 months of a max-4 book is roughly 15-25 trades, and portfolio P&L adds slot, exit and cash noise to a signal question.
  - Every longer window is contaminated.

### Step 5: Only if NOT FALSIFIED

- **Forward signal log** with the same frozen prompt, on a model that will not retire mid-test (Sonnet 5 or later), from the next trading day, pushed before each open.
  - About 40 judgements a week, roughly 2,000 a year, costs about $5 a year with Sonnet 5 on batch.
- **A portfolio arm** comes only after at least 6 months of forward signal data, under its own pre-registration.
- **No historical portfolio backtest** at any point.

### Cost estimate

| Step | Haiku 4.5 calls | Sonnet 5 calls (optional secondary) |
|---|---|---|
| 1. Competence and yes-rate | 300 | 300 |
| 2. Leakage probe | 520 | 520 |
| 3. Minervini agreement (optional) | 108 | 108 |
| 4. Test | 1,500 | 700 |
| **Total** | **≈ 2,430** | **≈ 1,630** |
| **Cost at batch prices** | **≈ $3.2** | **≈ $4.2** |
| With 20% retry margin | ≈ $3.9 | ≈ $5.0 |

- **Haiku alone:** about $4, well inside the $10 cap.
- **Haiku plus the Sonnet 5 secondary:** about $9. That is inside the cap with almost no margin, so the owner should either drop step 3 and the Sonnet secondary or raise the cap.
- **Wall time:** 1-2 days, with batch results within 24 hours.
- **Deadline:** Haiku 4.5 retires no sooner than 2026-10-15, so steps 0-4 must finish before then.
- **Prerequisite:** an Anthropic API key, which the project does not have today.
- **Free alternative:** Gemini on the existing key, but its cutoff is undocumented. The step-2 probe would first have to establish an effective cutoff, and free-tier rate limits apply.

### What this test can and cannot say

- **It can say:**
  - "The LLM cannot read the pattern" (step 1).
  - "It sees the future on old charts" (step 2).
  - "Its approvals did not beat its rejections on unseen dates", or "it did no better than the detector" (step 4).
  - Each of these is a cheap, decisive stop.
- **It cannot say** "AI chart reading makes money". At most it says "not falsified on 10 months of one regime", which earns a forward test and nothing more.
