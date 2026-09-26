# AI chart judge: architecture proposal (experiment 4)

Author: engineer-architect. Status: DESIGN ONLY. Nothing here is implemented, and no model has been called.
Sources read: `kashif_engine/strategies/minervini_sepa_v1/module.py` and `signals.py`, `entry_timing.py`, `vcp_detection.py`, `kashif_engine/catalyst/scorer.py`, `kashif_engine/scripts/build_catalysts.py` and `prepare_agent_batches.py`, `kashif_engine/data/fingerprint.py` and `prices.py`, and `backtest_results/experiment3/minervini_check/FIX_TESTS_RESULT.md`.
The funnel counts come from the signal caches in `kashif_data/signals/vcp_US_*.parquet`, read without changing them.

---

## 0. The answer in brief

- **Where it goes.** The judge is a third `entry_mode`, `"ai_judge"`, next to `"vcp"` and `"high50"`. It replaces only the base reading and pivot location (`SIG.vcp_table`).
  - Everything upstream stays unchanged: regime, trend template, RS, fundamentals, and the 1.2x volume pre-filter.
  - The trigger stays mechanical: `vcp_detection.check_breakout` runs with the judge's pivot. Sizing, stops and exits stay mechanical too.
- **Input and output.** The input is one anonymised text payload per (ticker, decision day): 250 daily bars rescaled to 100, plus about eight precomputed facts. The output is a strict JSON verdict.
- **Calls.** Each pre-filtered ticker-day costs exactly one call. Measured workloads:
  - about 12,500 to 13,700 calls per 5-year window with strict fundamentals on the S&P 1500;
  - about 55,000 to 60,500 calls per window under `rank_only`.
- **Cost.** At the project's own list prices, a strict window costs roughly **$7 to $11**. A `rank_only` window costs **$33 to $47**. A Batch API halves both.
- **Free tiers will not do.** The catalyst run exhausted both free providers after about 200 short calls, so a paid key is required.
- **Reproducibility.** It comes from a content-addressed cache, not from the model. The cache is keyed by `sha256(payload, model id, prompt version, schema version, decoding params)`. Backtests run in `cache_only` mode: zero API calls, byte-identical re-runs.
- **Biggest risk: memorisation.** The candidate models were trained on 2017 to 2025 market data, and both historical windows are already consumed. A leakage probe (§5) is mandatory before any full run. Only post-cutoff periods and forward paper trading can give confirmatory evidence.
- **Effort.** About **55 to 75 engineer-hours** to a pre-registered first run (§7). The staged plan is in §8. Stage 0, a calibration check on Minervini's disclosed buys, costs about $1 and should gate everything else.

---

## 1. Where the judge sits: the measured funnel

`Strategy.prepare()` (`module.py` lines 187-251) builds `pre` = regime open, trend template (or early path), RS at least 70, volume on the day at least 1.2x its 50-day average, and fundamentals OK. It then evaluates entry timing only on those ticker-days.

The table below is read from the signal caches written by the Minervini-fix runs (26 Sep).

| Cache file | Window | Arm (inferred) | Pre-filtered ticker-days | Tickers | VCP price-ready | Ready rate |
|---|---|---|---|---|---|---|
| `vcp_US_06630a7274d2` | 2017-21 | F0 (S&P 400/600, strict) | 8,595 | 493 | 947 | 11.0% |
| `vcp_US_d13712e208b8` | 2017-21 | F1 (S&P 1500, strict) | 13,681 | 780 | 1,504 | 11.0% |
| `vcp_US_35a309cc5ffc` | 2022-26 | F1 (S&P 1500, strict) | 12,477 | 803 | 1,534 | 12.3% |
| `vcp_US_2814e68b0b33` | 2017-21 | F2 (S&P 1500, rank_only) | 60,486 | 1,320 | 6,943 | 11.5% |
| `vcp_US_65c7fade1f77` | 2022-26 | F2 (S&P 1500, rank_only) | 55,368 | 1,387 | 6,854 | 12.4% |

What the detector rejects (F2, 2017-21, 60,486 rows):
- **Contraction count out of range: 33,788 rows (56%).** This is the dominant veto, and it matches the STAA/SKY/MRNA/NUE/SCHW rejections of Minervini's own buys.
- **Monotonicity failed:** 6,779 daily and 4,619 weekly.
- **No weekly base:** 3,389.
- **Weekly correction too deep:** 2,943.

This rejection pattern is what the judge is meant to re-examine.

Base length of the VCP-accepted rows:
- median 83 bars, 90th percentile 158, 95th percentile 198, 99th percentile 244;
- 4.9% exceed 200 bars and 0.7% exceed 250.

So a 250-bar window contains about 99% of accepted bases. For the longest 5%, it leaves only a short run-up before the base; the facts block below carries that longer context.

---

## 2. Data-flow diagram

