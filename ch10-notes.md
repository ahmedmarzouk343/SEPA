# Chapter 10 — "A Picture Is Worth a Million Dollars"
*Notes and analysis (not book text). The most detailed technical/entry-timing chapter in the book. Long chapter — this is the hardest one to turn into simple hard-filter booleans; parts of it are genuinely closer to pattern recognition than a checklist. Flagged throughout where something is cleanly codeable vs. where it likely needs a dedicated pattern-detection routine or visual/AI review.*

## The core concept: Volatility Contraction Pattern (VCP)
Within a Stage 2 uptrend, a healthy pre-breakout base shows a series of pullbacks that get **progressively smaller**, each roughly **half (±) of the size of the previous one**, generally accompanied by shrinking volume at each stage.
- Typical sequence example: a 25% pullback → 15% → 8% (each roughly halving).
- Usually **2–6 contractions**, most commonly **2–4** ("Ts").
- Base duration: **roughly 3–65 weeks**, depending on depth — very short (V-shaped, "time compression") is a warning sign since it means weak holders weren't properly shaken out.
- **The final, tightest contraction should occur on unusually low volume** (below the 50-day average, sometimes near the lowest volume of the entire base) — this signals selling has genuinely dried up.
- The author's own shorthand notation: `[weeks]W [max%/final%] [#T]` — e.g. `8W 22/2 3T` = 8-week base, max correction 22%, final tightest pullback 2%, 3 contractions.

## The pivot point — the actual buy trigger
- The **pivot point = the high of the final, tightest contraction** (or the high of the base for a simple flat base). This is the exact price level that triggers a buy.
- **Buy when price breaks above the pivot, ideally on volume meaningfully above average** (examples in the book show breakout-day volume 300–1000%+ of the average).
- **Never buy in anticipation of a breakout** — wait for price to actually clear the pivot. Buying early defeats the purpose of the setup (you're taking on the same risk without the confirmation).

## Correction-depth ceiling (reinforces and sharpens Ch. 9's rule)
- Most constructive setups correct **10–35%** from peak to trough.
- Up to **~50%** can still work during a genuine bear-market correction.
- **>60% correction = high failure risk, generally avoided** — too much "overhead supply" (trapped buyers waiting to sell at breakeven) builds up.
- **Relative rule**: a stock correcting more than roughly **2–3x the general market's decline** over the same period should generally be avoided, regardless of the absolute %.

## Shakeouts — a bullish confirming signal, not necessarily a bad sign
- Price briefly undercutting an obvious prior support level (like a well-known previous low) before recovering **is a constructive sign**, not automatically bearish — it flushes out stop-loss sellers ("weak holders," which includes disciplined traders like us) and clears the way for a cleaner advance.
- Look for **1–3 shakeouts** within a base as added confirmation. This is genuinely hard to fully distinguish in real time from "the setup is actually failing" — the book itself says you can't know for certain in the moment, only interpret probabilistically.

## Evidence of institutional demand (price/volume signature)
- Sharp price spikes/gaps **up**, especially off the lows and on the right side of the base, **on unusually large volume** = likely institutional buying.
- Up-volume days should be **bigger and more frequent** than down-volume days throughout the base.

## Post-breakout health check: "tennis ball vs. egg" action
- After a valid breakout, minor pullbacks are normal — but they should be **brief (days, not weeks) and recover quickly** ("tennis ball" bouncing back), not stay down ("egg," cracked).
- **Concrete post-breakout failure signals**:
  - Price closes below its **20-day moving average** after breaking out
  - The price swings get **wider/choppier** instead of calmer
  - A pullback that doesn't recover within roughly **1–2 weeks**
- **"Squat"**: price breaks the pivot intraday but closes back inside the range the same day. Not an automatic sell — give it up to **~10 trading days** to recover, as long as price holds above the stop-loss and the 20-day moving average.
- **Early-day reversal**: a morning spike that fades by midday isn't an automatic failure either — give it until end of day unless the hard stop is actually hit.

## Cup-with-handle / 3C ("cup completion cheat")
- The cup-with-handle (originally "saucer with platform") is called the single most reliable, repeatable base pattern historically.
- **3C = the earliest valid entry point within a cup**, before the handle fully forms — an aggressive but valid alternative entry, sometimes used to build a partial position early and add more at the handle breakout.
- Qualifying conditions for a cup/3C setup: prior move up of at least **25–100%** (sometimes 200–300%+) in the preceding **3–36 months**; price above a **rising 200-day moving average**; pattern length **3–45 weeks** (most commonly 7–25); correction depth 15–40%, up to 50% in weak markets, **>60% flagged as too deep**.

## The four-phase "Turn" — why not just buy a trendline break
1. **Downtrend** — a real intermediate correction within the larger uptrend.
2. **Attempted recovery** — price rallies and breaks its downtrend line, but **don't buy yet** — this alone is not confirmation (trendline breaks are frequently false signals/whipsaws).
3. **Pause** — price plateaus in a tight range (ideally 5–10%), ideally with a shakeout below a prior low.
4. **Breakout** — price clears the high of the pause → this is the actual buy trigger.
- **Design implication**: don't treat "broke its downtrend line" as a buy signal by itself — require the subsequent pause-and-breakout confirmation (the Livermore method: wait for two reactionary pullbacks after the initial trend break, buy only when price clears the second reaction's high).

