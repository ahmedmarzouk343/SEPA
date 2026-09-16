# Chapter 7 — "Fundamentals to Focus On"
*Notes and analysis (not book text). The most quantitatively dense fundamentals chapter — direct source for our fundamentals-side hard/soft filters.*

## Core thesis
Superperformance is driven by real, accelerating earnings and sales growth — not accounting engineering, not "story," not price momentum alone. This chapter is where most of our **fundamentals hard/soft-score inputs** should come from.

## Concrete quarterly earnings growth thresholds (usable as filter values)
- **Minimum bar many successful growth managers use**: current-quarter YoY EPS growth of **20–25%+** in the most recent 1–3 quarters.
- **Typical superperformance phase**: **30–40%+** quarterly YoY EPS growth.
- **Strong bull-market standard**: look for **40–100%+** in the most recent 2–3 quarters.
- More consecutive strong quarters = more confidence (examples cited ranged from 5 to 45 consecutive strong quarters for history's biggest winners).
- **This is a good hard-filter or strong soft-score input**: `most_recent_quarter_yoy_eps_growth >= 20%` as a floor, with the composite score rewarding higher values.

## Earnings acceleration — arguably the single most important fundamental signal
- **Over 90% of the biggest historical winners showed earnings acceleration** (growth *rate* increasing quarter over quarter, not just growth existing) before or during their big price moves.
- Definition: each quarter's YoY growth rate should be higher than the previous quarter's YoY growth rate — e.g., a company going from -5% → +10% → +28% → +56% YoY over four consecutive quarters is accelerating.
- **Recommended noise-reduction technique**: smooth quarter-to-quarter growth using a **2-quarter rolling average** over the trailing 4–8 quarters, rather than reacting to a single volatile quarter.
- **This is a strong, directly codeable soft-score input**: `(most_recent_qtr_growth - prior_qtr_growth) > 0` across 2–3 consecutive quarters = acceleration flag.

## Revenue must confirm earnings — avoid earnings-only signals
- Don't trust earnings growth alone — **demand sales/revenue growth and acceleration alongside it.** This guards against margin-expansion-only or one-off accounting-driven "growth" that isn't backed by real demand.
- Historical examples show sales growth accelerating in step with earnings during the best runs (e.g., quarterly sales growth rising from ~21% to ~34% across 8 quarters alongside ~45% average earnings growth).

## Annual growth, not just quarterly
- Strong annual EPS growth should back up the quarterly pattern — a couple of good quarters isn't enough on its own.
- **"Breakout year" signal**: current-year earnings breaking out above a multi-year (2–4 year) prior range/high is treated as a meaningfully bullish, discrete event — a good candidate for a boolean flag.

## Turnaround-specific threshold (ties to Ch. 6's turnaround category)
- Demand **+100% or better YoY earnings growth in the most recent 1–2 quarters**, specifically because turnarounds are coming off easy (weak/negative) prior-year comparisons — the bar needs to be higher to confirm it's real, not just an easy comp.
- Extra confirmation: earnings/margins should be at or near a new high, not just "less bad."

## Deceleration is a red flag — relative, not absolute
- Watch for **material slowdown in growth rate relative to the company's own recent pace**, even if the new growth rate still sounds decent in isolation. Example given: a company slowing from ~80% → ~65% → ~28% YoY growth is a real warning sign despite 28% still being "good growth" by normal standards — because it's a sharp deceleration from its own trend, and historically this has coincided with major stock price tops.
- **Design implication**: deceleration should be measured as **rate of change of the growth rate**, relative to the stock's own trailing pattern — not a fixed universal threshold.

## Analyst estimate revisions (needs an external estimates data source)
- Studies cited: stocks with earnings estimates **revised upward 5%+** show above-average performance; **downward revisions of 5%+** show below-average performance.
- Look for both the **current-quarter estimate** and the **current fiscal-year estimate** trending higher — both trending up together is a stronger signal than either alone.
- Large downward revisions are flagged as a stronger red flag than the absence of upward revisions is a green flag (asymmetric — downside signal matters more).
- **Note for Kashif**: this requires analyst estimates data, which we already flagged as the weak point in EGX data coverage (Part 2 of our project docs — no reliable EGX estimates API). This input may simply be unavailable for us and should be treated as optional/skippable rather than required.

## Earnings surprise quality (needs "beat magnitude" data, not just beat/miss)
- Not all "beats" are meaningful — companies routinely beat by a token amount because guidance quietly sets the bar low. **Look for a meaningful beat margin, not just beat vs. miss as a binary.**
- "Cockroach effect": a genuine earnings surprise tends to be followed by more good quarters from the same company, and often by surprises from other companies in the same sector too (reinforces the Ch. 6 sector-strength idea — sector-level earnings surprise clustering is a real signal).

## Relevance to Kashif
Concrete, directly usable filter/score inputs from this chapter:
- `recent_quarter_yoy_eps_growth >= 20%` (floor), reward higher, especially 30–40%+
- Earnings acceleration flag: growth rate increasing over 2–3 consecutive quarters (use 2-quarter rolling average to smooth)
- Revenue growth confirming earnings growth (both must be healthy, not earnings alone)
- Annual EPS growth trend + "breakout year vs. prior 2–4yr range" boolean
- Turnaround-specific override: require ≥100% recent-quarter YoY growth when tagged as turnaround
- Deceleration flag: current growth rate meaningfully below the stock's own trailing growth rate (relative measure, not fixed cutoff)
- Estimate revisions and surprise-magnitude: **mark as optional/best-effort** given known EGX data gaps — don't make the strategy depend on data we may not reliably have.
