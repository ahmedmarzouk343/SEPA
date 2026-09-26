# Experiment 4, Step 3: the clean screening test (pre-registered before any Step-3 judgement)

**Question.** On breakouts the judging model cannot have seen in training, does the AI chart judge pick future winners better than simple chart statistics and our mechanical VCP detector?

## Judge (unchanged)

- **Model and prompt:** Claude Haiku 4.5 subagents with the frozen prompt v1 (`JUDGE_PROMPT_v1.md`).
- **Delivery:** as in Amendments 1–2. Batches of 3 charts, one Read per judge, compliance checked from the transcript by `ai_judge_batches.py extract`.
- No prompt, model or format change. Step 0 (93%) and Step 2 (AUC 0.58) were scored before this file was written, and neither changed the judge.

## Data

**Source.** Fork 4's `kashif_data/experiment4/modelbook_eval/`:
- fresh qualified breakouts, each with its own real forward returns;
- WINNER means a later +50% maximum within 126 days;
- 3 date-matched NON_WINNERs per winner.

**Clean window.** Signal date on or after **2025-09-01**: Haiku 4.5's training data runs to July 2025, plus a one-month buffer (`research/CLEAN_WINDOWS_AND_LEAKAGE.md`).
- **212 samples: 53 WINNER and 159 NON_WINNER, from 2025-09-05 to 2026-03-25.**
- The 293 earlier samples are used **only** to fit the statistics baseline.

**What the judge sees.**
- Bars 0..249; bar 249 is the breakout day, and nothing after it is shown.
- Ids are `B<sample_id>`, shuffled with seed 61. There are 71 batch files.
- **Known deviation:** this set's `relvol` divides by a 50-bar mean that *includes* the day itself, while the prompt says "previous 50 days". The effect is small (a 3.0× spike shows as about 2.9×) and applies equally to both classes.

## Baselines (computed and fixed now, before judging)

All are measured on the same 212 samples, with `fwd_ret60` = the 60-day forward close-to-close return.

| Baseline | Value |
|---|---|
| **Statistics:** logistic regression on the README's 8 window statistics, fit on the 293 pre-2025-09 samples only | AUC **0.799**; top third mean fwd_ret60 **+20.9%** (rest +4.1%) |
| **Mechanical VCP detector** (`vcp_ready_x1_2`, 38 yes) | yes +11.3%, no +9.3% |
| All 212 | +9.6% |

The 8 statistics were verified against the README's single-statistic AUCs; all 8 match to 3 decimals.

## Rule (from the README: this set can only *reject* a judge)

**REJECT** the AI chart judge if **any** of these holds:
1. its `buy_readiness` AUC is ≤ 0.799 (the statistics baseline);
2. the mean fwd_ret60 of AI `valid_base = true` is ≤ that of `false`;
3. the mean fwd_ret60 of its top third by `buy_readiness` is ≤ +20.9% (the statistics top third);
4. the mean fwd_ret60 of its top third is ≤ +11.3% (mechanical yes).

**Also reported (not decisive):** a paired bootstrap probability that the AI's AUC beats the baseline's, and the medians.

**If rejected:** the AI chart-judge idea is closed for this strategy (TEAM_PLAN decision 3, recommended). This is recorded in the results and not re-tested with a tuned prompt.

**If it survives:** that is a screening pass only, not proof. The winners were chosen in hindsight, and the sample is small. The next step would be a forward test on *every* fresh breakout, not a curated set.
