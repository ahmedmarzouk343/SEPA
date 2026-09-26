# Clean windows and a leakage probe for AI chart judgment

Research only. No model was called. Sources were read on 2026-09-26/27. Our price data ends on 2026-09-24.

**Question.** If an LLM judges anonymised charts, which of our data can it be tested on without already "knowing" what happened next? How would we measure how much it knows anyway?

---

## 1. Documented training cutoffs

"Cutoff" below means the **latest** date the vendor gives. Leakage is bounded by the newest data a model saw, not by the date through which its knowledge is "reliable".

| Model (where we'd call it) | Vision input | Documented cutoff | Source |
|---|---|---|---|
| **Claude Haiku 4.5** (`claude-haiku-4-5-20251001`) | yes | training data **Jul 2025**; reliable knowledge Feb 2025 | [Anthropic models overview](https://platform.claude.com/docs/en/models/overview) |
| **Claude Sonnet 5** (`claude-sonnet-5`) | yes | training data **Jan 2026**; reliable Jan 2026 | same |
| **Claude Opus 5.5 / Fable 5.1** | yes | training data **Jun 2026**; reliable Jun 2026 | same |
| **Gemini 3.6 Flash** (`gemini-3.6-flash`) | yes | "**March 2026** – users can expect updated information for some domains while in others ... limited to **January 2025**" | [DeepMind model card](https://deepmind.google/models/model-cards/gemini-3-6-flash/) (21 Jul 2026) |
| **Gemini 3.7 Flash / 3.8 Flash** | yes | same tiered wording: Mar 2026 / Jan 2025 | [3.7 card](https://deepmind.google/models/model-cards/gemini-3-7-flash/), [3.8 card](https://deepmind.google/models/model-cards/gemini-3-8-flash/) |
| **Gemini 3.5 Flash-Lite** | yes | same tiered wording: Mar 2026 / Jan 2025 | [3.5 Flash-Lite card](https://deepmind.google/models/model-cards/gemini-3-5-flash-lite/) |
| **Gemini 3.1 Pro**, **Gemini 3.1 Flash-Lite** (`gemini-3.1-flash-lite`, used by our scorer) | yes | **UNDOCUMENTED** in the current official card: it defers to Gemini 3 Pro, whose card (updated May 2026) states no cutoff. Third parties widely report **Jan 2025**. | [3.1 Pro card](https://deepmind.google/models/model-cards/gemini-3-1-pro/), [3.1 Flash-Lite card](https://deepmind.google/models/model-cards/gemini-3-1-flash-lite/), [Gemini 3 Pro card PDF](https://storage.googleapis.com/deepmind-media/Model-Cards/Gemini-3-Pro-Model-Card.pdf) |
| **Gemini 2.5 Flash / Pro** | yes | **UNDOCUMENTED** in the current official card (Dec 2025) and the Cloud page; historically reported **Jan 2025** | [2.5 Flash card PDF](https://storage.googleapis.com/deepmind-media/Model-Cards/Gemini-2-5-Flash-Model-Card.pdf), [AI Studio models page](https://ai.google.dev/gemini-api/docs/models) (lists no cutoffs) |
| **gpt-oss-20b / gpt-oss-120b** (Groq `openai/gpt-oss-*`; Cerebras `gpt-oss-120b`) | **no** (text only) | **Jun 2024** | [OpenAI gpt-oss model card](https://cdn.openai.com/pdf/419b6906-9da6-406c-a19d-1bb078ac7637/oai_gpt-oss_model_card.pdf), [OpenAI API model page](https://developers.openai.com/api/docs/models/gpt-oss-120b) |
| **Llama 3.3 70B** (Groq `llama-3.3-70b-versatile`) | **no** | "pretraining data has a cutoff of **December 2023**" | [Meta Llama 3.3 model card](https://github.com/meta-llama/llama-models/blob/main/models/llama3_3/MODEL_CARD.md) |
| **Llama 3.1 8B** (Groq `llama-3.1-8b-instant`) | **no** | **December 2023** | [Meta Llama 3.1 model card](https://github.com/meta-llama/llama-models/blob/main/models/llama3_1/MODEL_CARD.md) |
| **Qwen 3.8-27B** (Groq preview `qwen/qwen3.8-27b`; Cerebras `qwen-3.8-27b`) | yes (vision encoder) | **UNDOCUMENTED**: the release discloses no cutoff | [HF discussion "Knowledge cut-off date"](https://huggingface.co/Qwen/Qwen3.8-27B-FP8/discussions/8) |

Availability notes, as of the pages above:
- Cerebras now lists only `gpt-oss-120b` and `qwen-3.8-27b` ([Cerebras models](https://inference-docs.cerebras.ai/models/overview)), so **no Llama on Cerebras**.
- Groq production text models are Llama 3.1 8B, Llama 3.3 70B and gpt-oss-20b/120b ([Groq models](https://console.groq.com/docs/models)).
- **Claude Haiku 4.5 retires "not sooner than October 15, 2026"**, three weeks from now. Anything built on it must pin outputs or plan to migrate.
- Claude needs an Anthropic API key; the project `.env` currently holds Google, Groq and Cerebras keys.

Caveats on "documented":
1. **Gemini 3.x is explicitly tiered.** Whether US stock prices and news sit in the Mar-2026 "updated" domains or the Jan-2025 base is not stated. So for leakage we must assume **Mar 2026**. The probe in section 3 can show empirically that market knowledge actually stops earlier.
2. Declared cutoffs are not measurements. LLMLagBench ([arXiv 2511.12116](https://arxiv.org/abs/2511.12116)) exists precisely because stated and effective cutoffs differ. Hence a **+1-month safety buffer** below, and the probe.
3. Post-training (RLHF, tool-use data) and model refreshes under the same alias can add later knowledge. Pin dated snapshot IDs, and record the model ID with every output.

---

## 2. Clean evaluation windows in our data

Rules:
- A **decision date** is clean if it falls after the cutoff month plus a 1-month buffer.
- An outcome is **scoreable** only if its forward horizon (60 trading days here) ends by 2026-09-24.
- The 250-bar lookback *may* reach back before the cutoff. It holds no future information, only possible recognition of the stock (which the probe measures).
- Trading days are from the SPY calendar.

| Model | Cutoff used | Clean from | Clean trading days to 2026-09-24 | ≈ months | **Scoreable decision days (60-day horizon)** |
|---|---|---|---|---|---|
| Llama 3.1 8B / 3.3 70B | Dec 2023 | 2024-02-01 | 663 | 31.6 | ~603 (~29 mo) |
| gpt-oss-20b / 120b | Jun 2024 | 2024-08-01 | 538 | 25.6 | ~478 (~23 mo) |
| Gemini 2.5 / 3.1 Pro / 3.1 Flash-Lite (reported Jan 2025, undocumented) | Jan 2025 | 2025-03-01 | 394 | 18.8 | ~334 (~16 mo) |
| Claude Haiku 4.5 | Jul 2025 | 2025-09-01 | 268 | 12.8 | ~208 (~10 mo) |
| Claude Sonnet 5 | Jan 2026 | 2026-03-01 | 144 | 6.9 | ~84 (~4 mo) |
| Gemini 3.5 Flash-Lite, 3.6/3.7/3.8 Flash (later tier) | Mar 2026 | 2026-05-01 | 100 | 4.8 | ~40 (~2 mo) |
| Claude Opus 5.5 / Fable 5.1 | Jun 2026 | 2026-08-01 | 38 | 1.8 | **0**: nothing is scoreable yet |

**The tradeoff:** the only models with long clean windows (Llama 3.x, gpt-oss) are **text-only**, so they would have to read charts as numeric OHLCV text. Every vision-capable model with a documented cutoff has **≤ 13 months** of clean data, and ≤ 10 months scoreable at a 60-day horizon. That window is also a **single market regime** (late 2025 to 2026).

### Minervini's disclosed trades after each cutoff

Source: `backtest_results/experiment3/minervini_check/minervini_disclosed_trades.csv`. It has 114 rows: 46 BUY, 37 HOLD, 21 SELL and 10 DISCUSSED. BUY dates by year: 2021: 32, 2022: 1, 2024: 9, 2025: 4.

For rows dated only to a month or quarter, the row counts after the cutoff if the period *starts* after it.

| Model | BUY rows after cutoff + 1 mo | Of which stocks (ETFs excluded) | BUY+HOLD rows after cutoff + 1 mo |
|---|---|---|---|
| Llama 3.x (Dec 2023) | 12: APP, AXON, CCL, DVA, IBIT, IWN, LMB, MU, NMM, RNA, TATT, UBER | 10 | 32 |
| gpt-oss (Jun 2024) | 10: APP, AXON, CCL, DVA, IWN, LMB, NMM, RNA, TATT, UBER | 9 | 28 |
| Gemini, reported Jan 2025 tier | 4: CCL, IWN, TATT, UBER | 3 | 21 |
| Claude Haiku 4.5 (Jul 2025) | **0**. Without the buffer: 3 (CCL, IWN, UBER, all dated only "2025-08") | 0-2 | 12 |
| Claude Sonnet 5, Gemini 3.x later tier, Opus 5.5 | **0** | 0 | 12 / 12 / 0 |

The 12 BUY+HOLD rows that remain for the newer models are **all HOLDs from a single 2026-06-11 holdings snapshot**: ASML, FRST, KRYS, MAR, MATX, MNST, MS, PSMT, PSX, ROST, SMFG, VIK. Their entry dates are unknown and likely before the cutoff, so they aren't usable as entry-chart ground truth.

**Consequence:** "does the model pick what Minervini picked?" **cannot be tested cleanly on any vision model**. His 2021-2025 picks, and what happened to them, are public and pre-cutoff. Clean evaluation has to be **outcome-based**: forward returns of model-approved vs model-rejected setups on post-cutoff decision dates. Minervini's charts can serve only as pre-cutoff *calibration examples*, and only if the probe below passes.

---

## 3. Leakage probe (specification; not run)

**Purpose:**
- (a) Measure whether a model can recover identity, sector, date or future outcome from our anonymised chart format.
- (b) Estimate its **effective market-knowledge cutoff**, which the Gemini tiering and the LLMLagBench caveat make necessary.

Run the probe on each candidate model **before** any strategy work. Its result decides which data may be used for development.

### 3.1 Anonymisation, identical to the planned production format
- 250 daily bars, split- and dividend-adjusted. The bar index runs 1..250 with no dates, weekdays or holiday gaps.
- Price rescaled so that bar-1 close = 100 × U(0.8, 1.25). The random base removes price-level lookup. The exact factor is logged.
- Volume divided by its 250-bar median and rounded to 0.01. Share counts and dollar volume are never shown.
- **Image form:** candlesticks plus a volume panel, fixed style and size. The y-axis is in relative units, with no title, watermark or ticker.
- **Text form:** a CSV of `t,open,high,low,close,vol_rel` rounded to 0.1 (price) and 0.01 (volume), for the text-only models.
- The same windows go to every model, and each model gets the form it will use in production.

### 3.2 Samples (drawn from our cache: S&P 1500 current members, SPY/MDY/IJR; frozen by seed before any call)
| Set | n | Content | Role |
|---|---|---|---|
| **A: famous single-stock windows** | 40 | Windows ending at the peak, trough or breakout of widely covered moves that are in our cache and pre-cutoff for the model under test. Candidates: NVDA (2023-05 AI breakout, 2024-03 and 2024-06 peaks); TSLA 2020 run-up; MRNA 2020-21; ZM and PTON 2020 (if cached); SMCI 2024-03 peak; META 2022 low and 2023 recovery; NFLX 2022-04 gap-down; GME 2021-01 (if cached); CVNA 2022 crash / 2023 rebound; KRE / regional-bank names 2023-03; APP 2024. Keep only those present in the cache. | Does the model *recognise* famous stories? |
| **B: famous market-wide windows** | 20 | SPY / MDY / IJR (and 5-10 random S&P 1500 constituents) ending in: Aug-2015 selloff, Q4-2018 drawdown, Mar-2020 crash and Apr-2020 rebound, 2022 bear market, Oct-2023 low; plus Apr-2025 tariff drop if pre-cutoff for that model | Does it recognise *regimes*? |
| **C: ordinary pre-cutoff controls** | 40 | Random (ticker, end date) from the universe, pre-cutoff, excluding A/B tickers within ±1 year, matched to A on 250-bar volatility quintile | Baseline recognition of unremarkable charts |
| **D: post-cutoff dramatic controls** | 20 | Post-cutoff windows (end date ≥ cutoff + 1 mo) with moves as large as A's (top-5% absolute 60-day return); only possible for models with a clean window | Shows how much can be *inferred from shape alone* |
| **E: forward-outcome panel** | 200 pre + 200 post | Random (ticker, decision date) from the universe, pre- vs post-cutoff, matched on volatility quintile and 250-bar trend (SMA50 > SMA200 or not). Post-cutoff dates need 60 trading days of future data. | The key test: does the model predict the future better where it has seen the future? |

Models with no scoreable post-cutoff window (Opus 5.5 / Fable 5.1 today) can run A-C only. They **cannot** be cleared for any backtest until scoreable post-cutoff data exists.

### 3.3 Prompts
Each question is a separate call with a fresh context: no tools, no web, temperature 0 (or the lowest the API allows), and a fixed system prompt:

> You are shown an anonymised daily price-and-volume chart of one US-listed stock or ETF: 250 trading days, oldest first. Dates, ticker and price level have been removed on purpose. Answer only in the JSON format requested. If you cannot tell, you must still give your best guess together with a confidence.

- **Q-ID (sets A-D):** `{"ticker_guesses":[up to 5 tickers],"confidence":0-1}`, with the instruction "If you recognise the specific security, name it. Otherwise give your best guesses."
- **Q-YEAR (A-D):** `{"year_probs": {"2014":p,...,"2026":p}}`, probabilities summing to 1, for the year of bar 250.
- **Q-SECTOR (A, C, D; stocks only):** `{"sector_probs": {11 GICS sectors: p}}`.
- **Q-FWD (set E):** "Over the next 60 trading days after bar 250, will the close be more than 15% higher (UP), more than 15% lower (DOWN), or in between (FLAT)?" Answer as `{"probs":{"UP":p,"FLAT":p,"DOWN":p}}`. The ±15% band is set from the universe's historical 60-day return distribution so that each class has 25-45% base rate. Freeze the band before running.

Scoring is from the model's probabilities (log loss and top-1), never from free text. Refusals and "unknown" are scored as uniform probabilities.

### 3.4 Pass thresholds (pre-registered; a model is **cleared for pre-cutoff development data** only if all pass)
1. **Identity:** ticker top-1 ≤ 2/40 and top-5 ≤ 4/40 on set A, **and** not above set D's rate (one-sided Fisher p > 0.10). (C should be ~0; if C is not ~0, the anonymisation leaks and must be fixed first.)
2. **Year:** top-1 year accuracy on A+B ≤ 25%, and at most 10 percentage points above C's accuracy. Chance is ~8% (13 years).
3. **Sector:** top-1 on A at most 10 pp above C, both compared against the ~1/11 base plus the universe's sector frequencies.
4. **Forward outcome (decisive):** the Brier / log-loss skill on E-pre minus skill on E-post must have a 95% bootstrap CI whose lower bound is ≤ 0. In other words, it must **not** do significantly better where the future is in its training data. Also report accuracy per decision-date half-year. The half-year where pre-minus-post skill drops to ~0 is the **empirical market-knowledge cutoff**, and it replaces the documented one in section 2 if it is *later*.

**If a model fails 1-3 but passes 4:** it recognises charts but doesn't use outcome knowledge in this format. Pre-cutoff data may then be used for prompt design only, and never for performance claims.
**If it fails 4:** only post-cutoff data may be used with it, for anything.

Cost: about 120 × 3 + 400 = ~760 calls per model. On free tiers, spread them over days.
Outputs to freeze: the window list with seeds, the rendered images and CSVs with SHA-256 hashes, every raw response, and the model ID and timestamp.

### 3.5 What the probe cannot detect
- **Regime priors.** A model that "knows" 2020-21 was a momentum boom may favour breakout-shaped charts from that era even without recognising them. That lifts pre-cutoff results without failing Q-ID or Q-YEAR. Only E catches it, and only on average.
- **Knowledge of Minervini's own picks and books.** A model can learn "what a Minervini chart looks like" from his published examples. That's a legitimate skill, not leakage, but his published examples overlap the calibration set.
- **Small n.** 40-window sets detect only gross recognition. E at 200/200 detects a skill gap of roughly 0.08-0.10 in accuracy.

---

## My view

**Is it worth it?** Only as a narrow, pre-registered test, and only with realistic expectations.
- The probe is cheap (hundreds of calls) and worth running regardless. It turns "the model might remember" into a number, and it can reveal that Gemini's effective market cutoff is Jan 2025, not Mar 2026. That would give a vision model about 16 scoreable months instead of about 2.
- The approach itself is sound: an LLM as a *filter on setups the mechanical screen already found*, judged on post-cutoff outcomes. Our experiment-3 evidence says chart reading is exactly where the mechanical system and Minervini diverge.

**Biggest risk: too little clean data, not memorisation.**
- For the vision models we'd actually want, the scoreable post-cutoff window is about 2-10 months (about 16 at best, if the Jan-2025 Gemini tier holds), all in one market regime.
- A result there has huge sampling error. After three experiments that each failed out of sample, there'll be strong pressure to "also look at 2021", which is exactly where leakage and regime priors live and where Minervini's own picks come from.
- The honest path is to run the probe, then evaluate only on clean post-cutoff dates, and treat **forward paper trading from now on** as the real test. A clean backtest window this short can falsify the idea but not confirm it.

Secondary risks:
- **Model churn.** Haiku 4.5 retires as soon as 2026-10-15. Gemini aliases update, so every result must name a pinned snapshot, and a replacement model needs its own probe and clean window.
- **The target may not be charts alone.** Minervini's discretion also uses fundamentals, news and market context. A perfect chart-reader might still not reproduce his results.
