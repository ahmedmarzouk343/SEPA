# Kashif — Implementation Plan: Book Alignment

*Three categories: things to fix (built wrong vs book), things to remove
(invented with no book basis and no real impact), engineering additions
(keep but make loose, not restrictive). Priority order within each category.*

---

## Category A — Fix: Built Different From Book

### A1 — Fundamentals Q2: Single-quarter → 2-quarter rolling average
Book (ch07): "smooth quarter-to-quarter growth using a 2-quarter rolling average"
Built: current_quarter_growth > prior_quarter_growth (single comparison)
Fix: avg of last 2 quarters vs avg of prior 2 quarters
Impact of not fixing: single volatile quarter passes or fails incorrectly

### A2 — Fundamentals: Deceleration must fail Q2
Book (ch07): "material slowdown in growth rate is a real warning sign"
Built: removed entirely in v0.27
Fix: Q2 fails if avg_growth_recent_2q < avg_growth_prior_2q (decelerating)
Impact of not fixing: slowing-growth stocks pass when book says they should fail

### A3 — Fundamentals Q4: Annual EPS check never built
Book (ch07): "strong annual EPS growth should back up quarterly pattern.
Breakout year: current-year EPS breaking above multi-year (2-4yr) range"
Built: nothing
Fix: Q4 = annual EPS growing YoY. If data unavailable: SKIPPED (not failed).
Log BREAKOUT_YEAR flag if current year exceeds prior 3-year high.
Impact of not fixing: stocks with strong quarters but declining annual trend pass

### A4 — Pilot size on reentry: 75% → 50%
Book (ch13): "small pilot positions first"
Built: 75%
Fix: 50% — 75% contradicts "small pilot"
Impact of not fixing: nearly full capital deployed on reentry immediately

### A5 — Breakout volume: 1.2× → 1.4×
Book (ch10): "volume meaningfully above average — examples show 300-1000%+"
Built: 1.2× (changed from 1.4× as profit-first decision)
Fix: restore to 1.4×. Flag as calibration parameter.
Impact of not fixing: weak-volume breakouts admitted without institutional confirmation

### A6 — Losing streak size reduction: removed, must be restored
Book (ch13): "reduce position size in steps (40% → 20%) during losing streaks"
Built: removed entirely in v0.27
Fix: restore — after 3 consecutive stops → 40%, after 5 → 20%
Recovery: after 1 profitable trade at reduced size → step up one level
Triggers are calibration parameters, not book-given numbers
Impact of not fixing: full size through extended losing streaks — contradicts explicit book rule

### A7 — Catalyst STRONG_POSITIVE: remove
Book (ch03): catalyst is confirmatory context, not a ranking mechanism
Built: STRONG_POSITIVE boosts Scoring Queue ranking
Fix: remove STRONG_POSITIVE. Two states only: STRONG_NEGATIVE (block) and NEUTRAL (proceed)
Impact of not fixing: stocks ranked higher based on invented scoring the book never describes

### A8 — Catalyst 90-day window: remove
Book (ch03): no time window stated
Built: 90-day hard boundary
Fix: use most recent available catalyst information — no time boundary
Impact of not fixing: valid catalysts older than 90 days silently ignored

---

## Category B — Remove or Simplify: Invented, Minor Impact

### B1 — Catalyst HIGH/MEDIUM/LOW scoring tiers → relevance filter only
What: ArabFinance disclosure categories mapped to scoring tiers
Book basis: none
Fix: remove scoring. Keep as a relevance pre-filter only — skip purely
administrative notices that cannot contain negative catalysts
Impact of removing: minimal — LOW-priority disclosures were auto-NEUTRAL anyway

### B2 — Multiplicative stacking → minimum
What: defensive_mode × losing_streak multiply (e.g. 0.5 × 0.40 = 0.20)
Book basis: none — book describes each mechanism separately
Fix: take the minimum of the two, not the product
Impact: simpler, less punitive, no book basis for compounding

### B3 — Recovery trigger: 2 consecutive winners → 1 profitable trade
What: 2 consecutive profitable trades at reduced size steps back up
Book basis: book says "once performance normalizes" — no specific trigger
Fix: change to 1 profitable trade — more permissive, matches "normalizes"
Impact: faster return to normal sizing after a losing streak

### B4 — Tick-quantized pre-filter → warning flag only
What: stocks with fewer than 20 unique closing prices excluded from VCP
Book basis: none — engineering discovery from TRTO data
Fix: change from hard exclusion to warning flag in Decision Receipt
Log LOW_PRICE_GRANULARITY and continue. Liquidity Lock handles sizing.
Impact: TRTO-like stocks still rejected by Liquidity Lock, not by this filter