```
 OFFLINE PRECOMPUTE (detached, resumable)                   BACKTEST (cache_only, 0 API calls)
 ------------------------------------------                 ------------------------------------
 panel (tt_core, tt_early, rs_pct, vol_ratio,               Strategy.prepare()
        regime, atr14_pct, pullback_depth, ...)                 |
 fundamentals_panel (PIT)                                       | same prefilter() as the runner
        |                                                       v
        v                                                   pre_long (ticker, date)
 Strategy.prefilter(universe, start, end)  <-- one function,     |
        |                                      used by both      +-- entry_mode "vcp"    -> SIG.vcp_table
        v                                                        +-- entry_mode "high50" -> _high50_table
 pre_long (ticker, date)  ~12.5k-60k / window                    +-- entry_mode "ai_judge" -> SIG.judge_table
        |                                                                               |
        v                                                                               v
 for each (t, d):  P.load(t,"US")  -> df.loc[:d].iloc[-300:]        for each (t, d): rebuild payload -> key
        |           (split-adjusted OHLCV, bars <= d only)                  |
        v                                                                   v
 anonymise()  -> payload text (no ticker, no dates, close[0]=100,     cache.get(key) --miss--> NOT_JUDGED
        |        volume / 50-bar avg at d, facts block)                     | hit                 (run refused
        |        scale S = close[0]/100 kept LOCAL, never sent               v                   if coverage
        v                                                             verdict (rescaled)          < 100%)
 key = sha256(payload | model_id | prompt_v | schema_v | decoding)           |
        |                                                                    v
        v                                                             pivot_real = pivot * S, stop_real = stop * S
 cache.get(key) --hit--> skip                                        price_ready = valid AND conf >= 0.5 (grid-loosest)
        | miss                                                                   AND check_breakout(df, pivot_real, 1.2x)
        v                                                                    |
 budget.reserve(est_max_cost) --over--> BudgetExceeded (hard stop)           v
        |                                                             self.vcp (same columns + judge_*) -> to_bundle()
        v                                                                    |       (structural += judge_model,
 provider (ONE pinned model, T=0, seed, JSON schema)                         |        judge_prompt_version, judge_schema)
        |                                                                    v
        v                                                             candidates(): volume >= breakout_volume,
 validate(JSON) --bad--> 1 repair retry --bad--> NOT_JUDGED (not cached)     RS >= rs_threshold, conf >= judge_min_confidence
        | ok                                                                 |
        v                                                                    v
 spend ledger (append) -> cache.put(key, raw, parsed, usage) atomic   allocate() -> on_entry_filled(): engine stop
                                                                      (pivot*0.97, 4%..10%); judge stop only in a
                                                                      separate, pre-registered arm
```

Two properties the diagram enforces:
1. **The model sees only the payload.** The mapping from (ticker, date) to window hash lives in a local manifest and is never sent.
2. **The backtest never calls a model.** Tuning (`rs_threshold`, `breakout_volume`, `judge_min_confidence`) re-filters rows that are already judged, following the same GRID_LOOSEST pattern as the VCP table.

---

## 3. The input

### 3.1 The window

- **Bars.** `df = P.load(t, "US")[Open, High, Low, Close, Volume]`, the same split-adjusted bars `_vcp_worker` reads. Take `df.loc[:d].iloc[-300:]`: 300 bars ending ON the decision day's close. The last 250 are shown; the first 50 exist only to compute the volume denominator and the 200-day MA facts.
- **History floor.** `tt_core` and `tt_early` already require a valid 200-day MA, so every pre-filtered ticker-day has at least 200 bars. With fewer than 250, show what exists and say so in the facts (`bars_shown`).
- **Prices.** Every O/H/L/C is divided by `S = Close[first shown bar] / 100` and rounded to 1 decimal.
  - This removes the price level, which is a strong identifier (a $3,000 AMZN before its split, for example).
  - It also makes the payload **invariant to any later split**: split adjustment multiplies all bars up to d by one constant, and the rescaling cancels it. The hash of day d therefore cannot change because of a split after d.
- **Volume.** Each volume is divided by ONE denominator: the mean volume of the 50 bars ending at d. It is rounded to 1 decimal.
  - A single denominator keeps the volume dry-up across the base visible, as a chart's volume pane does. A per-bar rolling ratio would normalise the dry-up away.
  - The decision bar's value equals the panel's `vol_ratio`, which `check_breakout` also uses (window includes today).
- **No identity.** No ticker, no company, no dates, no weekdays, no calendar gaps. Rows are ordered oldest to newest, and the prompt says "row k = bar k; the last row is the decision bar".
- **No weekly block by default.** Weekly aggregation needs real calendar weeks, and the daily bars carry the same information. An optional variant computes 5-bar blocks from bar indices only (no calendar), so no date information can enter.

### 3.2 The facts block

All facts are computed from the same bars and the panel on day d. They are expressed in rescaled units or percentages, never in dollars or dates.

| Fact | Source | Why |
|---|---|---|
| `pct_below_52w_high` | Close vs 252-bar max High | Trend template tt_6; context beyond the window |
| `pct_above_52w_low` | Close vs 252-bar min Low | tt_5 |
| `rs_percentile` | panel `rs_pct` (integer) | Minervini reads the RS line (see the cache note below) |
| `latest_pullback_depth_pct` | panel `pullback_depth` | Depth of the current contraction |
| `bars_since_local_high` | panel `days_since_high` | Base age |
| `close_vs_ma50 / ma150 / ma200` (%) | panel SMAs | Stage-2 check without drawing MAs |
| `ma200_slope_20bars` (%) | panel | tt_3 |
| `atr14_pct` | panel `atr14_pct` | Volatility, which affects the plausible stop |
| `decision_bar_volume_multiple` | as §3.1 | Breakout volume |
| `bars_shown` | 200..250 | Short-history flag |

**Cache note.** `rs_pct` is computed across the panel, so the same ticker-day has a different RS on `US_idx` than on `US_1500`. Including it exactly makes F0 and F1 windows cache-distinct even when the bars are identical.
- Within one panel it does not matter: the strict set is a subset of the `rank_only` set, so running F2 covers F1 for free.
- Recommendation: send RS as a coarse bucket (70-79, 80-89, 90-94, 95-99). Then windows from the two panels are identical and share the cache, and the bucket also leaks less.

**Deliberately NOT sent:**
- the mechanical VCP verdict or its reason, so the judge stays independent and the disagreement can be measured;
- fundamentals;
- catalysts and news;
- the market regime;
- anything after d.

