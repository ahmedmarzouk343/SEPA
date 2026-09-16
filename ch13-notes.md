# Chapter 13 — "Risk Management Part 2: How to Deal with and Control Risk"
*Notes and analysis (not book text). This chapter directly answers our two still-open project items — position sizing and portfolio-level allocation — with concrete numbers.*

## Four contingency plans (a checklist worth building into our ops runbook)
1. **Initial stop-loss** — set before entry, absolute, non-negotiable (Ch. 12's ~10% ceiling).
2. **The reentry** — getting stopped out doesn't permanently disqualify a stock. If it still meets criteria, it can be re-screened and re-entered later; second/third setups are sometimes stronger than the first. **Design implication**: a stopped-out position should return to the normal scanning universe next cycle, not get blacklisted.
3. **Selling at a profit** — needs its own explicit rule (below): protect gains once they reach a multiple of the original risk.
4. **The disaster plan** — operational resilience for black-swan events (data feed outage, fraud, exchange halt) — separate from normal market risk. Worth a basic version for Kashif: what happens if the data API goes down mid-cycle, what happens if a position gaps through the stop overnight.

## ⭐ Profit protection rule — precise, codeable trigger
- **Once an open position's gain reaches ~3x the original risk (the size of the initial stop-loss distance), move the stop to at least breakeven.** Example: bought at $50 with a $2.50 (5%) stop → once price reaches $57.50 (3× $2.50 gain), move stop to at least $50.
- After that, continue looking for opportunities to sell into strength and lock in more of the gain as it runs.
- **Directly codeable rule**: `if unrealized_gain >= 3 * initial_stop_distance: move_stop_to_breakeven_or_higher`.

## ⭐ Never average down — explicit, firm rule
- **Adding to a losing position ("averaging down") is explicitly condemned as one of the worst mistakes a trader can make** — "only losers average losers." A stock that's fallen after a correct entry is *less* attractive, not more, regardless of the lower price.
- **Scaling in ≠ averaging down**: the acceptable version is scaling into a position **only in the direction that's already proving correct** — i.e., adding to a position only after it shows a profit, never after a loss. "Never trust the first price unless the position shows you a profit" before adding more.
- **Directly codeable constraint**: our strategy engine should have a hard rule that forbids increasing position size on any ticker currently below its entry price.

## Losing-streak protocol — position-size scaling tied to recent performance
When a strategy hits a run of stopped-out trades, the response is **cause diagnosis + scale down**, never "trade bigger to make it back":
- Two possible causes: (1) the selection criteria are flawed, or (2) the general market environment has turned hostile.
- **Concrete scaling response**: reduce position size in steps (book's example: normal size → 40% of normal → 20% of normal, continuing down if losses persist), and **only scale back up ("pyramid") once performance normalizes.**
- Symmetrically, when **coming back from cash** after a correction/bear market, scale in gradually too — small "pilot" positions first, add more size only after early trades confirm the approach is working in current conditions.
- **This is a strong, concrete answer to our open "position sizing" item**: position size should be a function of recent realized performance (a rolling win/loss track record), not a fixed amount — scale down after losing streaks, scale up after winning streaks, always starting small when re-entering the market from cash.

## Why NOT to widen stops for "more volatile" stocks — a genuine mathematical argument
- Common advice says to give volatile stocks more room. **The author argues the opposite, backed by explicit return-math tables**: in difficult market conditions, batting average (win rate) tends to fall below 50%, and widening stop-loss tolerance while win rate is falling accelerates the path to negative expected returns — because losses compound geometrically against you (Ch. 12's asymmetry).
- **A striking finding from the book's own compounding tables**: at a fixed 2:1 win/loss *ratio*, doubling both numbers (e.g., from 20%/10% to 42%/21%) while win rate stays around 50% can turn a profitable system into a **losing** one over the same number of trades — the ratio alone isn't sufficient information; **absolute magnitude of the swings also matters**, because larger swings amplify the same geometric loss-asymmetry problem even at an identical ratio.
- **Concrete "tough market" playbook** (worth encoding as a distinct regime-adjusted rule set, not just a single fixed configuration):
  - Tighten stop-loss (e.g., from a typical 7–8% down to 5–6%)
  - Take profits smaller/sooner (e.g., from a typical 15–20% target down to 10–12%)
  - Cut position sizes and overall market exposure
  - Only loosen back to normal parameters once win rate/risk-reward improves again
- **Design implication**: our strategy config should support a "defensive mode" parameter set (tighter stops, smaller targets, smaller sizes) that activates based on recent realized batting average — not a single static rule set used at all times regardless of how the strategy is currently performing.

## ⭐ Portfolio concentration — direct numeric guidance for our "capital allocation" open item
- **Diversification is explicitly argued NOT to protect you** — in a real market-wide decline almost everything falls together, and over-diversifying actively hurts by (1) making it impossible to track each position closely, (2) slowing your ability to reduce exposure quickly when needed, and (3) mathematically guaranteeing only average/mediocre results (smoothing away the edge of a good selection process).
- **Concrete position-count guidance**: typically **4–6 concurrent positions** for a smaller portfolio, up to **10–12** for a larger one. **Hard ceiling: never more than ~20 positions** (which would already mean ≤5% per position if equally weighted).
- **Explicit sizing math for a "true 2:1 trader"**: optimal position size ≈ **25% of capital** (i.e., 4 roughly equal positions) — sized so a big winner actually moves the needle on total portfolio return.
- **Direct answer to our open "portfolio-level capital allocation when multiple strategies signal simultaneously" item**: the book's implicit answer is *concentration with a hard ceiling*, not broad diversification — prioritize the strongest-ranked candidates (Ch. 9's "buy the strongest first") up to the position-count ceiling, rather than spreading capital thin across every signal that fires.

## Relevance to Kashif — this chapter directly resolves two of our open project items
1. **Position sizing rule (previously unresolved)**: size positions dynamically based on recent realized performance — reduce after losing streaks, increase gradually after winning streaks, always start small when reactivating a strategy from a flat/cash state. Never add to a position currently below entry (no averaging down, ever).
2. **Portfolio-level capital allocation across simultaneous signals (previously unresolved)**: cap concurrent positions per strategy at roughly 4–12 depending on account size, hard ceiling ~20; when more candidates qualify than available slots, prioritize by signal strength/rank (reusing the Ch. 9 "buy strongest first" logic) rather than spreading thin across all of them.
3. **New profit-protection rule**: move stop to breakeven once unrealized gain reaches 3x the original stop distance.
4. **New regime-adjusted rule set**: a "defensive mode" (tighter stops, smaller profit targets, smaller size) that activates automatically when the strategy's own rolling win rate degrades — not a single fixed parameter set forever.
5. **Hard constraint for the strategy engine**: never increase size on a position currently at a loss.
