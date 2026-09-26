# Can an AI judge read Minervini charts? Evidence memo

Researcher memo for experiment 4. Web research done on 2026-09-27. No backtests were run.

**The question.** Should the mechanical VCP base detector be replaced with an AI judge that reads bases, pivots and entries the way Minervini does? This memo collects the evidence that bears on that decision.

**Background.** See `experiment3/minervini_check/FIX_TESTS_RESULT.md`:
- the trend and relative-strength filters agree with his buys;
- the VCP detector rejects most of his entries;
- no mechanical arm beat the index in both 2017-2021 and 2022-2026.

**Evidence labels.** Every claim carries one of these:
- **[V]**: I read it in the paper, its abstract or an official page.
- **[S]**: seen only in a search-result snippet or a secondary summary. Check it before relying on it.
- **[P]**: practitioner or non-peer-reviewed material (GitHub, a gist, a blog). Low weight.

No citation here was made up. Where I could not find something, the memo says so.

---

## Executive summary

1. **Trained image models work, but not where we trade.** CNNs trained on chart images do predict returns ([V] Jiang, Kelly & Xiu 2023). Accuracy is about 53% against a 50% baseline. The edge is mostly short-horizon and equal-weighted; value-weighted Sharpe at monthly holding is about 0.5, with high turnover.
2. **Classic automated pattern detection adds little.** It finds statistical information, but little stand-alone profit after costs and after controlling for data snooping ([V] Lo, Mamaysky & Wang 2000; Savin et al. 2007; Bajgrowicz & Scaillet 2012).
3. **Off-the-shelf models read charts at roughly coin-flip level.** On 193k US and China charts, the best model got the direction right 53.5% of the time, and the models showed strong directional biases ([V] Hu et al. 2026). In one practitioner test, models named the right pattern in 1 of 215 attempts ([P]).
4. **LLMs reason poorly about numeric price series.** They score barely above random, up to 30 points below humans ([V] Merrill et al. 2024). In LLM-based forecasters, removing the LLM does not hurt accuracy ([V] Tan et al. 2024).
5. **Nobody has published a working AI version of Minervini's or O'Neil's base-reading.** I found no study that automates VCP or cup-with-handle judgement with ML or an LLM and shows after-cost, out-of-sample outperformance. There are only practitioner repos. One of them finds a bare VCP detector *anti-predictive* on the S&P 500 in 2021-26, with the trend gate doing the work ([P]).
6. **Leakage is the decisive problem.** LLMs memorise pre-cutoff market data. GPT-4o recalls S&P 500 levels with a 0.6% error before its cutoff and 16.9% after. Telling it to "only use data before X" fails, and masking text fails ([V] Lopez-Lira, Tang & Zhu 2025).
7. **Both of our test windows are contaminated.** 2017-21 and 2022-26 overlap current models' training data. Minervini's own annotated charts of his public trades are very likely in that data too (my inference, not tested). No historical backtest of an LLM judge can be made clean, only less dirty.
8. **Hiding tickers and dates helps for price-only inputs, but is unproven for our charts.** In one test, attackers recovered the stock in their top 5 guesses 10.2% of the time, against 1.7% by chance (China A-shares; [V] Zhu et al. 2026). Nobody has tested rescaled *US chart images* of famous stocks, so we must run our own leakage probe.
9. **Money is not the obstacle.** 10k-30k judgements cost roughly $20-$150 per test period on paid batch APIs ([V] official pricing, 2026-09-27). Free tiers allow only about 60-1,000 calls per day, which is enough for prompt work and probes but not for a full run.
10. **Recommendation.** Treat an AI judge as a hypothesis for forward, post-cutoff paper trading, with the model and prompt frozen. Score it pre-registered against both the mechanical detector and a random-pick control. Any historical run is a diagnostic, not evidence.

---

## Q1. Does machine reading of chart images or price series predict returns?