### 3.3 Text or image: tokens per judgement

The two tokenizer families differ. gpt-oss (o200k-style) chunks digits up to three per token. Gemini-family tokenizers split every digit into its own token.

The figures below are **estimates**. Step 1 of the pilot confirms them with the providers' token counters on 20 real payloads, before any budget is set.

| Encoding | Content | Input tokens, gpt-oss | Input tokens, Gemini | Notes |
|---|---|---|---|---|
| **A: text, full OHLCV** | 250 x `o,h,l,c,v` + facts (~150) + rubric/schema (~900) | ~6,500 | ~8,700 | Most faithful; Open matters only for gaps |
| **B: text, HLCV (default)** | 250 x `h,l,c,v` at 1 decimal + facts + rubric | ~5,000 | ~6,500 | Gaps stay visible from prior close vs Low; exact numbers for the pivot |
| **C: image + numeric tail** | one PNG (candles + volume + MA50/150/200, ~1024x640) + last 20 bars as B + facts + rubric | n/a (text-only models) | ~1,800-2,600 (image ~280-1,120 by resolution setting) | Chart-native; pivot read from pixels is imprecise; Gemini only |

Output is about 100 JSON tokens, plus hidden reasoning tokens that are billed as output:
- gpt-oss at `reasoning_effort="low"`: about 300-800;
- Gemini at the minimum thinking setting: about 0-300.

Planning figures: **700 output tokens for gpt-oss and 300 for Gemini.**

**Recommendation: Encoding B is the primary.**
- It keeps the exact numbers the pivot and stop must be expressed in.
- It runs on all three configured providers.
- Its hash is exact, and it costs about $0.0006-0.0008 per call.

Encoding C is a pre-registered secondary arm, compared on the calibration set only. An image adds rendering code (matplotlib, fixed style and size, no axis labels, no title) and makes the payload hash depend on renderer versions. If C is kept, the hash must cover the rendered PNG bytes, and the renderer version must be pinned.

### 3.4 Prompt skeleton (prompt version `judge-v0.1`)

```
SYSTEM: You are a chart reader applying Mark Minervini's SEPA / VCP rules to ONE anonymised daily chart.
Judge ONLY from the numbers below. You do not know the company, the dates, or what happened later;
do not guess them. Definitions you must use:
 - base: a sideways consolidation after a prior advance, 3-65 weeks, correction <= 60% (ideally <= 35%);
 - VCP: 2-6 successively tighter contractions, volume drying up into the right side; other valid
   types: flat base (<= 15% deep), cup-with-handle, high tight flag, double bottom, ascending base;
 - pivot: the high of the final, tightest contraction (flat base: the base high);
 - stop_level: a logical level under the final contraction low, in the same units.
Units: prices rescaled so that the first row's close = 100.0; volume = multiple of the 50-bar average
volume ending at the LAST row. Rows are bars 0..N-1, oldest first; the LAST row is the decision bar.
Answer with JSON only, matching the schema. No text outside the JSON.
USER:
FACTS: pct_below_52w_high=3.1; pct_above_52w_low=64.0; rs_bucket=90-94; latest_pullback_depth_pct=12.4;
bars_since_local_high=38; close_vs_ma50=+4.2; close_vs_ma150=+14.8; close_vs_ma200=+21.5;
ma200_slope_20bars=+3.0; atr14_pct=2.8; decision_bar_volume_multiple=1.9; bars_shown=250
BARS (h,l,c,v):
101.4,99.2,100.0,0.8
...
131.9,127.5,131.6,1.9
```

---

## 4. Output, point-in-time guarantees, throughput and cost

