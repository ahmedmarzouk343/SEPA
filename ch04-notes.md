# Chapter 4 — "Value Comes at a Price"
*Notes and analysis (not book text). Chapter's core argument: P/E ratio is a weak filter on its own — important for us to get right, since it's tempting to build a naive "low P/E = good" screen that this chapter explicitly argues against.*

## Core argument
- **P/E ratio alone has almost no predictive value** for finding superperformance stocks. Low P/E ≠ cheap/safe; high P/E ≠ overvalued/risky. Many of the biggest winning stocks in history had P/E ratios of 30–900+ *before* their biggest gains.
- **A very low P/E, especially combined with a stock near its 52-week low, is a warning sign of trouble**, not a bargain — the market may be correctly pricing in a real business problem.
- **Earnings growth rate matters far more than the P/E number itself.** If a company keeps growing earnings fast enough, the P/E "takes care of itself" even if it started high.

## ⚠️ Important design implication for Kashif
**Do not build a hard filter like "P/E below X = pass."** The book explicitly argues this style of screening throws away many of the best candidates. If P/E is used at all in our hard filters, it should NOT be a simple "low P/E is good" rule.

## The PEG ratio (P/E ÷ earnings growth rate)
- Formula: `PEG = P/E ÷ projected EPS growth rate (%)`. Example: P/E of 20, growth rate of 40% → PEG = 0.5.
- Common interpretation: PEG < 1 → potentially undervalued; PEG > 1 → potentially overvalued. Further from 1 = stronger signal, either direction.
- **The author is skeptical of PEG too** — flags two real weaknesses: (1) it can't properly value extreme high-growth/newly-understood companies (like early Yahoo at a huge multiple), and (2) it can make "broken leader" stocks (past their peak, decelerating) look attractive when they're actually a trap.
- **Verdict for us**: PEG is a useful supporting number, not a standalone filter. Treat it as one input into the soft-score composite, not a hard gate.

## A genuinely useful, quantifiable signal: P/E expansion since entry
- Historical pattern: during a superperformance run, a stock's P/E typically **expands 100–200% (roughly 2–3x)** from the start of the move to its peak.
- **Actionable rule candidate**: once a held position's P/E has expanded to roughly **2.5–3x its value at entry**, treat this as a caution/watch signal — start looking for signs of deceleration or price weakness as a possible exit trigger. This is a genuinely mechanical, trackable number (not a hard sell rule, but a good soft-score input or alert condition for *held positions*, not entry screening).

## Anti-pattern to explicitly avoid: "the broken leader syndrome"
- Don't buy a former market leader just because it's fallen a long way from its highs and "looks cheap" now. A leader that has topped and broken down is usually correctly pricing in a real slowdown, not offering a discount.
- Math reminder baked into this: **percentage losses are asymmetric** — a stock down 75% needs a +300% gain just to get back to even. This is really a risk-management point (ties into Ch. 12–13) but is introduced here as the reason "buying the dip on a broken leader" is dangerous.
- **Design implication**: any strategy that considers buying a stock "off its highs" should check it's basing/re-accelerating (a real technical setup — Ch. 5/10 territory), not just "down a lot from peak."

## Relevance to Kashif
- **Do not use**: "low P/E" or "low PEG" as a hard entry filter.
- **Do use**: PEG as one soft-score input among several, not a gate.
- **New concrete rule candidate**: P/E expansion ratio (current P/E ÷ entry P/E) ≥ ~2.5–3x on a held position → weakness/exit watch signal.
- **New guardrail**: exclude "buying the dip on a broken leader" pattern — a stock far below its highs needs fresh basing/trend confirmation (from Ch. 5/10), not just distance-from-high, before being treated as a candidate.
