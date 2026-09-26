# Model-book chart evaluation set (signal level)

Built 2026-09-27 by the "Fork 4" session from the experiment-2 model book (`kashif_data/experiment2/model_book_dev/`). It is data only: no LLM was called, and nothing outside this folder was changed.

**Purpose.** Test whether a chart judge (AI or otherwise) can tell, *on the breakout day*, which breakouts went on to become big winners. The judge sees only an anonymised 250-bar chart.

## Files

| File | Contents |
|---|---|
| `windows.parquet` | 505 samples × 250 bars = 126,250 rows. Columns: `sample_id, bar, open, high, low, close, vol_rel` (float32). |
| `key.csv` | One row per `sample_id`. **Never show it to the model.** |
| `README.md` | This file. |

**`windows.parquet`:**
- `bar` 0 is the oldest bar and `bar` 249 is the signal day. No bar after the signal day is included.
- Prices are split-adjusted OHLC divided by the window's first close × 100, so `close` at `bar` 0 is 100.
- `vol_rel` is volume divided by its trailing 50-bar mean, including that bar (the engine's convention).
- There are no tickers, dates or price levels.
- Sample ids are a random permutation (seed 41), so row order carries no label or date information.

**`key.csv` columns:**
- The label and identity: `ticker, date, label` (WINNER / NON_WINNER), `episode_id` (winners), `matched_to` (the winner a control was drawn for) and `date_offset` (a control's distance from that winner's date, in trading days).
- Forward returns: `fwd_ret20, fwd_ret60, fwd_ret126` (split-adjusted close to close) and `fwd_max126` (highest close in the next 126 days, relative).
- Baseline features the chart does not show: `rs_pct, vol_ratio, dist_52wh, raw_close, addv50, fund_verdict, vcp_ready_x1_2, regime_open`.

## How the set was built

**Qualified breakout.** Used for both classes, and evaluated with the model book's point-in-time data:
- a liquid day: raw close of at least $10 and 50-day dollar volume of at least $5M;
- Trend Template tt_1–tt_8b passes;
- RS percentile ≥ 70;
- close above the prior 50-day closing high;
- volume ≥ 1.2× its 50-day average;
- **fresh**: no other qualified day for that ticker in the previous 20 trading days.

The mechanical VCP detector, fundamentals and the regime gate are deliberately *not* required. The chart judge is meant to replace the base reading, and the key records those verdicts for comparison.

**Freshness applies to both classes.** Without it, 96% of winner days would be fresh against 33% of candidate controls. A judge could then separate "first breakout" from "continuation day" without reading the base at all.

**WINNER.** For each of the 447 model-book episodes (a ≥ +100% run within 126 days, 2022-01..2026-09), the winner sample is the first fresh qualified day inside the episode's catchable window whose next-126-day maximum close is at least +50%. The catchable window runs from the run's low to its last day with ≥ +50% still left.

**NON_WINNER.**
- A fresh qualified day with a full 126-day horizon whose next-126-day maximum close stayed below +50%.
- 3 are drawn per winner, without replacement, with seed 41, on the winner's date.
- When fewer than 3 are available on that date, the rest come from the nearest dates within ±5 trading days.

Both classes need a full 126-day forward horizon, so signal dates end at 2026-03-25.

## Counts

**Winner selection:**

| Step | Count |
|---|---|
| Model-book episodes | 447 |
| … with no fresh qualified day that had ≥ +50% ahead | −304 (the Trend Template and RS block most of them, as in the model book) |
| … signal day after the horizon cutoff | −12 |
| … fewer than 299 bars of history (recent listings) | −3 |
| **Winners** | **128** (109 tickers) |
| **Non-winners** | **377** (123 winners have 3 controls, 4 have 2, and TTMI 2025-06-09 has none: almost every breakout that week became a winner) |
| Total samples | **505** on 372 tickers |

**Class balance: 25.3% winners.** This is by construction. The natural rate is lower: among all 3,118 fresh qualified breakouts with a full horizon, 11.9% reached +50% and 2.5% reached +100%.

**Date matching:** 268 of the 377 controls are on the winner's exact date, 88 are within ±1 trading day, 19 within ±2–3, and 2 at +5.

**By year** (signal date):

| | 2022 | 2023 | 2024 | 2025 | 2026 (to 03-25) | Total |
|---|---|---|---|---|---|---|
| WINNER | 8 | 15 | 30 | 40 | 35 | 128 |
| NON_WINNER | 24 | 44 | 88 | 116 | 105 | 377 |

**Samples after 2024-06-30 (a likely training cutoff): 374 of 505 (74%)**, of which 95 are winners and 279 non-winners. The other 131 (33 winners, 98 non-winners) are from 2024-06-30 or earlier.

**Forward returns (median):**

| | 20-day | 60-day | 126-day | 126-day maximum |
|---|---|---|---|---|
| WINNER | +10.9% | +37.8% | +62.1% | +85.8% |
| NON_WINNER | +0.4% | +0.2% | −1.5% | +16.0% |

## The bar to beat: trivial chart statistics

Every statistic below except RS and price is computable from the anonymised window itself. AUC is 0.5 for chance and 1.0 for perfect.

| Statistic (from the window) | AUC, all | AUC, up to 2024-06-30 | AUC, after |
|---|---|---|---|
| ATR14 as % of close | **0.774** | 0.719 | 0.794 |
| 20-bar return | **0.767** | 0.759 | 0.770 |
| Depth of the last 60 bars (highest high to lowest low) | **0.776** | 0.806 | 0.767 |
| 60-bar return | 0.678 | 0.650 | 0.687 |
| 250-bar return | 0.664 | 0.759 | 0.631 |
| Distance below the 250-bar high | 0.424 | 0.449 | 0.415 |
| Breakout-day `vol_rel` | 0.513 | 0.453 | 0.536 |
| Volume dry-up (mean `vol_rel` over the prior 10 bars) | 0.507 | 0.490 | 0.515 |
| *RS percentile (not in the window)* | 0.666 | 0.767 | 0.636 |
| *Raw price (not in the window)* | 0.433 | 0.327 | 0.466 |
| **Logistic regression on the 8 window statistics**, 5-fold cross-validation grouped by matched set | **0.809** | 0.813 | 0.807 |

- **What separates the classes.** Winners were more volatile (median ATR 4.2% vs 3.0%) and already running (median 20-bar return +21% vs +10%). They were also coming out of wider recent ranges (median 60-bar depth 35% vs 25%).
- **What does not.** The classic VCP cues, volume dry-up and breakout-day volume, carry no signal here.
- **What this means for a chart judge.** It must beat **AUC 0.81**. It should also be scored against the same judge-free baselines on the risk-adjusted outcomes in `key.csv`, not only the +50% label.

## Caveats

1. **Hindsight selection.**
   - Winners come from runs identified after the fact, and each winner's signal day is chosen using its future (the first day with ≥ +50% ahead).
   - Controls are also chosen by outcome.
   - The set therefore measures *discrimination on a 1:3 set*, not precision on live candidates, where the base rate is about 12% for +50% and 2.5% for +100%.
2. **The middle is excluded.** Qualified days that rose ≥ +50% without belonging to a model-book doubling episode are in neither class. That makes the classes cleaner than reality, so real-world AUC will be lower.
3. **The label rewards volatility.** "+50% maximum within 126 days" is easier for volatile stocks. ATR alone gets AUC 0.77, and model-book section 4 showed that the same volatile names are stopped out more often (about 55% touch −8% within 20 days at ATR 5–7%). Judge on `fwd_ret60`/`fwd_ret126` and on stop-aware outcomes too.
4. **Memorisation is reduced, not removed.**
   - Anonymisation hides the ticker, date and price level.
   - A chart's *shape* can still identify it. Market-wide shocks (for example April 2025) date a chart, and famous runs (GME, HIMS, SEZL, CAR) may be recognisable.
   - Date matching makes market-level clues equal between the classes, but not stock-specific ones.
   - "After 2024-06-30" is only clean for a model whose training cutoff really is before that date. Most current models' cutoffs are in 2025–2026, so **no sample here is guaranteed unseen**. Only forward data is.
5. **Survivorship.** The universe is today's S&P 400 + 600 members, so failed or removed companies are missing.
6. **Small N.** 128 winners give an AUC standard error of about ±0.025. Compare judges on the same samples with a paired test (DeLong or a bootstrap), not by eyeballing.
7. **Listing bias.** A window needs 299 bars, so listings younger than about 14 months are absent; 3 winners were dropped for this reason.
8. **Prices are split-adjusted, not dividend-adjusted.** Forward returns exclude dividends.

## My view

**Is an AI chart judge worth trying?** Yes, but as a cheap, falsifiable experiment, not a build.
- The mechanical VCP detector demonstrably misses the bases a discretionary trader accepts.
- On this set, the classic VCP cues (volume dry-up, breakout volume) carry no signal. That suggests the "base quality" a human reads may not be where the edge is.
- The honest prior is that a vision or LLM judge will mostly rediscover volatility and momentum, which a two-line formula already captures at AUC about 0.8.
- It is worth pursuing only if it adds information *beyond* those statistics: better AUC than the logistic baseline on the same samples, **and** better risk-adjusted forward returns among its top picks.

**Biggest risk: lookahead through memorisation, and confusing volatility with skill.**
- Any model trained on 2017–2026 text and charts may recognise a chart or its era. It would then "judge" with knowledge of the outcome, and any in-sample test would look great.
- The second risk is subtler. A judge that simply prefers volatile, extended charts will score well on a "+50% maximum" label and still lose money to stops.
- Both risks point to the same fix: treat any historical result as a screening test only, and **decide on forward, post-cutoff data**, as in the experiment-3 draft.

**How to handle hindsight-selected winners:**
1. Never report accuracy on this set as expected trading performance. Report the AUC together with the natural base rate of about 12%.
2. Use it only to **reject** judges: one that cannot beat the 0.81 baseline here will not beat it live.
3. Freeze the judge (prompt, model, threshold) *before* scoring it, and score it once.
4. For the forward test, rate **every** fresh qualified breakout each day, not a curated winners-plus-controls set, so the outcome distribution is the real one.
5. Keep the key file away from anything the model can read.