### 4.1 The output schema (JSON only, strict)

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["is_valid_base", "base_type", "pivot_price", "stop_level", "confidence", "reason"],
  "properties": {
    "is_valid_base": {"type": "boolean"},
    "base_type": {"enum": ["vcp", "flat_base", "cup_with_handle", "high_tight_flag", "double_bottom",
                           "ascending_base", "none"]},
    "pivot_price": {"type": ["number", "null"]},
    "stop_level":  {"type": ["number", "null"]},
    "confidence":  {"type": "number", "minimum": 0, "maximum": 1},
    "reason":      {"type": "string", "maxLength": 160}
  }
}
```

Send it as the provider's structured-output schema:
- Gemini: `response_schema` / `response_mime_type="application/json"`;
- Groq and Cerebras: `response_format={"type": "json_schema", ...}`, where the model supports it; otherwise `json_object` plus the local validator.

**Local validation.** The scorer's `_parse` is too lenient for numbers, so validation runs locally. Each rule failure is a named reason, never a silent default.

| Rule | On failure |
|---|---|
| Parses, has exactly the six keys, and each type matches | `JUDGE_UNPARSEABLE` |
| `is_valid_base = false` implies `base_type = "none"` and null levels | normalised; logged |
| `is_valid_base = true` implies non-null pivot and stop, and `stop < pivot` | `JUDGE_INVALID_LEVELS` |
| `min(Low) <= pivot <= 1.10 * max(High)` over the shown bars | `JUDGE_INVALID_LEVELS` |
| `(pivot - stop) / pivot` between 1% and 35% | `JUDGE_INVALID_LEVELS` |

- An invalid answer gets **one** repair retry, which re-sends the validator's message.
- If the retry also fails, the row is `NOT_JUDGED`. It is written to a separate failures table and **never cached as a verdict** (the same rule as scorer.py line 147).

**Mapping to the engine's row** (same columns as `SIG.vcp_table`):
- `pivot = pivot_price * S`
- `price_ready_min = is_valid_base AND confidence >= 0.5 AND check_breakout(df, df.Volume, pivot, volume_multiplier=1.2)[0]`
- `volume_ratio` comes from `check_breakout`'s detail.
- The judge fields are kept as extra columns: `judge_valid, judge_base_type, judge_confidence, judge_stop (x S), judge_reason, window_hash, judge_key`.
- `reason` becomes one of `PRICE_READY`, `JUDGE_NO_BASE`, `JUDGE_LOW_CONFIDENCE`, `AWAITING_BREAKOUT`, `JUDGE_INVALID_LEVELS` or `NOT_JUDGED`. `write_receipts()` then works unchanged.

Keeping the breakout mechanical means the arm changes exactly one thing against `vcp` and `high50`: the base reading and pivot location.

### 4.2 Point-in-time guarantees

| Guarantee | Mechanism | Test |
|---|---|---|
| The window ends at the decision close | `df.loc[:d]` then trim, as `_vcp_worker` does | Mutating or deleting any bar after d leaves the payload bytes unchanged |
| No future bars in the facts | Facts come only from panel rows at d; the panel columns are already tested for this (`test_new_panel_columns_do_not_change_when_the_future_is_removed`) | Same truncation test on the facts block |
| No later split can change the input | Rescaling to 100 plus a single volume denominator | A synthetic 2:1 split after d gives the same hash |
| No news, fundamentals, ticker or date | The payload builder takes only bars and the facts dict | Regex test: no universe ticker, no `19xx`/`20xx`, no month names, no `$` |
| The fill is on the next open | Unchanged engine: signals at close d, fill at open d+1 | Existing engine tests |
| Deterministic and reproducible | Cache key `sha256(payload_bytes \| provider \| model_id \| prompt_version \| schema_version \| decoding params)`; backtests in `judge_cache_only=True` | Same key across processes and hash seeds; two backtests byte-identical |
| Pinned model | One provider and one exact model id per arm. **No failover to another model inside an arm.** A model switch is a cache miss, and a cache miss in `cache_only` mode refuses the run. The provider's returned model or version string is stored per record and must equal the pin. | A fake provider returning another version string triggers a hard error |
| Temperature 0 | `temperature=0`, fixed `seed` where supported, fixed `max_tokens`, fixed reasoning or thinking level. **Note:** Google advises the default temperature for Gemini 3.x models, so check T=0 quality on the calibration set. | A stability probe (below) measures what is left |

**Temperature 0 is not bit-deterministic.** Batching and mixture-of-experts routing on the provider side still vary. The **cache is the guarantee**: the first valid answer is frozen, and every re-run reads it.

A **stability probe** measures how much nondeterminism is left: 200 windows, sent 3 times each, with the cache bypassed and the results stored in a probe namespace. Report:
- the flip rate of `is_valid_base`;
- the dispersion of the pivot.

**Gate:** if the flip rate is above 10%, either use a majority of 3 (three times the cost) or change models before any full run.

The cache must be backed up with the results, because providers retire models; after that, the cache is the only way to reproduce a run. This argues for an **open-weights model** (gpt-oss-20b or -120b, Apache-2.0). Its exact weights can be self-hosted later, so a forward paper test cannot be ended by a deprecation.

### 4.3 Providers already in the project

- **Variable names in `.env`** (names only; values not read or printed): `GOOGLE_AI_STUDIO_KEY`, `GROQ_API_KEY`, `CEREBRAS_API_KEY`.
- **Used in code** (`kashif_engine/catalyst/scorer.py`, `catalyst_check.py`, `build_catalyst_table.py`):
  - Groq, `openai/gpt-oss-20b`, through the `openai` client at `https://api.groq.com/openai/v1`;
  - Google, `gemini-3.1-flash-lite`, through `google.genai`.
  - Both use `temperature=0` (Groq) and a 4-attempt, 429/503-classified retry loop.
- **Cerebras** has a key but no code path. It is OpenAI-compatible and hosts gpt-oss models, and would be the fastest serving option. Groq and Cerebras serving "the same" gpt-oss must still be treated as **different model ids**, since the inference stacks differ.
- **Claude subagents** (the `prepare_agent_batches.py` pattern) are free at the margin, but they cannot pin a model id or set temperature, and they cannot run 13k-60k judgements. Use them only to produce **reference labels** on the ~300-window calibration set, never for a backtest arm.
- **Measured free-tier capacity.** In the catalyst tune run (`kashif_data/catalyst/catalyst_summary_tune.json`), both providers were exhausted after **202 model calls** ("free-tier quota exhausted on every provider"; 161 filings NOT_SCORED). The project spend ledger holds 230 calls with 269,876 input tokens in total. At 5-6.5k tokens per judgement, that is **about 40-55 judgements per day**. A paid tier or a Batch API is required.

### 4.4 Calls per window

- **One call per pre-filtered (ticker, day).** No multi-turn, no tools.
- **Optional majority of 3** only if the stability probe fails.
- **At most one repair retry**; the pilot measures how often it happens.
- **Tuning costs nothing.** `rs_threshold`, `breakout_volume` and `judge_min_confidence` are run-time filters over the judged set.
- **What costs new calls:** a new prompt version, a new model, a new universe or panel, or new bars (a price correction changes the hash, which is correct).
- **Cross-arm reuse.** The content-addressed cache reuses every identical window across arms: F1 is a subset of F2 on the same panel, and with an RS bucket F0 and F1 also share.
- **An optional cheap pre-screen.** A proper pivot breakout implies that `close_d` is above the closes of the final contraction. So a mechanical necessary condition such as `close_d > max(Close[d-5..d-1])` could cut calls a lot.
  - It is admissible only if it keeps at least 99% of the VCP-accepted rows and **all** of Minervini's in-window disclosed buys that reach entry timing.
  - Measure it in Stage 0; do not assume it.

