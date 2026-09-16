# Kashif Trading Manifesto
*The complete rule set, consolidated from all 13 chapters of Minervini's "Trade Like a Stock Market Wizard" — reworded and organized as a step-by-step protocol, not book text. This is the document to actually apply when screening, entering, and managing positions.*

---

## Part 0 — The Philosophy (why every rule below exists)

- **Risk comes first.** Before "how much can this make," always ask "how much can this lose." Every rule in this document is downstream of that question.
- **Deterministic rules beat discretion.** The strategy's edge comes from mechanically applying rules without emotion — not from cleverness in the moment. Decide everything in advance; execute without hesitation.
- **You don't need to be right often. You need your wins to be bigger than your losses.** A 50% win rate is enough to succeed if losses are capped small and wins are allowed to run.
- **No stock is "safe" enough to skip the rules.** Every position — blue chip or unknown small-cap — gets the same discipline. No exceptions.
- **Being wrong is fine. Staying wrong is the only real mistake.**

---

## Part 1 — Market Regime Gate (check before screening anything)

Run this before any individual-stock screening. If the regime is unfavorable, don't force entries.

- **Check leading-stock behavior, not just the index.** Track the ratio of stocks hitting new highs vs. new lows across the universe. A rising ratio = improving regime.
- **Shallow pullbacks = strength.** In a genuine new uptrend, pullbacks in leading stocks are brief (days, not weeks) and shallow (roughly 3–10%). If leaders keep recovering quickly, that's bullish confirmation — don't wait for a "better" pullback that isn't coming.
- **>90% of superperformance moves historically began as the general market was exiting a correction or bear market.** Very few started during an ongoing downtrend. This is a legitimate reason to reduce activity or pause entries entirely during confirmed bear conditions.
- **Leadership rotates.** Fewer than 25% of one cycle's leading stocks/sectors lead the next cycle. Never bias screening toward what worked last cycle — re-screen the full universe fresh each time.

---

## Part 2 — Hard Filter: The Trend Template (Chapter 5)

**Non-negotiable. A stock must pass ALL 8 criteria simultaneously, regardless of how good the fundamentals look. This is the one place where stacking many AND-conditions is intentional.**

1. Price is above **both** the 150-day and 200-day moving averages
2. The 150-day moving average is above the 200-day moving average
3. The 200-day moving average has been trending up for **at least 1 month** (ideally 4–5 months+)
4. The 50-day moving average is above both the 150-day and 200-day moving averages
5. Price is above the 50-day moving average
6. Price is **at least 30% above its 52-week low**
7. Price is **within 25% of its 52-week high**
8. Relative strength ranking is in at least the **70th percentile** vs. the universe, ideally 80s–90s (needs an EGX-specific computed version — no IBD RS Rating available to us)

**Any single failure = disqualified**, no matter how attractive the story or fundamentals.

---

## Part 3 — Fundamentals Screen (Chapters 7–8)

