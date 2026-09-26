# Experiment 3: team synthesis and proposed plan

**Status:** a proposal to the owner, 2026-09-26. Nothing here is binding until the owner approves it and a final pre-registration is committed.

**Inputs.** Three research memos in `research/`, written independently in parallel, plus a peer engineer building the code:

| Memo | Author | Covers |
|---|---|---|
| `LITERATURE_MEMO.md` | researcher | published evidence, with citations |
| `LESSONS_FROM_EXP1_EXP2.md` | analyst | what held in both historical periods |
| `DESIGN_REVIEW.md` | statistician | power, arms and the honesty of each option |

## 1. What the team agrees on

1. **Expect a small edge at best.**
   - Published long-only momentum beats the index by about +2–3% a year after costs. No audited systematic strategy with 100%+ a year was found.
   - Live Sharpe ratios fall a median 73% from their backtests.
   - Realistic range for any version: −3% to +3% a year against the index, with drawdowns of 20–40%.
2. **Our problem is sitting in cash, not picking stocks.**
   - The strategy was invested only 26–50% of the time. The money it did invest earned about what the index would have, in both periods.
   - With idle cash parked in the index, experiment 1's strategy would have made about 13.4% a year in 2017–2021, against 12.5% for MDY/IJR.
3. **Most trades are quick stop-outs.**
   - 55–63% of trades hit the stop within about a week, in both periods. All the profit came from the few long holds.
   - The stops mostly cut real losers: stopped trades kept falling afterwards on average. Wider ATR stops would have saved few winners.
4. **Nothing tuned survived.** Every tuned setting helped in one period and not the other: the pick's edge, "defensive mode off", RS 90, and the let-winners-run exits. Don't tune parameters again.
5. **The forward test cannot prove a modest edge in any reasonable time.**
   - Even with the better metric below, 5 years detects only about +11% a year of excess at 80% power. A 2–4% edge would take decades.
   - The forward test can catch a failure or a very large edge, and that is all.

## 2. Where the team disagrees, and how it is resolved

**Relative strength ≥ 95 (the draft's H2).**
- The model book (2022–2026) found RS ≥ 95 stocks double more often.
- The analyst found that *in actual trades*, higher entry RS gave worse results in **both** periods (correlation −0.24 and −0.20). Those stocks are the most volatile, so the stop shakes the strategy out.
- The literature has never tested the top-5% extreme.
- **Resolution:** keep B1 as written, since it was committed before the validation window was opened. Let the one-shot screen (3a) decide whether it survives, and do not add an RS ≥ 70 version to 3a. The analyst's evidence for that version comes partly from the 2017–2021 trades, so testing it there would be circular. It goes to the forward test only.

## 3. Proposed plan

### Step 3a: a one-shot "kill screen" on 2017–2021 (about 1 day of work)

- **Legitimacy.** The statistician judges this legitimate for B1, B2 and B3 **only**, because they were committed (7857cac) before experiment 2 opened 2017–2021.
- **Rules:**
  - Freeze every open detail with neutral defaults written in advance.
  - Take the non-entry settings from experiment 2 by file hash, and use experiment 2's frozen data byte for byte.
  - Run once under a new lock. Experiment 2's lock is never touched.
- **Metric: swept excess.** The arm with its idle cash held in the benchmark, minus the benchmark.
- **Verdict:** an arm is **killed** if its swept excess over the equal-weight member basket is ≤ 0 over the five years.
  - This kills a no-edge arm half the time, and a real IR-0.5 arm 13% of the time.
  - A survivor is labelled "not falsified (pseudo-out-of-sample)" and is **never** counted as evidence of an edge.
- **Consequence:** the forward primary is the first survivor in the order B1 → B2 → B3. If all three are killed, the forward test runs only the controls, and the report says so.

### Step 3b: forward paper trading, virtual money only

Start about 1–2 weeks after approval, once the daily runner is built and rehearsed.

**Portfolio design:** the strategy's picks, with **idle cash held in the index**. This removes the cash drag the analyst found, and halves the tracking error, so the test gets twice the power.

**Arms (small on purpose):**

| Role | Arm | Why |
|---|---|---|
| **Primary** | first 3a survivor among B1/B2/B3 | the only arms with a clean historical screen |
| Secondary S1 | the primary's signals as a portfolio | more observations for the same idea |
| Secondary S2 | AI news rating: high-rated vs other candidates on the same days | the only fair test of the AI idea. Company names hidden from the model, one pinned model, never re-asked |
| Control | plain 12-1 momentum, top decile, monthly rebalance, swept | the literature's best-supported strategy, and the yardstick for whether our rules add anything |
| Reference | experiment 1's frozen strategy, swept | the analyst's recommendation |
| Placebo | 100 random-entry copies of the primary | shows what luck looks like |
| Descriptive only | an RS ≥ 70 breakout arm; a rank-based exit (stay while RS ≥ ~80) | new ideas from this synthesis, too new for a confirmatory claim |

- **Dropped:** arm A (the experiment-2 pick, which failed) and P-1 / B4 (2×ATR stops with 1% risk). The analyst found wider stops rescue few winners, and the literature is mixed.
- **Verdict rules** (from the statistician):
  - Benchmark: equal-weight basket of the frozen 2026-09-25 universe (no survivorship going forward). The arm must also beat MDY/IJR on CAGR to PASS.
  - Early looks at 24 and 36 months (p < 0.005 to stop early), a non-binding futility look at 24 months, and the final verdict at 60 months.
  - At least 60 trades before any PASS. A 25% drawdown kill is recorded as "FAIL (risk)".
  - Health flags based on signal counts, not trade counts.
- **The harness must guarantee:**
  - every order file pushed to GitHub, with an external timestamp, before the next open;
  - raw data snapshots with SEC acceptance times, and a hash chain;
  - frozen code, checked before every run;
  - a rehearsal proving it matches the backtest engine exactly.

## 4. What this cannot do

It cannot turn this strategy into a 200%-a-year system; no evidence supports that. The honest best case is an arm that roughly matches the index with lower risk, or beats it by a few percent a year, confirmed only after many years.
