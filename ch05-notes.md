# Chapter 5 — "Trading with the Trend"
*Notes and analysis (not book text). This is the most important chapter for our hard_filter design — it contains the author's explicit, numeric "Trend Template," described as non-negotiable (a stock must pass ALL of it regardless of how good the fundamentals look).*

## The Four Stages framework
Every stock cycles through four repeating stages. The strategy's entire premise is: **only ever consider buying during Stage 2.**

| Stage | Name | What's happening | Buy here? |
|---|---|---|---|
| 1 | Neglect / consolidation | Sideways, low volume, no real trend either way. Can last months to years. | No — "dead money," don't bottom-fish |
| 2 | Advancing / accumulation | Clear uptrend, big up-volume on rallies, light volume on pullbacks, institutions buying | **Yes — the only stage to buy in** |
| 3 | Topping / distribution | Momentum slows, volatility increases, sharp one-off volume spikes, smart money quietly exiting to late buyers | No — reduce/exit existing positions |
| 4 | Declining / capitulation | Confirmed downtrend, high volume on down days, new 52-week lows | No — avoid entirely, or short |

### How to recognize each stage mechanically
- **Stage 1** → price oscillates around its 200-day moving average with no clear direction; volume contracted relative to the prior decline.
- **Stage 2 begins when**: price closes above both the 150-day and 200-day moving averages, the 200-day average has turned up, and there's a clear series of higher highs/higher lows — typically confirmed only after the stock is already **~25–30%+ above its 52-week low** (waiting for confirmation over "buying the exact bottom" is explicit and intentional).
- **Stage 3** → increased volatility, the largest single-day or single-week decline since the Stage 2 advance began, price starting to whip around the 200-day average, that average flattening/rolling over.
- **Stage 4** → price mostly below a clearly declining 200-day average, new 52-week lows, lower highs/lower lows, heavier volume on down days than up days.

## ⭐ The Trend Template — 8 hard criteria, ALL required
This is described as a strict qualifier: fundamentals don't matter at all if this fails. Directly usable as our `hard_filter` stage, first in the pipeline, exactly as our project design already planned.

1. Price is above **both** the 150-day and 200-day moving averages
2. The 150-day moving average is above the 200-day moving average
3. The 200-day moving average has been trending up for at least ~1 month (ideally 4–5 months+)
4. The 50-day moving average is above both the 150-day and 200-day moving averages
5. Price is above the 50-day moving average
6. Price is at least **30% above its 52-week low** (many good candidates are 100–300%+ above their low)
7. Price is within **25% of its 52-week high** (closer is better)
8. Relative strength ranking is in at least the **70th percentile** vs. all stocks, ideally 80s–90s

**All 8 must pass simultaneously** — this is an AND-gate by explicit design, unlike the "don't stack too many conditions" advice from Ch. 3. The author treats this specific 8-item set as the one exception worth stacking, because it's really one coherent concept (confirmed uptrend) expressed eight ways, not eight unrelated ideas.

**Note on criterion 8 (relative strength ranking)**: the book references *Investor's Business Daily's* proprietary RS Rating (percentile rank of a stock's price performance vs. all others). We don't have access to that exact metric — for Kashif this needs a substitute, e.g. our own percentile rank of trailing price performance across the EGX universe, computed ourselves.

## Base counting (secondary timing layer, sits on top of the Trend Template)
- Within a Stage 2 uptrend, price advances in a series of "bases" (multi-week sideways pauses/consolidations, typically 5–26 weeks each) between pushes higher — not one straight line up.
- **Early bases (1st, 2nd) are the best entries** — usually right off a market correction.
- **3rd base is still tradable but more obvious.**
- **4th–5th base = late stage** — trend is well-known, failure rate rises sharply. Treat as a caution flag, not an automatic reject.
- This gives us a natural "how mature is this trend" score to layer onto the binary Trend Template pass/fail — good soft-score candidate.

## Critical exit/risk signal (ties directly into our exit rules)
- **The single largest daily or weekly price decline since the Stage 2 advance began, on heavy volume, is treated as a sell signal — even if it happens right after a "good" earnings report.** Price action is trusted over headline fundamentals; by the time deteriorating fundamentals are officially confirmed, the book's examples show stocks already down 50–99% from highs.
- Explicit anti-pattern: **do not buy a sharp, high-volume decline in a former leader thinking it's now "cheap"** — this is the same broken-leader trap from Ch. 4, now expressed as a technical signal (biggest drawdown bar since the trend began = exit, not entry).

## Relevance to Kashif
- **This chapter IS our `hard_filter` stage.** The 8-point Trend Template translates almost directly into JSON boolean conditions on moving averages, 52-week range, and a relative-strength percentile we'll need to compute ourselves for EGX.
- **New soft-score input**: base count (1st–2nd = favorable, 3rd = neutral, 4th–5th = caution) — feeds the soft_score composite, not a hard filter.
- **New exit rule candidate**: "largest single-day or single-week price decline since entry, on above-average volume" → automatic exit-candidate flag for held positions, independent of any fundamental news.
- Confirms: don't try to time the exact bottom; wait for confirmed trend before considering entry.
