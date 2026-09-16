# Minervini Book Notes — Master Index
*Chapter-by-chapter analysis of "Trade Like a Stock Market Wizard" (Mark Minervini), reworded and reorganized around Kashif's design. Not a reproduction of the book — original analysis and rule extraction, mapped to our own strategy schema.*

| # | Chapter | What it gives Kashif |
|---|---|---|
| 1 | An Introduction Worth Reading | Mindset only — risk-first thinking, no numeric rules |
| 2 | What You Need to Know First | Mindset — cut losses without ego; float-size seed idea |
| 3 | Specific Entry Point Analysis (SEPA) | **The pipeline shape itself** — validates our hard_filter → soft_score → AI-synthesis design independently |
| 4 | Value Comes at a Price | P/E and PEG usage rules (soft input only, never a hard filter) |
| 5 | Trading with the Trend | **⭐ The Trend Template — our core hard_filter (8 criteria)** |
| 6 | Categories, Industry Groups, Catalysts | Company/sector tagging layer, cyclical-stock exception |
| 7 | Fundamentals to Focus On | **⭐ Earnings/sales growth + acceleration thresholds** |
| 8 | Assessing Earnings Quality | **⭐ "Code 33" composite signal**, earnings-quality red flags |
| 9 | Follow the Leaders | Market-regime detection via leading stocks, max-drawdown ceiling |
| 10 | A Picture Is Worth a Million Dollars | **⭐ VCP pattern + pivot point — entry timing mechanics** |
| 11 | Don't Just Buy What You Know | IPO/primary-base rules (narrow, optional module) |
| 12 | Risk Management Part 1 | **⭐ The 10% hard stop-loss — validated with real before/after numbers** |
| 13 | Risk Management Part 2 | **⭐ Position sizing + portfolio concentration — answers our open items** |

---

## The Master Rule Set — pulled together across all 13 chapters

### 1. Universe / Market Regime Gate (before anything else runs)
- Check overall market regime using **leading-stock behavior** (Ch. 9): ratio of new 52-week highs to new lows, whether pullbacks in top stocks are shallow (3–10%) — not just "is the index up."
- **>90% of superperformance phases begin as the general market exits a correction/bear market** (Ch. 3) — this is a legitimate top-level kill switch: if the regime signal is bad, don't run entries at all.

### 2. Hard Filter — Trend Template (Ch. 5), all 8 required
Price above 150-day & 200-day MA · 150-day MA above 200-day MA · 200-day MA rising ≥1 month · 50-day MA above 150/200-day MA · price above 50-day MA · price ≥30% above 52-week low · price within 25% of 52-week high · relative-strength percentile ≥70 (needs an EGX-specific version, since we don't have IBD's RS Rating).

### 3. Fundamentals Screen (Ch. 7–8, soft-scored, not one giant AND-gate — per Ch. 3's advice, split into grouped sub-screens)
- Recent-quarter YoY EPS growth ≥20% floor, reward 30–40%+
- Earnings acceleration flag (growth rate itself increasing, 2-quarter rolling average)
- Revenue growth confirming earnings growth
- **"Code 33"**: 3 consecutive quarters of simultaneous EPS + sales + margin acceleration → strong boost
- Deceleration flag: current growth rate meaningfully below the stock's own trailing pace
- Estimate revisions / surprise magnitude: optional, best-effort (known EGX data gap)

### 4. Category & Sector Tagging (Ch. 6)
Tag each candidate: market leader / top competitor / institutional favorite / turnaround / cyclical / laggard. Cyclicals get inverted P/E logic. Sector relative-strength (% of sector making new highs) boosts individual scores.

### 5. Entry Timing — VCP / Pivot Point (Ch. 10)
- Base with 2–6 contractions, each roughly half the size of the last, duration ~3–65 weeks
- Correction depth ceiling: prefer ≤35%, caution 35–50%, avoid >60%
- Volume dries up at the final contraction (below 50-day avg), then expands sharply on breakout
- Buy trigger = price clears the pivot (high of final contraction), not before
- Post-breakout health check: must hold above the 20-day MA
- `price_ready` flag (technical trigger) gates entry on top of the fundamentals pass — fundamentals passing alone is never a buy signal

### 6. Risk Rules (Ch. 12–13, non-negotiable, code-enforced)
- **Hard stop-loss: max 10% per position**, target average realized loss ~6–7%
- Once unrealized gain ≥3x the original stop distance → move stop to breakeven
- **Never average down** — no size increase on any position currently below entry
- Losing-streak protocol: scale position size down in steps; scale back up only after performance normalizes
- Re-entering from cash: start with small "pilot" positions, scale up only after early confirmation

### 7. Position Sizing & Portfolio Concentration (Ch. 13 — resolves two of our open project items)
- **4–6 concurrent positions** for a smaller account, up to **10–12** for larger, **hard ceiling ~20**
- When more candidates qualify than available slots: **take the strongest-ranked first** (Ch. 9), don't spread thin across all of them
- Target win/loss size ratio: **2:1 minimum, aim for 3:1** — track this explicitly as a portfolio stat, not just win rate

### 8. Exit Rules (Ch. 5, 8, 9, 12)
- Largest single-day/week price decline since the position's advance began, on heavy volume → exit-candidate flag, regardless of headline "good" earnings
- Price reaction quality around earnings dates (holds gains vs. sells off and can't recover)
- P/E expansion ≥2.5–3x since entry on a held position → weakness/exit watch signal

---

## What still needs a decision or more work
- **EGX-specific relative-strength percentile** — we don't have IBD's RS Rating; need to compute our own cross-sectional percentile rank.
- **VCP/pivot pattern detection is genuinely hard to fully proceduralize** — recommend a dedicated Python pattern-detection routine for the numeric parts (contraction sequence, volume dry-up, breakout volume) and treat the qualitative "is this really a clean cup-with-handle" judgment as a candidate for the `ai_context_review` stage, not a hard filter.
- **Estimate revisions / earnings-surprise-magnitude data**: likely unavailable at depth for EGX — keep optional.
- **Power Play (Ch. 10)** — the one setup type that trades on pure momentum without fundamentals confirmed. Worth building as an explicitly separate, clearly-labeled sub-strategy, not folded into the main pipeline.

---
*Individual chapter files (ch01–ch13) contain the full detail behind each row above.*
