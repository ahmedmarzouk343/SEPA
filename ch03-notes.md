# Chapter 3 — "Specific Entry Point Analysis: The SEPA Strategy"
*Notes and analysis (not book text). This is the core framework chapter — maps closely to our own pipeline design.*

## The Five Elements of SEPA (the whole book's outline)
1. **Trend** — stock must be in a defined price uptrend, identifiable early (detailed rules come in Ch. 5)
2. **Fundamentals** — earnings, revenue, and margin improvement, usually visible *before* the big price move starts (Ch. 7–8)
3. **Catalyst** — every big winner has a specific, identifiable reason: new product, regulatory approval, new contract, new leadership, something that attracts real attention (Ch. 6)
4. **Entry points** — precise, low-risk points to buy, not "somewhere in the uptrend" (Ch. 10)
5. **Exit points** — both stop-losses (protect capital) and profit-taking rules (Ch. 12–13)

**This maps almost one-to-one onto our own strategy schema** (universe filter + entry rules + exit rules + risk rules) — good sign the two frameworks are compatible.

## The SEPA screening pipeline — directly useful for our pipeline design
This is described as a 4-stage funnel, and it's basically our `hard_filter → soft_score → ai_context_review → ai_synthesis` idea, validated independently:

1. **Stage 1 — Trend Template** (hard filter, binary pass/fail — detailed rules in Ch. 5)
2. **Stage 2 — secondary filters**: earnings, sales/margin growth, relative strength, price volatility. The author notes **~95% of stocks that pass Stage 1 fail Stage 2** — this is a brutal funnel by design, not a bug.
3. **Stage 3 — Leadership Profile match**: compare survivors against the historical profile of past winners (this is literally the "discovery mode / control group" idea we already designed — the author is doing factor-model matching against historical superperformers).
4. **Stage 4 — manual/qualitative ranking**: a short list gets scored on a "relative prioritizing" basis using factors that are numeric (EPS growth, revenue acceleration, analyst estimate revisions, profit margins) mixed with judgment calls (industry position, catalyst quality, liquidity risk). **This is exactly our `ai_context_review`/`ai_synthesis` stage** — a small, pre-filtered shortlist getting nuanced scoring that pure code can't fully do.

## Concrete, extractable criteria
- **Company size**: prefers small-cap / mid-cap over large-cap. Reasoning: less float (shares available to trade) means less buying pressure needed to move the price meaningfully. Big funds structurally can't move small-float stocks the way individuals can.
- **Company age**: superperformance phases typically happen **within the first ~10 years after IPO** — younger, still-growing companies, not mature giants.
- **Catalyst requirement**: don't just screen numbers — require a real, identifiable story/reason (product launch, regulatory approval, contract win, leadership change). Hard to fully automate, but can be partially proxied by things like news/sentiment (this is where our earlier Hugging Face sentiment idea could eventually plug in, as a supplementary signal, not the core screen).
- **Market regime matters**: over 90% of superperformance phases began as the *general market* was coming out of a correction/bear market. Very few happened during ongoing bear markets. → **Individual stock signals should be gated by overall market trend condition**, not evaluated in isolation. This is a strong candidate for a top-level "market regime" hard filter that applies before any per-stock screening runs at all.

## Practical screening advice (methodology, not just criteria)
- **Don't stack too many AND-conditions into one screen.** If a screen has 12 criteria and a stock misses just 1, it's filtered out even though it passes the other 11 — good candidates get silently lost. Explicit advice: **run several smaller, separate screens grouped by compatible theme** (e.g., one screen for price/trend/relative-strength, a separate screen for earnings/sales), then look at overlap — rather than one giant combined filter.
  - **Directly actionable for us**: our `hard_filter` stage should probably be split into a few thematically grouped sub-filters (trend/technical group, fundamentals group) rather than one monolithic AND-gate, and we should look at which stocks appear across multiple groups as a signal in itself.

## Relevance to Kashif
- Confirms our pipeline shape (hard filter → soft score → AI synthesis) independently — good validation.
- New candidate hard-filter inputs: market cap band (small/mid preferred), company age since IPO, market regime gate.
- New design note: build hard filters as several smaller grouped screens, not one giant rule, and treat "appears in multiple screens" as a positive signal.
- Catalyst detection is the hardest one to make purely mechanical — likely lands in the qualitative/AI stage, not hard filter.
