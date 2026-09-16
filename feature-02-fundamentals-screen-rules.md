# Kashif — Engineering Rules: Fundamentals Screen (Feature 2 — v3 Rebuild)

*Source of truth for Claude Code. Supersedes all prior versions of this file.*

**Status:** Rebuilt from scratch at v3. The original composite scoring system
was replaced after proving it could never pass any real stock (max achievable
score was 35, threshold was 65, due to data depth limitations in yfinance).

**Philosophy change**: profit-first within book rules. Where the book gives
options, take the more aggressive one that maximizes opportunity.

---

## 0. Why this was rebuilt

The original Feature 2 built a 6-sub-screen weighted composite requiring 5+
quarters of quarterly data. yfinance provides 5-7 quarters maximum, leaving
only 1-2 usable growth comparisons after the lookback window. Code 33 (3
consecutive accelerating quarters) was structurally impossible to confirm.
No stock in the S&P 500 or EGX backtest scored above 35 against a threshold
of 65. The screen was built before validating the strategy on real data.

The rebuild matches what the book actually states in ch07-notes.md — three
directional questions, not a weighted scoring system.

---

## 1. Source of truth

1. `minervini_sepa_v1_strategy_config.json` → `fundamentals_screen` block (v0.27)
2. `ch07-notes.md` — the direct source for all three questions
3. `ch08-notes.md` — earnings quality context (informational only, not scored)

---

## 2. The three questions — this is the entire fundamentals screen

### Question 1 — EPS growth ≥20% (REQUIRED)

```
most_recent_quarter_yoy_eps_growth >= 0.20
```

The most recent quarter's EPS compared to the same quarter one year ago
must show ≥20% growth. This is the book's stated minimum bar.

- Use Basic EPS if available, Diluted EPS as fallback
- If no EPS data available at all: SKIPPED (stock passes through)
- **Turnaround override**: if category_tag = turnaround, threshold raises
  to ≥100% (1.00) — book explicitly requires this for turnarounds coming
  off weak prior-year comparisons
- If Question 1 FAILS: stock fails the fundamentals screen immediately.
  Do not evaluate Questions 2 or 3.

### Question 2 — Earnings acceleration (SKIPPED if insufficient data)

```
current_quarter_yoy_growth > prior_quarter_yoy_growth
```

The most recent quarter's YoY growth rate must be higher than the prior
quarter's YoY growth rate.

- If only 1 quarter of data is available: SKIPPED (cannot measure
  acceleration without at least 2 data points — not failed)
- If Question 2 FAILS (2+ quarters available, growth is decelerating):
  stock fails the fundamentals screen

### Question 3 — Revenue confirmation (SKIPPED if data unavailable)

```
most_recent_quarter_yoy_revenue_growth > 0
```

Revenue must be growing YoY in the most recent quarter.

- If revenue data is unavailable (Mubasher fallback has no revenue):
  SKIPPED (not failed)
- If Question 3 FAILS: stock fails the fundamentals screen

---

## 3. Pass rule

```
PASS if: Q1=PASS AND Q2=(PASS or SKIPPED) AND Q3=(PASS or SKIPPED)
FAIL if: Q1=FAIL OR Q2=FAIL OR Q3=FAIL
```

---

## 4. What was removed and why

| Removed component | Why removed |
|---|---|
| Weighted composite (6 sub-screens, 0.25/0.20/0.15/0.20/0.10/0.10) | Required 5+ quarters — impossible with yfinance. Never passed any real stock. |
| 65-point pass threshold | Invented number, not in the book |
| Log-distance PEG modifier | Book says contextual note only, never standalone |
| Cross-source consistency checks | Theoretical concern, not a proven problem |
| Partial-data renormalization with 0.35 safeguard | Unnecessary with yes/no approach |
| Deceleration penalty formula | Replaced by: Q2 fails if current growth < prior growth |
| earnings_quality sub-screen | Book mentions checking for one-time items but never as a scored component |
| price_reaction_to_earnings sub-screen | Useful signal but not a book-required filter |
| Filing lag enforcement | KEPT — real lookahead bias protection |

---

## 5. Data fetching

Use `fundamentals_fetcher.py` with the correct suffix:
- EGX tickers: `suffix=".CA"`
- US tickers: `suffix=""` (no suffix)

Apply 60-day FRA filing lag — only use quarters whose filing deadline
has elapsed as of the current bar date. This is the one engineering
addition that must stay regardless of simplification.

---

## 6. Testing standard

Required fixtures:

- **Fixture 1 — Clean pass**: EPS +35% this quarter vs +28% last quarter,
  revenue +22%. Q1=PASS, Q2=PASS, Q3=PASS → PASS
- **Fixture 2 — Q1 fails**: EPS +15% (below 20% floor). Immediate FAIL,
  Q2 and Q3 not evaluated.
- **Fixture 3 — Q2 fails (deceleration)**: EPS +35% this quarter vs +48%
  last quarter. Q1=PASS, Q2=FAIL → FAIL
- **Fixture 4 — Q3 fails**: EPS +40% accelerating, but revenue -5%.
  Q1=PASS, Q2=PASS, Q3=FAIL → FAIL
- **Fixture 5 — Q2 skipped (only 1 quarter)**: only 1 quarter of EPS data
  available. Q1=PASS, Q2=SKIPPED, Q3=PASS → PASS
- **Fixture 6 — Q3 skipped (no revenue)**: Mubasher fallback, no revenue.
  Q1=PASS, Q2=PASS, Q3=SKIPPED → PASS
- **Fixture 7 — Turnaround override**: category=turnaround, EPS +85%.
  Q1=FAIL (85% < 100% turnaround threshold). FAIL.
- **Fixture 8 — Turnaround passes**: category=turnaround, EPS +120%.
  Q1=PASS (120% ≥ 100%). Continue to Q2, Q3.

---

## 7. Deliverables checklist

- [ ] Rebuild `fundamentals_screen.py` with the 3-question logic
- [ ] `fundamentals_fetcher.py` already has suffix parameter — no changes needed
- [ ] Update `kashif_strategy.py` — replace compute_composite() call with
  the new 3-question evaluate_fundamentals() function
- [ ] Known-answer test file covering all 8 fixtures
- [ ] Regression sweep — all existing test suites must still pass

---

## Change Log

- v1 — original composite scoring system (6 sub-screens, weighted scores)
- v2 — fixes to composite: PEG formula, turnaround curve, monotonicity
- v3 — REBUILT. Composite replaced with 3 yes/no questions from ch07-notes.md.
  Triggered by S&P 500 backtest confirming composite could never pass any real
  stock (max score 35, threshold 65, yfinance data depth limitation).
  Profit-first principle applied: simpler, works with available data, book-faithful.