**Jiang, Kelly & Xiu, "(Re-)Imag(in)ing Price Trends", *Journal of Finance* 78(6), 2023, pp. 3193-3249** [V]
([Wiley](https://onlinelibrary.wiley.com/doi/10.1111/jofi.13268); [working paper PDF](https://www.aidf.nus.edu.sg/wp-content/uploads/2022/02/Xiu-Re-Imagining-Price-Trends.pdf); [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3756587)). Figures below are from the working-paper version; the published tables may differ slightly.

Setup:
- CNNs are trained on black-and-white images of the last 5, 20 or 60 days of OHLC bars, volume and a moving average, for all CRSP stocks.
- Training and validation use 1993-2000 only. The model is then frozen and tested on 2001-2019.

Results:
- **Accuracy.** Out-of-sample directional accuracy for 20-day returns is 52.5-53.6%. Momentum scores 52.1% and 1-month reversal 50.4%.
- **Sharpe ratios.** The top-minus-bottom decile portfolio, held one month, reaches an annualised Sharpe of **2.4 equal-weighted but only about 0.5 value-weighted**. The weekly-rebalanced equal-weight version reaches 7.2; the authors themselves say not to read that as achievable trading.
- **Turnover.** Monthly-strategy turnover is about the same as short-term reversal, around 170% a month. With a one-week trading delay, the monthly Sharpe is still about 0.9.
- **Horizon.** At a quarterly holding period only the 5-day-image model stays significant, value-weighted Sharpe 0.5.
- **What drives it.** A key ingredient is the **rescaling** implicit in the image: each chart is normalised to its own window. The CNN signal correlates most with dollar volume, size, reversal and illiquidity, and known signals explain at most 12% of it.
- **Transfer.** The patterns transfer across horizons and to international markets.

What this means for us:
- The best evidence for "machines reading charts" is a model trained on forward returns. It is not a model imitating a human's pattern labels.
- Its edge is concentrated at short horizons and in equal-weighted (smaller) stocks. Our S&P 1500, multi-week-hold setting is where it is weakest.

**Later replications and follow-ups:**
- **Several replications support the original.**
  - China: Lu & Wu, [SSRN 4171663](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4171663) [S].
  - Korea: *Research in International Business and Finance*, 2025, [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0275531925004878) [S]. The page was blocked (HTTP 403), so I have not read the results.
  - Open replications: [lich99/Stock_CNN](https://github.com/lich99/Stock_CNN) and [RichardS0268/CNN-for-Trading](https://github.com/RichardS0268/CNN-for-Trading) [P].
  - An ablation study says the OHLC bar geometry is the main source of the predictive power: Guan, Li & Si, [SSRN 6389479](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6389479) [S]. SSRN returned 403.
- **No published failure found.** I did not find a peer-reviewed failure to replicate. I also found no clean post-2019, after-cost update by the original authors.

**Broader cautions from ML asset pricing:**
- **ML edges sit in hard-to-trade stocks.** Avramov, Cheng & Metzker, "Machine Learning vs. Economic Restrictions", *Management Science* 69(5), 2023 [V abstract via [IDEAS](https://ideas.repec.org/a/inm/ormnsc/v69y2023i5p2587-2619.html)]:
  - deep-learning signals earn their profits mainly in hard-to-arbitrage stocks and in high-volatility periods;
  - excluding microcaps and distressed firms "considerably attenuates" profitability, and reasonable trading costs erode it further.
- **Published effects decay.** McLean & Pontiff, *Journal of Finance* 71(1), 2016 [V abstract via [Wiley](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365)]: across 97 published predictors, returns are 26% lower out-of-sample and 58% lower after publication.

**Classic automated pattern recognition:**
- **Lo, Mamaysky & Wang, "Foundations of Technical Analysis"**, *Journal of Finance* 55(4), 2000 ([NBER w7613](https://www.nber.org/papers/w7613)) [V abstract].
  - Kernel-regression smoothing automatically detects head-and-shoulders, double bottoms and similar shapes in US stocks, 1962-1996.
  - Several patterns change the conditional return distribution and "may have some practical value".
  - This is a test of distributions, not a cost-adjusted trading result.
- **Savin, Weller & Zvingelis**, *Journal of Financial Econometrics* 5(2), 2007 ([OUP](https://academic.oup.com/jfec/article-abstract/5/2/243/785044)) [S].
  - They use the Lo-Mamaysky-Wang detector with filters of the kind a technical analyst would apply, on the S&P 500 and Russell 2000, 1990-99.
  - They find "little or no support for the profitability of a stand-alone trading strategy", but significant power to predict excess returns.
- **Bajgrowicz & Scaillet**, *Journal of Financial Economics* 106, 2012 ([SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1095202)) [V abstract].
  - They test thousands of technical rules on the Dow, 1897-2011, correcting for data snooping with the false discovery rate.
  - Investors could not have picked the future winners in advance.
  - Even in-sample, low transaction costs wipe out the profits.
- **Template matching.** Leigh, Modani, Purvis & Roberts 2002 (bull flag, NYSE Composite, 1981-96) and Wang & Chan 2007 (flags, NASDAQ and Taiwan) report positive index-level results [S]. Samples are small and in-sample-heavy.

**Q1 bottom line:**
- Machine-read price shapes contain real but **small** information: about 1-3 percentage points of directional accuracy.
- It converts to money mainly at short horizons and in small, illiquid stocks, and it decays after publication and after costs.
- None of this evidence is about imitating a discretionary trader's base judgement.

---

## Q2. LLMs (GPT-4-class, Gemini, Claude, Llama) reading charts or OHLCV

**Hu, Xiao, Xu, Tang & Liu, "Do VLMs Truly 'Read' Candlesticks? A Multi-Scale Benchmark for Visual Stock Price Forecasting", arXiv 2604.12659, April 2026** ([arXiv](https://arxiv.org/abs/2604.12659)) [V]

This is the most relevant study.
- **Models:** Claude Haiku 4.5, Claude Sonnet 4.5, Gemini 2.5 Flash, Gemini 2.5 Pro, GPT-4o, GPT-5 mini and Qwen, against an XGBoost baseline.
- **Data:** 193,524 daily and weekly candlestick charts for HS300 and **S&P 500** stocks, test period 2023-25. The target is the 30-day forward return.
- **Accuracy:** the best was **53.48%** (Sonnet 4.5 with thinking, on HS300), against XGBoost's 50.87%. XGBoost was more stable and ranked stocks better on average.
- **Where the models work:** only "under persistent uptrend or downtrend conditions", with weak predictive power in ordinary markets.
- **Biases:** significant directional biases, and little sensitivity to the forecast horizon stated in the prompt.
- **Leakage check:** a "peeping" experiment across GPT-4o versions found no sign of leakage for that setup.

**FinChart-Bench**, ACL 2026 ([ACL Anthology](https://aclanthology.org/2026.acl-long.615/), [arXiv 2507.14823](https://arxiv.org/abs/2507.14823)) [S]
- 1,200 real financial charts (2015-24) with 7,016 questions, testing 26 vision models.
- This is chart *comprehension* (answering questions about a chart), not prediction.
- A snippet reports that multimodal models "struggle with the fine-grained geometric perception" that pattern identification needs.

**Antonov, "Stop Using Vision LLMs to Read Trading Charts", GitHub gist, April 2026** ([gist](https://gist.github.com/roman-rr/c1cd675f7c35b68ae5ac281c30080166)) [P]
- Tested Claude Haiku 4.5, Sonnet 4.6, Opus 4.7 and Gemini 3 Flash on 40 real crypto signals.
- The right pattern name came back **1 time in 215 calls**.
- Direction was right 51-57% of the time; every 95% confidence interval includes 50%.
- The models' stated confidence was uncorrelated with being right.
- **Gemini called 100% of the long signals long and only 10% of the short signals short.**
- An early pass with 10 signals showed 80% accuracy, which fell to chance with more data. The sample is small, and this is crypto, not stocks.

**Ntale, "AI Trading: Evaluating Large Language Models for Technical Market Analysis", Georgia Tech master's paper, arXiv 2607.15414, July 2026** ([arXiv](https://arxiv.org/abs/2607.15414)) [V abstract]
- Tested GPT-4 Turbo, Claude 3 Opus, Gemini 1.5 Pro, Llama 3 70B and FinGPT on candlestick-pattern recognition from OHLCV data, plus buy/sell signals.
- It claims outperformance versus the S&P 500. The abstract describes no look-ahead controls, so treat it as likely contaminated.
- It notes "numerical hallucination" and poor performance in sideways markets.

**StockBench**, arXiv 2510.02209, 2025 ([arXiv](https://arxiv.org/abs/2510.02209)) [S]
- Design: LLM trading agents on market data from March-July 2025, chosen to fall after the models' training cutoffs.
- Most agents failed to beat buy-and-hold. The best agent (Kimi-K2) made +1.9% against +0.4% for buy-and-hold.
- The agents failed in the January-April 2025 downturn, a sign of bullish bias.

**Time-series reasoning:**
- **Merrill et al., EMNLP Findings 2024** ([ACL](https://aclanthology.org/2024.findings-emnlp.201/)) [V abstract]: LLMs score "marginally above random" on time-series reasoning tasks, up to 30 points below humans.
- **Tan et al., NeurIPS 2024** ([proceedings](https://proceedings.neurips.cc/paper_files/paper/2024/hash/6ed5bf446f59e2c6646d23058c86424b-Abstract-Conference.html)) [V abstract]: in three LLM-based forecasters, removing the LLM or replacing it with a basic attention layer does not hurt accuracy, and usually improves it.
- **Koa et al., "Verbal Technical Analysis", ICLR 2026** ([arXiv 2511.08616](https://arxiv.org/abs/2511.08616)) [V abstract]: an LLM reasons over OHLCV-as-text to condition a forecasting model, and claims state-of-the-art forecast error. This is a trained hybrid, not a zero-shot judge. No trading result or cutoff control appears in the abstract.
- **QuantHarness**, Xiong et al., arXiv 2509.09995 ([arXiv](https://arxiv.org/abs/2509.09995)) [V abstract]: multi-agent LLMs with "pattern" and "trend" agents on 1-hour and 4-hour crypto and futures bars. The abstract gives no cost-adjusted or post-cutoff numbers.

**Answers to the sub-questions:**
- **Can LLMs recognise cup-with-handle, VCP or flag patterns?**
  - No rigorous benchmark with expert-labelled stock bases exists that I could find.
  - The available evidence ([P] gist; [S] FinChart-Bench) says pattern naming and fine geometry are unreliable.
- **Accuracy against human experts:** no study compares LLMs with expert chartists on chart patterns. The closest is Merrill et al.'s general time-series comparison, where models were up to 30 points below humans.
- **Trading results:** those with credible post-cutoff designs (StockBench, Hu et al.) are about break-even to marginal. Positive claims come from studies without leakage controls.

---

## Q3. Look-ahead and memorisation in LLMs on financial data

**Key papers:**
- **Glasserman & Lin 2023**, "Assessing Look-Ahead Bias in Stock Return Predictions Generated by GPT Sentiment Analysis" ([arXiv 2309.17322](https://arxiv.org/abs/2309.17322)) [V abstract].
  - Removing company identifiers from news headlines made in-sample trading results *better*. General knowledge of the named firm (a "distraction effect") hurt more than look-ahead bias helped, especially for large firms.
  - Out-of-sample, look-ahead bias was a minor concern.
  - Lesson: anonymising can also improve the signal.
- **Sarkar & Vafa**, "Lookahead Bias in Pretrained Language Models", ICML 2025 workshop (DIG-BUGS) ([ICML page](https://icml.cc/virtual/2025/51018); [SSRN 4754678](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4754678)) [V ICML abstract].
  - They test for bias using events that should be unpredictable from the given information, and find it in forecasts of risk factors from earnings calls and of election outcomes.
  - Prompting-based fixes have limitations. The recommended fix is models trained only on text from before the analysis period.
- **Lopez-Lira, Tang & Zhu 2025**, "The Memorization Problem: Can We Trust LLMs' Economic Forecasts?" ([arXiv 2504.14765](https://arxiv.org/abs/2504.14765); [SSRN 5217505](https://ssrn.com/abstract=5217505)) [V HTML].
  - **GPT-4o recalls market data before its cutoff.** For the S&P 500 level, the average error is 0.61% before the October 2023 cutoff and 16.87% after it. Directional accuracy is 80.6% before and 45.7% after.
  - **Telling it to use only pre-2010 data does not work.** Its "forecast" accuracy stayed about 98% after that fake cutoff, against 40% after its real cutoff.
  - **Masking earnings-call text fails.** It identified the company in 85% or more of the anonymised calls it was tested on, and pinned the fiscal quarter and year of Apple calls 93% of the time.
  - **It can date news headlines.** It named the exact date of 47% of headlines published before its cutoff and 8% after.
  - The authors' conclusion: only post-cutoff tests are reliable, and they warn that small post-cutoff samples lack statistical power.
- **Gao, Jiang & Yan**, "Detecting Lookahead Bias in LLM Forecasts", arXiv 2512.23847, revised June 2026 ([arXiv](https://arxiv.org/abs/2512.23847)) [V abstract].
  - They propose "Lookahead Propensity" (LAP), which probes whether the model recalls the outcome for a given firm and date.
  - LAP is positive in the training period and "collapses essentially to zero" after the cutoff.
  - The LLM's predictive power is amplified on high-LAP samples, which is the signature of contamination.
- **Li et al., "Profit Mirage"**, arXiv 2510.07920, 2025 ([arXiv](https://arxiv.org/abs/2510.07920)) [S]: the Sharpe ratios of leading LLM trading agents fall 51-62% from backtest periods to post-cutoff periods.
- **Benhenda, "Look-Ahead-Bench"**, arXiv 2601.13770, 2026 ([arXiv](https://arxiv.org/abs/2601.13770)) [V abstract]: Llama 3.1 and DeepSeek show significant look-ahead bias, measured as alpha decay; point-in-time models do not.
- **Point-in-time models:**
  - Time Machine GPT (Drinkall, Rahimikia, Pierrehumbert & Zohren, NAACL Findings 2024; [ACL](https://aclanthology.org/2024.findings-naacl.208/)) [V abstract];
  - ChronoBERT and ChronoGPT (He, Lv, Manela & Wu, [arXiv 2502.21206](https://arxiv.org/abs/2502.21206)) [V abstract], which match a much larger Llama on news-to-returns Sharpe, suggesting look-ahead bias was modest there;
  - DatedGPT ([arXiv 2603.11838](https://arxiv.org/html/2603.11838)) [S].
  - All are small, text-only models, not vision chart readers.

**Can an LLM identify the stock or the date from an anonymised price chart?**
- **Zhu et al. (Tsinghua, StepFun and others), "From Knowing to Doing" (KTD-Fin), arXiv 2605.28359, 2026** ([arXiv](https://arxiv.org/html/2605.28359v1)) [V].
  - Setup: CSI300 stocks, 2024-01 to 2026-04. Tickers were replaced by aliases and dates by day indices. **Prices were not rescaled**; returns, volatility and drawdown were computed on real series.
  - Ten frontier LLMs acting as attackers got the stock in their top 5 at most **10.2%** of the time (chance about 1.7%), and top-1 at most 3%.
  - Recovering the date within ±7 days was near chance. Ticker and date together succeeded at most 1.5% of the time.
  - With real tickers and no data, the agent traded on brand stories. When blinded, it held cash.
- **Jeon & Lee, "BlindTrade"**, arXiv 2603.17692, 2026 ([arXiv](https://arxiv.org/html/2603.17692v1)) [V]:
  - replaces tickers with IDs and anonymises news through a knowledge graph;
  - runs no direct re-identification test, relying on negative controls such as shuffled scores;
  - its 2025 Sharpe of 1.40 did not hold in 2024 (0.34 against 1.70 for SPY).
- **Hu et al. 2026** [V]: the "peeping" test found no leakage for candlestick forecasting.
- **Gap.** No study I found tests re-identification from **rescaled US daily charts of famous stocks and famous dates**. Examples of the risk are the February-March 2020 crash, the 2022 bear market, meme-stock spikes, and NVDA/SMCI/APP in 2023-24.
  - Minervini's disclosed trades are exactly such famous charts, and he publishes annotated versions of them (inference; untested).
  - A 250-bar window containing March 2020 can probably be dated by its shape alone (my inference; untested).

**Which mitigations work:**
- **Testing only after the model's cutoff** is the one mitigation every source endorses (Lopez-Lira et al.; Gao et al.; StockBench; Profit Mirage).
- **Prompt instructions** ("pretend it is date X") do not work (Lopez-Lira et al.; Sarkar & Vafa).
- **Anonymising text** does not work for rich text such as transcripts (Lopez-Lira et al.), although it removes the distraction effect (Glasserman & Lin).
- **Anonymising price-only inputs** mostly works on CSI300 (KTD-Fin), but is not demonstrated for US charts.
- **A guess-the-ticker probe** is an accepted diagnostic (KTD-Fin; Gao et al.'s LAP). It gives only a lower bound on what the model knows (Lopez-Lira et al.).

---

## Q4. Costs and throughput

All figures are from official pages fetched 2026-09-27 [V] unless marked. Prices change often, so re-check before committing money.

| Provider / model | Input $/M tokens | Output $/M tokens | Batch | Free tier |
|---|---|---|---|---|
| Google Gemini 3.6/3.7/3.8 Flash ([pricing](https://ai.google.dev/gemini-api/docs/pricing)) | 0.75 (1.50 from 2027-01-01) | 3.75 (7.50 from 2027) | −50% | Yes. Official limits appear only in AI Studio; third-party pages say about 20 requests/day for 3.x Flash [S] |
| Gemini 3.1 Flash-Lite | 0.25 | 1.50 | −50% | Yes. About 500-1,000 requests/day and about 15 per minute per third-party pages ([S] [scriptbyai](https://www.scriptbyai.com/gemini-api-free-tier-limits/)) |
| Groq gpt-oss-120b ([models](https://console.groq.com/docs/models)) | 0.15 | 0.60 | Paid plan only | 30 per minute, 1K per day, **8K tokens/minute and 200K tokens/day** ([limits](https://console.groq.com/docs/rate-limits)). Groq's Llama 3.1 8B and 3.3 70B are now listed as "Enterprise" models, with no free Llama chat model |
| Cerebras gpt-oss-120b / Qwen ([limits](https://inference-docs.cerebras.ai/support/rate-limits)) | Not retrieved (the pricing page did not render) | Not retrieved | — | 5 per minute, **1M tokens/day**. The pay-as-you-go tier allows 1K per minute and has no daily cap |
| Anthropic Claude Haiku 4.5 ([pricing](https://platform.claude.com/docs/en/about-claude/pricing)) | 1.00 | 5.00 | $0.50 / $2.50 | Small trial credit only |
| Anthropic Claude Sonnet 5 (a stronger judge) | 2.00 | 10.00 | $1 / $5 | — |

**Token budget per judgement** (my estimates):
- **Text input.** 250 daily OHLCV bars as raw CSV with dates run to about 7-9k tokens. To get down to about 1.5-2.5k tokens:
  - rescale prices to integers (window start = 100 or 0-999);
  - drop dates and use day indices;
  - send volume as a ratio to its 50-day average.
- **Instructions.** Add about 0.8k tokens for the instructions (the Minervini rubric) and about 300 output tokens for a JSON verdict with brief reasons.
- **Image input.** Claude bills `ceil(w/28) × ceil(h/28)` tokens, so a 1000×600 chart is about **792 tokens** ([V] [vision docs](https://platform.claude.com/docs/en/build-with-claude/vision)). Gemini's image token count was not verified.
- **Reasoning tokens.** Hidden reasoning or "thinking" tokens are billed as output. They can double or triple the cost if left on.

**Cost for 30,000 judgements** (about 3k input and 300 output tokens each, no thinking):

| Model | Standard | Batch |
|---|---|---|
| Gemini 3.1 Flash-Lite | ~$36 | ~$18 |
| Groq gpt-oss-120b | ~$19 (~$46 with about 1.5k reasoning tokens) | n/a |
| Gemini 3.x Flash (2026 price) | ~$101 | ~$51 |
| Claude Haiku 4.5 | ~$135 | ~$68 |
| Claude Sonnet 5 | ~$270 | ~$135 |

The chart-image version (about 1.6k input tokens) costs roughly 30% less. Two periods × 3 prompt or model variants still comes to **under about $1,000**.

**Throughput:**
- **Free tiers do not scale to a full run.** At about 3.3k tokens per call:
  - Groq's free tier allows about 60 calls a day, because of the 200K-token daily cap. 30k calls would take about 500 days.
  - Cerebras's free tier allows about 300 calls a day, so about 100 days.
  - Gemini Flash-Lite's free tier allows about 500-1,000 calls a day [S], so 30-60 days.
  - Also check the free-tier data-use terms, because free-tier prompts may be used by the provider (not verified).
  - Use free tiers for prompt development and the leakage probe, which needs only a few hundred calls.
- **Paid batch APIs do scale.** They are asynchronous (Anthropic and Google both offer 50% off) and finish 30k requests in hours to a day.
- **Workload sizing:**
  - Judging all ~255 daily trend-passers every day for 5 years is about 320k calls, which is too many.
  - Judging the ~34 weekly breakout candidates is about 8.8k per 5-year period.
  - Judging the top ~100 trend/RS names weekly is about 26k per period.
  - The last two options fit the 10k-30k envelope.
- **Reproducibility:**
  - Cache every response under (model id, prompt hash, input hash) and pin the exact model snapshot.
  - The Anthropic pricing page already lists retired models, and Gemini prices change on 2027-01-01. A judge whose model has been retired cannot be re-run.

---

## Q5. Published attempts to automate Minervini, O'Neil or CAN SLIM base detection

**No peer-reviewed work found.** I found no peer-reviewed paper that detects VCP or cup-with-handle bases with ML or an LLM and reports out-of-sample, after-cost returns.

What does exist:
- **Lutey, Crum & Rayome, simplified CAN SLIM** (2013-14, a small-journal article; a related [ResearchGate listing](https://www.researchgate.net/publication/326548848_OUTPERFORMING_THE_BROAD_MARKET_AN_APPLICATION_OF_CAN_SLIM_STRATEGY) whose authorship I did not confirm) [S].
  - They report outperforming the Nasdaq 100 by 0.94% a month over 1999-2013.
  - It uses fundamentals and trend screens, not base reading, and I have not verified its survivorship or cost handling.
- **IBD MarketSmith's automated pattern recognition** (O'Neil's own commercial detector) was used through its API in a practitioner backtest ([GitHub HumanRupert](https://github.com/HumanRupert/marketsmith_pattern_recognition)) [P].
  - Dow 30 stocks only, 2016-17.
  - 9.7% a year with a beta of 0.1. The sample is far too small to mean anything.
  - I found no independent published evaluation of MarketSmith's detector.
- **VCP screeners on GitHub** [P]:
  - [rollroyces/vcp-signals](https://github.com/rollroyces/vcp-signals) replays S&P 500 stocks 2021-26, about 117k ticker-days.
    - The **bare VCP detector is "anti-predictive"**: 60-day mean return +1.87% with a 56.8% hit rate, and **−2.4 points** against the S&P 500.
    - Adding the Stage-2 trend template and RS gate gives +3.30% mean, a 60% hit rate, and only **+0.6 points** of excess.
    - This mirrors our finding: the trend and RS filters carry the signal, the base detector adds little. Unaudited.
  - [catchitearly/vcp](https://github.com/catchitearly/vcp) is a walk-forward framework with no published results. Its README tells users to check whether the VCP filter "actually improves the numbers or just cuts your sample size".
  - [phuazz/vcp-screener](https://github.com/phuazz/vcp-screener) reports a holdout Sharpe of about 1.0 [S].
  - [shiyu2011/cookstock](https://github.com/shiyu2011/cookstock) uses an LLM for news sentiment only.
  - [mphinance/alpha-skills](https://github.com/mphinance/alpha-skills) uses an LLM to critique strategy drafts, with no results.
- **Academic chart-pattern detectors:**
  - Velay & Daniel 2018, CNN/LSTM chart-pattern recognition ([arXiv 1808.00418](https://arxiv.org/abs/1808.00418)) [V abstract]: classification accuracy only, no returns.
  - Template matching: Leigh et al. 2002; Wang & Chan 2007 [S].
  - Lobão 2024, China ([Wiley](https://onlinelibrary.wiley.com/doi/full/10.1002/ise3.62)) [S; results not read].
  - None of these covers VCP or cup-with-handle judgement.

**Q5 bottom line.** There is no evidence base for "an AI that reads Minervini bases". What practitioner evidence exists suggests the base-shape layer adds little on top of trend and RS. That points at the mechanical detector's *value*, not just its strictness.

---

## What would make an AI-judge test honest

| # | Mitigation | Problem it addresses | Evidence | Verdict for our test |
|---|---|---|---|---|
| 1 | **Evaluate only on data after the model's training cutoff** | Memorised outcomes | Lopez-Lira et al. 2025 (accuracy collapses after cutoff); Gao et al. (LAP ≈ 0 after cutoff); Profit Mirage (Sharpe −51% to −62%); StockBench design | **Required for any claim of edge.** For current models this means forward paper trading. 2017-21 and 2022-26 cannot provide it. |
| 2 | **Point-in-time models** (ChronoGPT, TiMaGPT, DatedGPT) | Pretraining leakage | He et al. 2025; Drinkall et al. 2024; Benhenda 2026 | Clean, but small text-only models with no vision. Useful only as a leakage-free control on text-encoded bars. |
| 3 | **Anonymise the ticker, remove dates, rescale prices, express volume relative to its own average, no axis labels, fixed chart style** | Recognising the stock or date | KTD-Fin: top-5 ticker recovery 10.2% vs 1.7% chance, even without rescaling; Glasserman & Lin: removes the distraction effect; JKX: rescaling helps prediction | **Do it**, but it is **not sufficient**. Text masking fails (Lopez-Lira), and famous US charts are untested. |
| 4 | **Leakage probe before the run** | Unknown residual recognisability | KTD-Fin attacker protocol; Gao et al. LAP; Lopez-Lira (a probe gives only a lower bound) | Use the same inputs the judge sees. Ask the model for its top-5 tickers, the year, the sector and "what happened in the next 3 months". Pass only if results are near chance. Report results split into recognised and unrecognised samples, and drop recognised ones. |
| 5 | **Do not tune on Minervini's disclosed trades, or hold them out entirely** | His annotated charts are probably in the training data; his disclosed picks lean to winners | Our RESULT.md caveats; Lopez-Lira (entity reconstruction) | Use his trades only as a qualitative sanity check, never as calibration labels or the success metric. |
| 6 | **Freeze everything before the run**: pinned model snapshot, prompt, temperature 0, output schema, candidate set. Keep our lock-commit ritual. | Tuning prompts on the test window (data snooping) | Bajgrowicz & Scaillet 2012; McLean & Pontiff 2016 | Required. Develop the prompt on a separate, earlier window or on synthetic charts. Change it only through a new lock. |
| 7 | **Pre-registered baselines on the same candidates**: the mechanical detector, a random pick at the same acceptance rate, "take all breakouts", and a simple trained model (XGBoost or a JKX-style CNN fit only on pre-period data) | Mistaking selection rate or regime for skill | Hu et al. (XGBoost competitive); JKX (a trained CNN beats handcrafted rules) | Required. An AI judge must beat the random pick and the mechanical detector, not just the index. |
| 8 | **Score every candidate, not just the trades bought**: judge all ~34 weekly candidates and compare the forward returns of accepted against rejected | Too few trades (~2/week) for statistical power | Lopez-Lira et al. (low power of small post-cutoff tests) | Gives about 1.7k scored candidates a year instead of about 100 trades, and can be paired week by week against the mechanical detector. |
| 9 | **Check bias and consistency**: acceptance rate by market regime; "always long" behaviour; answers stable across reruns and small chart changes; mirror-image and synthetic control charts | Directional bias; random answers dressed as judgement | Antonov gist (Gemini 100% long) [P]; Hu et al. (directional biases); Profit Mirage (counterfactual checks) | Cheap and required. Reject the judge if its acceptance rate just tracks recent market direction. |
| 10 | **Full engine, costs and index comparison as the only success metric** | Agreement with Minervini is not profit | Our FIX_TESTS results; JKX (value-weight Sharpe ≪ equal-weight) | Same engine, costs, auditor and swept-cash comparison as experiments 1-3. |
| 11 | **Cache and log every response** (model id, prompt hash, input hash, raw output) | Irreproducible runs when models are retired | Anthropic retirement notes; Gemini 2027 price change | Required for audit. |

---

## Realistic expectations

**The best evidence for machine chart reading does not fit this strategy.** That evidence is a CNN *trained on forward returns* (Jiang, Kelly & Xiu). It is about 1-3 points more accurate than a coin flip, and its money is made at short horizons and in equal-weighted small caps. That is the opposite of a multi-week S&P 1500 breakout strategy.

**Off-the-shelf LLMs are worse at this than trained models.** Reading charts zero-shot, they score 51-53% on direction, show strong long biases, and cannot reliably name patterns. They also reason about numeric series barely above chance. Nobody has shown that an LLM reproduces Minervini's or O'Neil's base judgement, let alone that doing so earns money. Practitioner replays suggest the base-shape layer adds little beyond the trend template and RS.

**A good outcome is modest.** An AI judge that recovers some of the bases the detector wrongly rejects (for example "contraction count out of range" or "monotonicity failed") might raise the number of Minervini-like picks. More matches with him do not imply better returns: his public sample leans to winners, and we cannot measure it without survivorship bias.

**The backtest windows cannot give a clean answer.** Both windows sit inside the models' training data, and his charts are almost certainly in the training data. Any historical result would therefore be an **upper bound contaminated by memory**; a strong historical result should *raise* suspicion.

**The only clean answer is forward, and it is slow.**
- At about 2 trades a week there are about 100 trades a year.
- Assume a per-trade standard deviation of about 15% (an assumption, not a measurement).
- Then telling a 2-3 point per-trade improvement from noise takes years of trades.
- Scoring all ~34 weekly candidates and comparing accepted against rejected shortens this to roughly one to two years.

**What to expect.** Budget-wise the test is cheap: under $1k in API fees. Scientifically, the prior should be that an LLM judge will **not** beat the mechanical system after costs. The value of running it is to close the "maybe the chart reading is the missing piece" question honestly, under a pre-registered forward protocol, not to find alpha in 2017-2026 data.