### 4.5 Cost and time tables

Costs use the per-1M-token list prices in `scorer.PRICES`, which is what the spend ledger books:
- gpt-oss-20b: $0.075 in / $0.30 out;
- gemini-3.1-flash-lite: $0.10 in / $0.40 out.

**Verify these against the current price sheets before budgeting.** If the real Gemini list price is higher, scale its column linearly.

Planning values, Encoding B, one call per window:
- Groq gpt-oss-20b: 5,000 in + 700 out, about $0.00059 per call;
- Gemini flash-lite: 6,500 in + 300 out, about $0.00077 per call.

| Workload | Calls | Groq gpt-oss-20b | Gemini 3.1 flash-lite | Via Batch API (~50%) |
|---|---|---|---|---|
| Stage 0 + probes (calibration ~300, leakage ~600, stability 600, pilot ~500) | ~2,000 | $1.2 | $1.5 | $0.6-0.8 |
| F0-like, S&P 400/600 strict, 2017-21 | 8,595 | $5.1 | $6.6 | $2.6-3.3 |
| F1-like, S&P 1500 strict, 2017-21 | 13,681 | $8.1 | $10.5 | $4.0-5.3 |
| F1-like, S&P 1500 strict, 2022-26 | 12,477 | $7.4 | $9.6 | $3.7-4.8 |
| F2-like, S&P 1500 rank_only, 2017-21 (covers F1) | 60,486 | $35.7 | $46.6 | $18-23 |
| F2-like, S&P 1500 rank_only, 2022-26 (covers F1) | 55,368 | $32.7 | $42.6 | $16-21 |
| All S&P 1500 work, both windows (unique windows) | ~115,900 | ~$68 | ~$89 | ~$34-45 |
| Majority of 3 (only if needed) | x3 | x3 | x3 | x3 |
| Encoding A instead of B | same | x1.2 | x1.3 | |
| Encoding C (image, Gemini only) | same | n/a | x0.45 | |

Wall-clock time for Encoding B, from calls per minute. The paid rows are **assumptions** that depend on the account tier; check the provider's limits page for the chosen model.

| Throughput regime | Calls/min | 2,000 (Stage 0) | 13k (strict window) | 60k (rank_only window) |
|---|---|---|---|---|
| Free tiers (measured: ~200 short calls/day across both) | ~40-55/day | ~40-50 days | ~250-340 days | years: not viable |
| Paid, token-per-minute bound (~250k TPM at ~5-6.5k tokens/call) | ~40-50 | ~45 min | ~4.5-5.5 h | ~20-25 h |
| Paid, higher tier (~200 calls/min, 16-32 concurrent) | ~200 | ~10 min | ~65 min | ~5 h |
| Batch API (JSONL job, ~50% price) | n/a | minutes to hours (SLA up to 24 h) | same, one job | same, 2-4 jobs |

**The budget hard-stop** is its own ledger: `kashif_data/chart_judge/spend.jsonl`.
- It must NOT share `kashif_data/llm_spend.jsonl`. `scorer._spent()` sums that whole file, so shared use would charge the judge against the catalyst's $10 cap and the other way round.
- Before each call, `reserve(est_max_cost)` requires `spent + in_flight + est_max_cost <= budget`. The estimate is `ceil(len(payload)/3)` input tokens plus `max_tokens` output, at list price.
  - scorer.py checks only `spent`, which is enough when calls run in sequence. With concurrency, an in-flight reservation is needed.
- **Proposed caps:** $5 for Stage 0 and the probes; $15 per strict window; $60 per `rank_only` window. Raising a cap is an explicit CLI flag, logged into the run's provenance.
- **Order of work.** Work is processed in hash order, which is effectively random. A budget stop then leaves a random sample, not the first N days. A backtest is refused unless coverage is 100%; a partial set is reported only as a sample.

### 4.6 Resumability (the app-restart failure)

The failure mode is on record: in experiment 2, "An app restart killed the process at about 1,050/1,188" (`backtest_results/experiment2/PREREGISTRATION.md` line 198). The design:

1. **Idempotent work list.** `manifest_<arm>_<window>.parquet` holds `(ticker, date, window_hash, S, key)`. It is a deterministic function of the pre-filter and the bars. The to-do list is always recomputed as the manifest minus the keys in the cache, so no progress state can go stale.
2. **Crash-safe cache.** A SQLite database (`kashif_data/chart_judge/cache.sqlite`, WAL mode) commits one row per answer.
   - Columns: `key PK, window_hash, provider, model_pinned, model_returned, prompt_version, schema_version, raw_response, parsed_json, tokens_in, tokens_out, notional_usd, ts`.
   - One file for about 120k rows, roughly 100 MB. That is better than 120k small JSON files on NTFS.
   - Payloads are NOT stored; they can be rebuilt from bars. A 1% sample is stored for audit.
   - A crash loses only the calls in flight.
3. **Single writer.** A lock file is created with `O_CREAT|O_EXCL` and holds the PID (the pattern of `run_minervini_fix_tests.py`). A second runner refuses to start while the PID is alive.
4. **Detached launch.** The runner is started outside the Claude app's process tree, for example `Start-Process pythonw ... -WindowStyle Hidden` or a Task Scheduler entry.
   - It writes to a log file and a heartbeat JSON (done, to-do, spend, calls per minute, last error).
   - A `STOP` sentinel file makes it drain in-flight calls and exit cleanly.
