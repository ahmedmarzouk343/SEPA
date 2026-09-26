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