---

## Category C — Engineering Additions: Keep But Make Looser

### C1 — ATR-scaled VCP prominence (ATR_MULTIPLIER = 1.0)
Action: no change needed — already permissive

### C2 — 5-day rolling median pre-smoothing
Action: no change needed — already permissive

### C3 — Dual timeframe weekly/daily
Action: no change — confirm T0-B fix (single-contraction base passes) still in place

### C4 — Monotonicity tolerance: 1.30 → 1.50
What: no VCP step may exceed 1.30× the prior step's depth
Loosen: increase to 1.50 — "roughly halving" allows more variation
Impact: more real VCP patterns accepted, some noisier ones too

### C5 — Leader divergence threshold: 50% → 40%
What: regime gate requires >50% of leaders showing higher lows
Loosen: reduce to 40% — still a meaningful signal, less restrictive
Impact: regime gate opens more often, more trade opportunities

### C6 — Leader pullback duration: 10 → 15 trading days
What: pullback must occur within 10 trading days of local high
Loosen: increase to 15 trading days — 3 calendar weeks, still "days not weeks"
Impact: more leader pullbacks qualify, regime gate opens more

### C7 — 60-day filing lag
Action: do not loosen — this is a validity requirement, not a restriction

### C8 — Arabic + English news search
Action: no change — already permissive (missing names = skip, not fail)

### C9 — Three edge case rules
Action: no change — already permissive (produce NEUTRAL, not block)

### C10 — Trailing stop buffer: 3% → 5% below 50-day MA
What: trailing stop sits 3% below 50-day MA
Loosen: increase to 5% — more room before exit fires, lets winners run longer
Impact: fewer premature exits on brief dips below the MA

---

## Implementation Priority

### Priority 1 — Fix before next backtest

| # | Change | File |
|---|---|---|
| A1 | Q2: 2-quarter rolling average | fundamentals_screen.py |
| A2 | Q2: Deceleration fails | fundamentals_screen.py |
| A3 | Q4: Annual EPS check | fundamentals_screen.py |
| A6 | Losing streak: restore | kashif_strategy.py |
| A5 | Breakout volume: 1.4× | vcp_detection.py |
| A7 | Catalyst: remove STRONG_POSITIVE | catalyst_check.py |
| A8 | Catalyst: remove 90-day window | catalyst_check.py |

### Priority 2 — Loosen engineering additions

| # | Change | File |
|---|---|---|
| C4 | Monotonicity 1.30 → 1.50 | vcp_detection.py |
| C5 | Leader threshold 50% → 40% | market_regime_gate.py |
| C6 | Pullback duration 10 → 15 days | market_regime_gate.py |
| C10 | Trailing buffer 3% → 5% | kashif_strategy.py |
| B2 | Stacking: multiply → minimum | kashif_strategy.py |
| B3 | Recovery: 2 wins → 1 win | kashif_strategy.py |
| B4 | Tick filter: hard → warning | vcp_detection.py |

### Priority 3 — Remove and simplify

| # | Change | File |
|---|---|---|
| B1 | Catalyst tiers: scoring → filter | catalyst_check.py |
| A4 | Pilot size: 75% → 50% | kashif_strategy.py |

### Priority 4 — Update docs and JSON config

Files to update:
- minervini_sepa_v1_strategy_config.json — bump version, record all changes
- feature-02-fundamentals-screen-rules.md
- feature-03-market-regime-gate-rules.md
- feature-05-entry-timing-rules.md
- feature-06-catalyst-check-rules.md

---

## What Does NOT Change

All of these are book-faithful and stay exactly as is:

- All 10 Trend Template conditions
- Hard stop 10% ceiling
- Breakeven at 3× gain
- No averaging down
- Distribution bar as primary exit (largest decline + volume)
- Stage 3 transition (200-day MA break on volume)
- VCP: contraction count 2-6, pivot = high of final contraction
- Post-breakout: 20-day MA failure, squat 10 days
- Regime gate OR logic
- P/E expansion watch at 2.5×
- Defensive mode concept
- Arabic + English news search
- Track record logging

---

## Change Log

- v1 — complete plan. Three categories: 8 fixes (book-stated differently),
  4 removes/simplifications (no book basis, minor impact), 10 engineering
  additions made looser (permissive, not restrictive).