Run as **separate grouped sub-screens**, not one giant combined filter (per Ch. 3's explicit advice — a 12-condition AND-gate silently kills good candidates that miss on just one line).

### Earnings growth
- Recent-quarter YoY EPS growth: **≥20–25% floor**, reward higher — 30–40%+ typical of superperformance phase, 40–100%+ in strong bull markets
- More consecutive strong quarters = stronger confidence

### Earnings acceleration
- Growth *rate* increasing quarter over quarter (not just growth existing) — **present in >90% of history's biggest winners**
- Smooth with a 2-quarter rolling average over trailing 4–8 quarters to cut noise

### Revenue confirmation
- Sales/revenue growth and acceleration must **confirm** earnings growth — never trust earnings growth alone (guards against margin-only or accounting-driven "growth")

### The Code 33 (strongest composite signal in the book)
- **3 consecutive quarters of simultaneous acceleration in earnings growth, sales growth, AND profit margin** — all three together, not just one or two

### Deceleration flag (relative, not absolute)
- Watch for growth rate meaningfully slower than the stock's **own recent pace**, even if the new rate still sounds decent in isolation (e.g., 80%→65%→28% is a red flag despite 28% being "good" on its own)

### Earnings quality checks
- Strip out non-recurring/one-time gains before judging "earnings growth" — use core/adjusted EPS where available
- Repeated "one-time" charges quarter after quarter = red flag on quality
- Cost-cutting-only earnings growth is lower quality than revenue-driven growth
- Guidance reversal (raised then cut within days/weeks) = severe red flag
- **Price reaction to earnings is a trustworthy signal on its own** (no extra data needed): a genuinely strong report should produce a price reaction that holds up over following days; a pop that sells off and can't recover is a warning regardless of the headline numbers

### Optional / best-effort (known EGX data gaps — don't make these required)
- Analyst estimate revisions (5%+ up/down move associated with above/below-average performance)
- Earnings surprise magnitude (not beat/miss binary — the size of the beat matters)
- Inventory/receivables analysis (manufacturing/retail-specific, needs granular balance-sheet data)

---

## Part 4 — Company & Sector Tagging (Chapter 6)

Classify each candidate — this changes which rules apply, not just descriptive metadata:

| Category | Rule |
|---|---|
| Market leader | #1–3 in industry by sales/earnings, earnings growth ≥20%, often 35–45%+ |
| Top competitor | #2/#3, can still produce strong gains riding the leader's draft |
| Institutional favorite | Mature blue-chip, low-mid teens growth — rarely produces superperformance, treat with caution |
| Turnaround | Require ≥100% recent-quarter YoY growth (against weak/negative prior comps), earnings/margins at or near new highs |
| Cyclical | **Inverted P/E logic** — high P/E near cycle bottom is bullish, low P/E near cycle top is bearish (opposite of growth stocks) |
| Laggard | Same group as a leader but weaker fundamentals — anti-pattern, avoid regardless of lower P/E |

**Sector strength layer**: track % of stocks in each sector making new highs — rising concentration = sector leadership signal, boosts individual candidate scores. A top sector stock breaking down badly is an early warning for the whole sector.

---

## Part 5 — Valuation Rules (Chapter 4)

- **Never use low P/E or low PEG as a hard entry filter.** The book explicitly shows this throws away most of history's biggest winners (many traded at 30–900x+ earnings before their big moves).
- **A very low P/E combined with a price near its 52-week low is a warning sign of trouble**, not a bargain.
- PEG ratio (P/E ÷ growth rate) is a **soft-score input only**, never standalone — it misjudges extreme-growth names and can make "broken leader" traps look attractive.
- **P/E expansion tracking on held positions**: superperformance runs typically see P/E expand ~2–3x from entry to peak. Once a held position's P/E has expanded to roughly 2.5–3x its value at entry, treat it as a weakness/exit watch signal.
- **Avoid the "broken leader" trap**: never buy a former leader just because it's fallen far and "looks cheap" — require fresh basing/re-acceleration, not just distance from highs.

---

## Part 6 — Entry Timing: VCP & Pivot Point (Chapter 10)

This is the most pattern-recognition-heavy part of the strategy — flag the harder pieces for a dedicated detection routine or AI/visual review rather than a simple boolean.

### Volatility Contraction Pattern (VCP)
- A healthy base shows **2–6 pullbacks (usually 2–4), each roughly half the size of the last** (e.g., 25% → 15% → 8%)
- Base duration: **~3–65 weeks** — anything forming in under ~3 weeks ("time compression") is high-risk, insufficient time to shake out weak holders
- **Volume should contract at the final, tightest stage** (below the 50-day average) — signals selling has genuinely dried up

### Correction depth ceiling
- Most valid setups correct **10–35%** peak to trough
- Up to **~50%** tolerable in a genuine bear-market correction
- **>60% = high failure risk**, generally avoid — too much "overhead supply" (trapped sellers waiting to break even)
- Relative check: a stock correcting **more than 2–3x the general market's decline** over the same period should generally be avoided

### The pivot point (the actual buy trigger)
- Pivot = high of the final, tightest contraction (or high of the base for a simple flat base)
- **Buy only when price actually clears the pivot**, ideally on volume meaningfully above average (examples: 300–1000%+ of average on breakout day)
- **Never buy in anticipation** of a breakout — wait for confirmation

### Post-breakout health check
- Must hold above the **20-day moving average**
- "Squat" (breaks pivot intraday, closes back inside range) — not an automatic fail; give up to **~10 trading days** to recover as long as stop and 20-day MA hold
- Early-day reversal (morning spike fades by midday) — give it until end of day unless the hard stop is hit

### Shakeouts (bullish, not automatically bearish)
- Price briefly undercutting an obvious prior support level before recovering = constructive — flushes stop-loss sellers. Look for 1–3 within a base as added confirmation.

### The "Turn" — don't buy a trendline break alone
1. Downtrend → 2. Attempted recovery (**don't buy yet** — trendline breaks are often false) → 3. Pause/plateau (ideally with a shakeout) → 4. Breakout above the pause high = **actual buy trigger**

### Fundamentals-pass ≠ buy signal
A stock can pass every fundamental and Trend Template check and still not be a buy **today** — the technical pivot breakout is the actual trigger. Track a `price_ready` status separately from fundamentals-pass; only buy when both are true together.

### Power Play (separate momentum-only sub-strategy — the one exception to requiring fundamentals)
1. Explosive move ≥100% in <8 weeks on huge volume, from prior dormancy
2. Sideways consolidation correcting no more than 20–25% over 3–6 weeks
3. Final tight consolidation correcting no more than ~10%, or standard VCP characteristics
Build as an explicitly separate, clearly-labeled strategy variant.

---

## Part 7 — Risk Management: Stop-Loss (Chapter 12)

**The single most important rule in the entire book.**

- **Hard maximum stop-loss: 10% per position.** No exceptions, regardless of market cap, "quality," or conviction.
- **Target average realized loss: 6–7%** — most losses should be cut before ever reaching the 10% ceiling.
- **Proof it matters more than stock-picking**: the author capped his own real historical losses at 10% with nothing else changed — compounded return went from **-12.05% to +79.89%** on the exact same trades.
- **Predetermine the stop before entry, write it down, execute without hesitation** when hit — no "wait for the next rally to sell."
- **Handle slippage immediately**: if price gaps through the stop, sell at the next available price — don't wait for a bounce back to the original level.
- **No stock is safe enough to skip this** — real historical examples of "quality" names falling 70–99% and taking a decade+ to recover (or never recovering) are cited explicitly.

---

## Part 8 — Risk Management: Profit Protection & Position Management (Chapter 13)

- **Once unrealized gain reaches ≥3x the original stop distance, move the stop to at least breakeven.** (Bought at $50 with a $2.50/5% stop → at $57.50, move stop to ≥$50.)
- **Never average down.** Adding to a losing position is explicitly condemned — a stock that's fallen is *less* attractive, not more. No size increase on any position currently below entry, ever.
- **Scaling in is different from averaging down**: only add to a position **after** it shows a profit, never after a loss.
- **Losing-streak protocol**: diagnose cause (flawed criteria vs. hostile market), then scale position size **down** in steps — never trade bigger to "recoup." Scale back up only once performance normalizes.
- **Re-entering from cash**: start with small "pilot" positions, increase size only after early trades confirm.
- **Don't widen stops for volatile stocks or tough markets — tighten them.** The book's own compounding math shows widening risk tolerance while win rate is falling accelerates the path to negative returns.
- **Tough-market playbook** (activate as a "defensive mode," not a permanent setting):
  - Tighten stop-loss (e.g., 7–8% → 5–6%)
  - Take profits smaller/sooner (e.g., 15–20% target → 10–12%)
  - Cut position sizes and overall exposure
  - Loosen back to normal only once win rate/risk-reward improves

---

## Part 9 — Position Sizing & Portfolio Concentration (Chapter 13)

- **Concurrent positions: 4–6 for a smaller account, up to 10–12 for larger, hard ceiling ~20.**
- **Diversification does not protect you** — in a real market-wide decline, most things fall together anyway; over-diversifying just guarantees mediocre, averaged-out results and makes it harder to track positions or react quickly.
- **When more candidates qualify than available slots, take the strongest-ranked first** (Ch. 9's "buy the strongest first") — don't spread capital thin across everything that passes.
- **Target win/loss size ratio: 2:1 minimum, aim for 3:1.** At 2:1, profitable even at a 33% win rate; at 3:1, profitable even at 40%. Track this explicitly — win rate alone is not a sufficient success metric.

---

## Part 10 — Exit Rules Beyond the Stop-Loss (Chapters 5, 8, 9)

- **Largest single-day or single-week price decline since the position's advance began, on heavy volume → exit-candidate flag**, even right after a "good" earnings report. Price action is trusted over headline fundamentals.
- **Price reaction quality around earnings**: a report that pops the stock but then sells off hard and can't recover is a warning regardless of the numbers.
- **P/E expansion ≥2.5–3x since entry** on a held position → weakness/exit watch signal.
- **A stopped-out position is not permanently blacklisted** — it re-enters the normal scanning universe next cycle; second/third setups are sometimes stronger than the first.

---

## Part 11 — Explicit Anti-Patterns (never do these)

- ❌ Buying because a stock "looks cheap" (low P/E, low PEG, far below its high) without a confirmed technical trend
- ❌ Averaging down on any losing position
- ❌ Widening a stop-loss because a stock is "volatile" or the market is "difficult"
- ❌ Buying a stock still in Stage 1 or Stage 4 (no matter how good the fundamentals)
- ❌ Buying in anticipation of a pivot breakout instead of waiting for confirmation
- ❌ Treating a fundamentals-only pass as a buy signal without technical confirmation
- ❌ Over-diversifying beyond ~20 positions "for safety"
- ❌ Holding a losing position specifically to "get back to even" rather than evaluating it fresh against other opportunities
- ❌ Skipping the stop-loss on any position because it's a "quality" or large-cap name

---

## Quick-Reference Numeric Cheat Sheet

| Rule | Value |
|---|---|
| Max stop-loss | 10% (target avg 6–7%) |
| Move stop to breakeven | At ≥3x original risk in profit |
| Price above 52-week low | ≥30% |
| Price within 52-week high | ≤25% away |
| Relative strength percentile | ≥70 (80s–90s ideal) |
| Recent-quarter EPS growth floor | ≥20–25% |
| Code 33 window | 3 consecutive quarters |
| VCP contraction count | 2–6 (usually 2–4) |
| Base duration | ~3–65 weeks |
| Correction depth (favorable) | ≤35% |
| Correction depth (avoid) | >60% |
| Concurrent positions | 4–6 small / 10–12 large / 20 hard ceiling |
| Target win:loss ratio | 2:1 min, 3:1 target |

---
*Source: original analysis derived from all 13 chapters (see `ch01-notes.md` through `ch13-notes.md` and `00-INDEX.md` for full detail and reasoning behind each rule).*
