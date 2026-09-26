# AI chart judge: prompt v1 (FROZEN before any chart was judged)

**Model:** Claude Haiku 4.5, run as a Claude Code subagent (`model: haiku`), with NO tools. Any batch whose usage shows a tool call is discarded.

**Criteria source:** the consultant's summary of Minervini's own descriptions (`backtest_results/consultant/CONSULTATIONS.md`), in our own words.

**Steps:**
- Step 0: 60 synthetic charts.
- Step 2: First Trial's Minervini set, bars 0..248 (the evening before the buy).

Charts are batched 23 per call. The labels are never shown.

## Prompt text (verbatim; only the chart block changes)

You are judging anonymized daily stock charts. Do not use any tools: answer only from the data in this message.

Each chart is a table:
- `bar` runs 0 (oldest) to N (the most recent completed day).
- `high` / `low` / `close` are prices rescaled so the first close is 100.
- `relvol` is that day's volume divided by its average over the previous 50 days.

There are no tickers and no dates. Do not guess what stock or period it is.

For each chart, decide whether it currently shows a sound volatility-contraction base (VCP) in an established uptrend, near a buyable pivot, as practiced by growth-stock traders in the Minervini style. The typical traits are rules of thumb, not strict tests:
1. A clear uptrend led into the base.
2. The base lasts roughly 3 to 65 weeks. Its first correction is usually 10-35% deep and rarely more than about 50%.
3. Successive pullbacks inside the base generally get smaller, often about half the prior one, give or take; usually 2 to 6 of them. One shakeout that briefly undercuts a prior low can still be acceptable.
4. The final contraction is tight: small daily ranges, closes near each other.
5. Volume dries up (relvol well below 1) in that tight area.
6. The pivot is the top of the final tight area. The price now sits within about 5% below the pivot, or is just breaking out above it.
7. The price is not already extended far above the pivot.

Reply with ONLY one JSON object per chart, one per line, no other text:
`{"id": "<chart id>", "valid_base": true|false, "pivot": <rescaled price or null>, "buy_readiness": <0-100: how strongly a disciplined trader would want to buy a breakout over the pivot in the next few days>, "reason": "<at most 12 words>"}`

## Scoring (fixed now; `kashif_engine/scripts/ai_judge_batches.py score`)

- **Step 0:** the accuracy of `valid_base` against the synthetic truth.
  - Stop if below 80%: the model cannot read a base.
- **Step 2:** the AUC of `buy_readiness` for Minervini's buys against their matched controls, on all 23 buys, and on the buys that pass our trend and RS filters.
  - Descriptive only: his buys are pre-cutoff and famous, so agreement cannot prove skill.
  - Stop if AUC ≤ 0.55 (no better than chance at seeing what he saw).
  - No prompt change after seeing any score.

## Delivery rule (added before any judgement)

- Each batch is too large to paste into the agent's prompt, so the agent makes **exactly one** Read call, of its own batch file (`kashif_data/experiment4/judge/<step>_batchNN.txt`), and uses no other tool.
- The synthetic labels were moved outside the repository before any run.
- **Any batch whose usage shows more than one tool call is discarded and re-run by a fresh agent.**
- The answers come back in the agent's final reply and are saved unchanged to `kashif_data/experiment4/judge/answers_<batch>.jsonl`.

## Amendment 1 (delivery only; recorded before any answer was scored)

**Run 1 was discarded in full.** Every batch broke the one-Read rule:

| Batch | Tool calls | Charts answered |
|---|---|---|
| step0 00 / 01 / 02 | 10 / 6 / 5 | 17 / 5 / 4 of 23, 23, 14 |
| step2 00 / 01 / 02 | 10 / 3 / 2 | 13 / 4 / 0 of 23 (b02 refused) |
| step2 03 / 04 / 05 | 9 / 7 / 5 | 9 / 16 / 4 of 23 |

- **Root cause:** a 23-chart batch is about 54k tokens, but one Read call returns at most 25k. No judge could see its whole batch in one read.
- **Scoring:** none. The Step-0 labels and the Step-2 key were not opened, and no run-1 answer was saved.

**The change (delivery only):**
- Batches are 6 charts: at most 45.8 KB, about 14k tokens and 1,512 lines, so one default Read gets the whole file.
  - Step 0: 10 batches. Step 2: 23 batches.
- The synthetic labels are written to `kashif_data/experiment4/judge_keys/`, outside the judge's folder.
  - Rebuilt with the same seed, they are byte-identical to the pre-run-1 copy, so these are the same charts.
- **Agent prompt:** the delivery line below, then the frozen prompt text above unchanged, except that its first sentence ends "answer only from the data in that file".
  > Make exactly ONE tool call: Read the file <path> (no offset or limit; it fits in one read). Use no other tool at all. If that single read fails, reply only with READ_FAILED.
- **Gating:** Step 2 is launched only after Step 0 scores at least 80%.
- The criteria, the JSON format and the scoring rules are unchanged.

## Amendment 2 (delivery and compliance check; recorded before any answer was scored)

**Run 2 (Step 0, 6-chart batches) was discarded in full**, as checked by code (`ai_judge_batches.py extract`):
- 8 of 10 batches: truncated. The Read tool cuts its output after about 39k characters (line 1188 of 1512), so each judge saw only 4–5 of its 6 charts.
- The other 2 batches: read the file twice.
- No answer was saved or scored.

**Two measurement errors were found:**
1. The `tool_uses` count includes the `SubagentHandback` call that returns the reply, so a compliant judge shows 2, not 1. Counting tool calls was the wrong check.
2. The judge's JSON is written as text before the handback, and the handback often holds only a summary.

**The fixes:**
- **Batches are 3 charts.** Step 0: 20 batches. Step 2: 46 batches. The largest read shows about 25.1k characters, and `build` refuses any batch over 35k.
- **Compliance is decided by code from the transcript**, in the session's `subagents/agent-<id>.jsonl`, by `ai_judge_batches.py extract <batch> <transcript>`. It checks:
  - exactly one Read, of this batch file, with no offset or limit;
  - the Read result contains the file's last line, so nothing was truncated;
  - no tool other than that Read and `SubagentHandback`;
  - answers for exactly this batch's charts.
- The first answer given per chart is kept, and later revisions are ignored.
- Answers are saved only when every check passes. A failing batch is re-run once by a fresh agent.
- The prompt text, criteria and scoring are unchanged. The synthetic labels are again byte-identical after rebuilding.