## Failure reset — getting stopped out isn't necessarily "wrong"
- If a stock stops you out (hits your stop-loss), it doesn't automatically mean the underlying thesis was bad — keep it on the watchlist. It may "reset" and offer a **second, sometimes better, setup**.
- Two forms: **base failure reset** (needs to build an entirely new base) and **pivot failure reset** (can reset and re-trigger within days).
- **Design implication for our exit/re-entry logic**: a stopped-out stock shouldn't be permanently blacklisted — it should re-enter the scanning universe fresh next cycle rather than being excluded.

## The "Power Play" (high tight flag) — the one explicit exception to requiring fundamentals
A distinct, purely momentum-driven setup with its own strict numeric qualifying criteria:
1. An explosive move of **≥100% in under 8 weeks** on huge volume, from a relatively dormant prior state.
2. Followed by sideways consolidation correcting **no more than 20–25%** over **3–6 weeks** (sometimes as short as 12 days).
3. Then a final tight consolidation correcting **no more than ~10%**, or otherwise showing standard VCP characteristics.
- **This is the only setup type the author will act on without fundamentals confirmed yet** — the extreme price/volume action itself is treated as the signal that something significant is happening. Worth keeping as a distinct, separately-flagged strategy variant rather than folding into the main fundamentals-required pipeline.

## Fundamentally sound vs. price-ready — ties fundamentals and technicals together
- A company can pass every fundamental screen and still not be a good buy **right now** if the technical setup (VCP/pivot) isn't there yet — "a good company is not always a good stock" at this moment.
- **Design implication**: fundamentals passing should move a stock to a **watch status**, not an immediate buy signal — the actual entry trigger is always the technical pivot breakout, layered on top of fundamentals that already passed.

## Relevance to Kashif — what's cleanly codeable vs. what needs more
**Cleanly codeable as numeric rules:**
- Contraction-depth sequence decreasing over the base (proxy: each swing low-to-high pullback smaller than the last)
- Base duration bounds (~3–65 weeks; flag anything forming in under ~3 weeks as "time compression," high risk)
- Correction-depth ceiling: prefer ≤35%, caution 35–50%, avoid >60% (and relative-to-market-decline check)
- Volume contraction at the final base stage (below 50-day average) + volume expansion on breakout day (meaningfully above average)
- Post-breakout health check: close below 20-day MA = invalidate; squat allowed up to ~10 trading days if stop/20-day MA hold
- Power Play as a separate, explicitly flagged momentum-only sub-strategy with its own three numeric stages

**Harder to fully proceduralize — good candidates for either a dedicated pattern-detection algorithm or the `ai_context_review`/visual-chart stage of our pipeline, not a simple hard filter:**
- Distinguishing a genuine cup-with-handle/3C shape from a random sideways chop
- Judging whether a shakeout is "constructive" vs. an actual breakdown in progress
- The qualitative "tennis ball vs. egg" read on post-breakout behavior

**New status concept**: fundamentals-pass ≠ buy signal. Add a `price_ready` boolean (pivot breakout confirmed) that gates entry on top of the fundamentals/trend-template pass — a stock can sit in "watch" status indefinitely until both are true together.