5. **Batch API reconciliation.** A batch job id is appended to `batches.jsonl` **immediately after creation**. On restart, pending batches are polled and downloaded before anything is resubmitted, so nothing is billed twice. Windows inside a pending batch are excluded from the to-do list.
6. **Rate limits.** Reuse scorer.py's classification:
   - a 429 per-minute limit gets back-off;
   - a 429 per-day limit marks the provider exhausted, and the **runner pauses**. It does not fail over, because a model is pinned per arm;
   - a 503 gets back-off and never counts as exhaustion.
   - A token-bucket limiter is sized from the provider's RPM and TPM.

---

## 5. Leakage probe mode

**Purpose:** find out whether the anonymised payload still lets the model recognise the instance. If it does, the judge's verdicts can carry knowledge of what happened next.

**Mode `probe`:**
- same payload builder, same model and decoding;
- a different prompt version (`probe-v0.1`), so the results sit in a separate cache namespace;
- the probe asks the model to guess, as JSON: `ticker` (free text), `gics_sector` (one of 11), `year` (2005-2026), and `p_up20_next60` (the probability that the close 60 bars later is at least 20% higher).

**Sample** (about 600 windows, stratified; reported per stratum):

| Stratum | n | Why |
|---|---|---|
| Random pre-filtered ticker-days, 2017-21 and 2022-26 | 300 | The base rate on the actual workload |
| Minervini's disclosed buys at his dates (46 BUY rows in `minervini_disclosed_trades.csv`, those with bars) | ~40 | Charts discussed in public (USIC 2021 lists); the calibration set itself |
| Famous large-cap runs (for example the top-50 names by market cap at their largest 12-month gains) | 100 | Most likely to be memorised |
| Windows after the model's training cutoff (check the cutoff; gpt-oss is reported as mid-2024) | 100+ | Cannot be memorised: the control |
| Positive control: the same 60 windows **de-anonymised** (real dates and price levels) | 60 | Shows how much power the probe has; if even these are not recognised, a null result on ticker says little |

**Metrics, with pre-registered thresholds:**

| Probe | Metric | Baseline | Flag as leakage if |
|---|---|---|---|
| Ticker | Top-1 exact hit rate | ~1/1,500 | above 1% overall, or any hit on a Minervini buy |
| Sector | Accuracy | The largest sector's share in the sample | above base rate + 5pp (one-sided binomial p < 0.01) |
| Year | Exact hit rate and mean absolute error | Modal-year share and constant-median MAE | above base + 5pp. Report windows containing the Feb-Mar 2020 crash separately: that shape alone reveals the year |
| Outcome | AUC of `p_up20_next60` against the realised result, pre-cutoff vs post-cutoff | The same AUC gap for a mechanical logistic on RS and distance to the high | (pre - post AUC gap of the model) - (the same gap of the baseline) > 0.05 |

**The outcome probe is the most direct test.** A model that recognises charts forecasts well before its cutoff and poorly after it; the baseline shows how much of that gap the market regime alone explains.

**Consequences:**
- If any flag fires, the judge's historical backtests are labelled **leakage-suspect**. Only post-cutoff periods and forward paper trading can count as evidence.
- Mitigations to re-test under a new prompt version:
  - RS bucketing (already recommended);
  - a shorter window (150 bars);
  - dropping the Open;
  - small price noise of ±0.1% per bar (hash taken after the noise, with a seed fixed per window hash).

**Cost:** ~660 calls, about $0.4-0.6.

---

## 6. Integration

### 6.1 `module.py` (line numbers as of `e66f100`)

| Where | Change |
|---|---|
| L59 `STRUCTURAL_DEFAULTS` | **Unchanged.** Adding keys there would make every existing bundle fail the `built != self._structural()` check at L325-328. |
| L138-144 params | `entry_mode` gains `"ai_judge"`. New params: `judge_provider`, `judge_model` (exact pinned id), `judge_prompt_version`, `judge_encoding` (`"B"`), `judge_min_confidence` (0.6 default; grid-loosest 0.5), `judge_stop` (`"engine"` default, or `"judge"`), `judge_cache_only` (True). |
| L154 validation | Accept `"ai_judge"`. Reject an unknown provider or encoding. Reject a `judge_min_confidence` below the grid-loosest 0.5 (mirrors L167-169). |
| L187-230 | **Refactor:** extract the pre-filter (L198-229) into `Strategy.prefilter(universe, start, end) -> pre_long`, called by `prepare()` and by the runner. This is behaviour-neutral; `test_defaults_reproduce_experiment2_exactly` must stay green. |
| L231-235 | `elif self.p["entry_mode"] == "ai_judge": vcp = SIG.judge_table(pre_long[["ticker","date"]], GRID_LOOSEST["breakout_volume"], judge_cfg, cache_only=..., log=log)` |
| L256 `_structural()` | `d = {k: self.p[k] for k in STRUCTURAL_DEFAULTS}`, plus the `judge_provider`, `judge_model`, `judge_prompt_version` and `judge_encoding` keys when `entry_mode == "ai_judge"`, plus `judge_schema: SCHEMA_VERSION`. Old bundles and old arms are unaffected, and a bundle built with another model or prompt is refused at L326. |
| L380 `candidates()` | Under `ai_judge`: `g = g[g["judge_confidence"] >= self.p["judge_min_confidence"]]`. |
| L392-399 | Extend the NaN rule at L393 to `ai_judge` (`vcp_quality` is NaN). The reason becomes `"AI_JUDGE_BREAKOUT"`. Pre-register `rank_by="rs"` for the first arm, with confidence only as a threshold, so ranking does not change at the same time as the entry. |
| L401-405 receipts | Add `judge_base_type`, `judge_confidence`, `judge_reason` and `window_hash` to the candidate, so they land in `candidates.csv`. |
| L455-460 `on_entry_filled` | If `judge_stop == "judge"`: `sd = (entry - judge_stop_real) / entry`, clamped to [4%, 10%] like the pivot stop. Separate arm only. |
| L298-309 `to_bundle` | `self.vcp` already carries the judge columns. Add `"judge": {provider, model, prompt_version, schema_version, encoding, n_windows, n_judged, n_not_judged, verdicts_sha256}` to the bundle. `verdicts_sha256` is a hash over the sorted `(key, parsed_json)` rows used, so the auditor can prove which answers a run used. |
| L187-190 window guard | Already in `prepare()`. **The runner must call `X2.assert_window_allowed` too**, because judging validation-window days produces candidates there. |

