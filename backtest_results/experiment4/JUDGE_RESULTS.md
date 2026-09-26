# Experiment 4: AI chart judge, results (Steps 0, 2 and 3)

**Verdict: REJECTED at Step 3, the pre-registered clean test. The AI chart-judge idea is closed for this strategy** (TEAM_PLAN decision 3).

## Setup

- **Judge:** Claude Haiku 4.5 subagents, prompt v1 frozen before any judgement (`JUDGE_PROMPT_v1.md`), 3 charts per call.
- **Compliance:** checked by code from every transcript:
  - exactly one untruncated Read of its own batch file;
  - no other tool;
  - complete answers.
- **Runs:** 20 + 46 + 71 = 137 judge calls, all accepted.
  - Two earlier delivery runs were discarded unscored (Amendments 1–2).
- **Cost:** no API spend; the judges ran as Claude Code subagents.
- **Answers:** saved in `judge_answers/step{0,2,3}.jsonl`.
- **Rescore:** `python kashif_engine/scripts/ai_judge_batches.py score | step2 | step3`.

## Step 0: can it read a base at all? PASS

On 60 synthetic charts (30 textbook VCPs, 30 not): **93% correct** (gate: 80%). Readiness separates the two groups with AUC 0.96.

| Chart type | Judged a valid base |
|---|---|
| VCP | 27 of 30 |
| Downtrend | 0 of 10 |
| Loose | 0 of 10 |
| Extended | 1 of 10 |

## Step 2: does it see what Minervini saw? Barely; not distinguishable from chance

**Data:** 23 of his disclosed buys, each with 5 matched controls, shown up to the evening before the buy. Scored within match groups, as the eval set's README specifies.

| Score | AUC, within groups (23 buys) | AUC, 18 filter-passing buys |
|---|---|---|
| AI buy_readiness | **0.58**; 95% CI [0.47, 0.69]; permutation p = 0.12 | 0.58 |
| AI valid_base | 0.55 | 0.54 |
| Last-bar relvol / last-bar return | 0.44 / 0.50 | 0.48 / 0.50 |

- It clears the pre-registered stop line (> 0.55), so the plan proceeded to Step 3.
- But the result is statistically indistinguishable from chance.
- The AI marked 61% of his buys and 50% of the controls as valid bases. The loosened mechanical detector gave 35% and 25%.
- **Post hoc (direction chosen after seeing the data):** his buys sat further below their 1-year high than the controls, AUC 0.71 inverted, p = 0.001. A single plain number beat the AI.

## Step 3: the clean screening test on unseen data. REJECTED

**Data:** 212 breakouts dated 2025-09-05 to 2026-03-25, after Haiku 4.5's training cutoff; 53 became +50% winners. The baselines were fixed in `STEP3_PREREG.md` before judging.

| Measure (60-day forward return, fwd60) | AI judge | Bar | Pass? |
|---|---|---|---|
| AUC for winners | **0.42** | 0.799 (8-statistic logistic, fit pre-2025-09) | no |
| fwd60: AI valid_base yes vs no | +8.6% (119) vs **+10.9%** | yes > no | no |
| fwd60 of the AI's top third | **+4.4%** (rest +12.2%) | +20.9% (statistics top third) | no |
| same | +4.4% | +11.3% (mechanical detector yes) | no |

Paired bootstrap: P(AI AUC > baseline AUC) = 0.000.

### Why it failed (post-hoc diagnostic, clean 212)

The AI's readiness correlates **negatively** with the strongest predictors of winners:

| Statistic | Correlation with readiness | Winner AUC |
|---|---|---|
| ATR% | −0.42 | 0.80 |
| 20-day return | −0.39 | 0.75 |
| 60-bar depth | −0.40 | 0.74 |

The judge applies the VCP criteria faithfully: tight, calm, not extended. In this sample, though, the big winners were the volatile, already-running breakouts.
- Its reading skill is not the problem (Step 0 scored 93%).
- The problem is that a textbook-tight base does not identify the big winners here. This matches Fork 4's finding that the classic VCP cues (volume dry-up, breakout volume) score AUC about 0.51.

**Caveat (README caveat 3):** the winner label rewards volatility, and volatile names get stopped out more often. Even so, the AI's picks also had lower plain 60-day returns, so the rejection does not rest on the label alone.

## Side findings

- **Data flag, not changed:** Minervini-set control ME0106 (KNTK, anchor 2021-06-17) has a +204% bar on 376× volume at bar 96, almost certainly an unadjusted corporate event. It is 1 of 115 controls, with negligible effect. Reported to the set's owner (First Trial) for review.
- **Tooling lessons:**
  - The subagent Read tool refuses more than 25k tokens and silently truncates output at about 39k characters.
  - `tool_uses` counts the `SubagentHandback` call.
  - Compliance must therefore be checked from transcripts, not from counts or agents' own claims.

## What this means for the project

Replacing the mechanical VCP detector with an AI chart judge does not help, as tested:
- Haiku 4.5, frozen prompt v1;
- descriptive agreement with Minervini at chance level;
- worse than both simple statistics and the mechanical detector on unseen breakouts.

The evidence points the other way. Momentum and volatility statistics, which need no AI, carry the signal. That is a different strategy from textbook VCP-tightness and would need its own pre-registered test.