### 6.2 New code

| File | Content |
|---|---|
| `kashif_engine/chart_judge/anonymise.py` | `build_payload(df_upto_d, panel_row, encoding) -> (text, S)`, facts, rounding, `PAYLOAD_VERSION` |
| `kashif_engine/chart_judge/prompt.py` | Rubric text, JSON schema, `PROMPT_VERSION`, `SCHEMA_VERSION`, probe prompt |
| `kashif_engine/chart_judge/providers.py` | Groq, Gemini and Cerebras adapters (one call, structured output, usage, returned model string); keys via `dotenv_values`, never logged |
| `kashif_engine/chart_judge/cache.py` | SQLite cache, key function, atomic put, namespace (judge, probe or stability) |
| `kashif_engine/chart_judge/budget.py` | Separate ledger, reservation-based hard stop, `BudgetExceeded` |
| `kashif_engine/chart_judge/validate.py` | The strict parser and level rules of §4.1 |
| `kashif_engine/strategies/minervini_sepa_v1/signals.py` | `judge_table()` next to `vcp_table()`. Table-level parquet cache keyed like L114-117 (`CODE_VERSION`, `"judge"`, model, prompt, schema, encoding, vmin, pre list, `price_fp`). Rows come from the SQLite cache. Raises in `cache_only` mode when coverage is below 100%, listing what is missing. |
| `kashif_engine/scripts/run_chart_judge.py` | Detached, resumable precompute: manifest, to-do, async pool, limiter, budget, heartbeat, `STOP` file, Batch API mode with reconciliation |
| `kashif_engine/scripts/run_judge_probes.py` | Stage 0 calibration, the leakage probe, the stability probe; writes a markdown and JSON report |

### 6.3 Bundle and fingerprint implications

- `data_fp` (`fingerprint.quick()`) already refuses a bundle built on other prices, splits, breaks or store. That is enough, because any bar change also changes the window hash and so the cache key.
- Judge identity is structural (§6.1), so a bundle cannot be used under another model or prompt.
- `fingerprint.content()`, used by the validation runner, should gain `judge_cache_rows_sha` for the rows a run used. The full SQLite file is not hashed, because it is append-only and grows.
- The cache database and the manifest must be backed up with the run artifacts. They are the only way to reproduce a run after the model is retired.

### 6.4 Tests (`kashif_engine/tests/test_chart_judge.py`, fake provider, no network)

1. **Anonymiser:** first close = 100.0; the last row is the decision bar; 250 rows; the volume denominator is correct; no ticker, year, month or `$` tokens (regex over the full universe list).
2. **Point in time:** the payload from the full frame equals the payload from `df.loc[:d]`; mutating bars after d leaves the hash unchanged; a synthetic split after d leaves the hash unchanged.
3. **Cache key:** stable across processes and `PYTHONHASHSEED` values; changes with model, prompt, schema, encoding or decoding; identical payloads from different tickers share a key.
4. **Validator:** the good case, plus each of the §4.1 failure rules; NOT_JUDGED is never cached; the round trip `pivot * S` works.
5. **Budget:** a fake provider with a fixed cost stops before the cap under 16 concurrent workers; the ledger sum equals the cache sum.
6. **Resumability:** kill the runner after N answers, restart, and check that the total provider calls equal the number of unique windows. Also: a pending batch is never resubmitted.
7. **Pinning:** a returned-model mismatch raises; no failover inside an arm.
8. **Engine integration** (the `patched` fixture pattern of `test_exp3_switches.py`):
   - `ai_judge` changes only the entry gate, and the stop anchors at the judge's pivot;
   - a bundle records the judge structural keys and refuses a strategy with another model;
   - **existing `vcp` and `high50` bundles still load**;
   - `cache_only` with a missing window raises.
9. **Defaults unchanged:** `test_defaults_reproduce_experiment2_exactly` and the rest of the current suite stay green.
10. **Opt-in live smoke test** (skipped without a key): 5 windows, schema-valid, cost below $0.01.

---

## 7. Effort estimate (engineer-hours)

| Piece | Hours | Notes |
|---|---|---|
| Anonymiser + facts + Encoding B (+ A) | 4-6 | Pure functions; most of the point-in-time tests live here |
| Encoding C renderer (optional) | +3-4 | Only if the image arm is kept |
| Prompt, schema, validator, rescaling back | 3-4 | Plus prompt freeze and review |
| Provider adapters (Groq, Gemini, Cerebras) with structured output and usage | 5-7 | Reuses scorer.py's retry classification |
| SQLite cache + key + namespaces | 3-4 | |
| Budget ledger with reservations | 2-3 | |
| Resumable detached runner (manifest, pool, limiter, heartbeat, STOP, lock) | 6-8 | |
| Batch API mode + reconciliation | 4-6 | Optional; halves the cost of full runs |
| `prefilter()` refactor + `judge_table()` + `module.py` switches + receipts + bundle provenance | 5-7 | |
| Test suite (§6.4) | 7-9 | |
| Calibration set assembly (Minervini buys + VCP-accepted + VCP-rejected + random) and reference labels | 4-6 | Claude-agent or human labels, blind to outcome |
| Leakage probe + stability probe + report script | 5-7 | |
| Pilot run review, token-count confirmation, cost check | 3-4 | Plus wall-clock time |
| Pre-registration text + code review round | 4-5 | |
| **Total to a first pre-registered full run** | **~55-75** | Without Encoding C and Batch API: ~45-60 |
| Wall-clock for full runs | 1-25 h per window | §4.5; attended time about 1 h per window |

---

## 8. Staged plan: cheapest decisive test first

Each stage passes only if its gate is met.

| Stage | What | Calls / $ | Gate to continue |
|---|---|---|---|
| 0: calibration | Judge Minervini's ~40 disclosed buys with bars (window at his date) and 300 pre-filtered ticker-days (100 VCP-accepted, 200 VCP-rejected). Measure the pre-screen of §4.4. | ~350 / ~$0.25 | The judge accepts his buys clearly more often than random pre-filtered days (for example, recall at least 50% and selectivity at most 30%). Otherwise stop: no signal worth buying. |
| 1: probes | Leakage probe (§5) and stability probe (§4.2) | ~1,260 / ~$0.9 | No leakage flag, or a documented and accepted post-cutoff-only plan; flip rate at most 10% |
| 2: prompt freeze | Freeze `judge-v0.1`, model, encoding and thresholds; pre-register the arm(s), the metrics and the kill rules, as in experiment 3 | 0 | Committed before any full run |
| 3: one strict window | Precompute F1-like 2022-26 (12,477 calls). Backtest in `cache_only`. Report overlap with the `vcp` and `high50` sets (Jaccard); a judge that reproduces high50 adds nothing. | ~$7-10 | Exploratory only: both windows are consumed |
| 4: forward | Run the same pinned judge daily in paper trading (~255 trend+RS names per day; after the pre-filter, measured at ~11 calls per day with strict fundamentals and ~50 with rank_only) | ~$0.01-0.04/day | The only confirmatory evidence |

---

## 9. Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| 1 | **Memorisation / hindsight.** The models were trained on the 2017-2025 market, public chart commentary, and Minervini's published trades. Market-wide shapes (the 2020 crash, the 2022 bear) reveal the year even after anonymisation. | High | Leakage probe with a post-cutoff control and a positive control; label historical results leakage-suspect when flagged; confirm forward only |
| 2 | **Both historical windows are consumed** (exp 1/2 and the fix tests). A prompt is a very flexible free parameter, and iterating it against 2017-2026 is fitting on test data. | High | Develop the prompt on the calibration set only; freeze and pre-register before Stage 3; treat historical runs as exploratory |
| 3 | **Nondeterminism** despite T=0; **model deprecation** | Medium | The cache is the guarantee; stability probe; open-weights model preferred; back up the cache with the artifacts |
| 4 | **Free tiers cannot carry the load** (measured ~200 short calls per day) | High (feasibility) | Paid key or Batch API, under an explicit owner-approved budget; hard stop |
| 5 | **Cost blow-up** (rank_only x votes x retries x reasoning tokens) | Medium | Per-stage caps; reservation-based hard stop; token counts confirmed on real payloads before budgeting |
| 6 | **Numeric-reading errors**: LLMs misread long number tables or invent a pivot | Medium | Level-validation rules; mechanical breakout check with the judge's pivot; calibration against reference labels; the image arm only as a comparison |
| 7 | **The judge collapses to "near highs = valid"** (a `high50` clone, and high50 was already tested) | Medium | Jaccard overlap with the high50 and VCP sets in every report; a Stage 0 selectivity gate |
| 8 | **Small, biased calibration set** (~40 buys, from the 2021-2026 picks that motivated the design) | Medium | Report confidence intervals; include VCP-accepted and random negatives; do not tune thresholds on the same buys used to decide go or no-go |
| 9 | **Job killed by an app restart** (it has happened) | Medium | Detached launch; idempotent to-do list; per-row commit; single-writer lock; batch-id reconciliation |
| 10 | **A partial coverage run quietly biases results** | Medium | Hash-order processing; a backtest refuses coverage below 100% |
| 11 | **Mixing models through failover** (scorer.py fails over from Groq to Gemini inside one run) | Medium | No failover inside an arm; the runner pauses instead; pin checked per record |
| 12 | **Window truncation** for bases longer than ~200 bars (4.9% of VCP-accepted rows) | Low | Facts block carries the 52-week context; report acceptance by base length |
| 13 | **Secrets:** keys could leak into logs or the cache | Low | `dotenv_values` in the adapters only; never log request headers or client objects; the cache stores responses, not requests |
| 14 | **Inherited:** survivorship (current index members), the fundamentals store's small revision-date issue | Known | Stated in every report, as in FIX_TESTS_RESULT.md |

---

## 10. Decisions needed from the lead or owner

1. **Budget approval and a paid key.** Stages 0-1 cost under $2. One strict window costs about $10 at the project's list prices; all S&P 1500 work costs about $70-90, or half via a Batch API.
2. **Model choice.** Recommended: an open-weights gpt-oss (20b, or 120b for about 2x cost) on one pinned provider. The alternative is Gemini flash-lite, which is cheap, supports images and is closed.
3. **Encoding.** B (text HLCV) as primary; C (image) only as a calibration-set comparison.
4. **RS in the payload.** A bucket (recommended, enables F0/F1 cache sharing) or the exact percentile.
5. **Stop.** Engine stop in the primary arm; judge stop as a separate arm or not at all.
6. **Stage 0's gate numbers**, written down before it runs.
