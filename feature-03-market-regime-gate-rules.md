# Kashif — Engineering Rules: Market Regime Gate (Feature 3)

*Source of truth for Claude Code on this feature. Supersedes verbal instructions given in chat — if chat and this file disagree, this file wins until it's explicitly updated. Living document; update it when something new is found, don't just remember a verbal correction.*

**Status:** Ready to build. First review of this block in the project's history (v0.13), corrected against the book directly, then hardened against real edge cases (v0.14, v0.15). No open design decisions remain.

---

## 0. What this document is for

Same relationship as Features 1 and 2: this is the corrected, fully-specified spec for `market_regime_gate`, plus the rules for proving the code implements it correctly. Runs **first** in `pipeline_order` — before `hard_filter` — even though it's the third feature built.

---

## 1. Source of truth for the rule itself

1. `minervini_sepa_v1_strategy_config.json` → `market_regime_gate` block, as corrected below (v0.15)
2. `MANIFESTO.md` Part 1
3. `ch09-notes.md` — full reasoning, especially the three book signals this gate is built from
4. `ch03-notes.md` — the ">90% of superperformance phases begin as the market exits a correction" framing that justifies treating this as a high-conviction gate, not a loose one

---

## 2. The three conditions, as corrected

All three must be true simultaneously (**AND-gate**, corrected from an original OR-gate — see Section 2.1).

### 2.1 Gate logic: AND, not OR

The original spec opened the gate if *any* one condition was favorable. Corrected: these are three complementary confirmations of **one** underlying regime state, not independent tests where any single one proves health — same reasoning `MANIFESTO.md` Part 3 uses to justify `hard_filter`'s 8-condition AND-gate. An OR-gate would let one favorable signal open the gate while the others actively disagree, understating how high-conviction the book treats this prerequisite.

### 2.2 `new_high_low_ratio_favorable`

```
ratio[t] = count(52wk_high)[t] / (count(52wk_low)[t] + 1)
condition: ratio[t] > ratio[t-21]
```

- The `+1` in the denominator is a deliberate fix, not an approximation of the book: `count(52wk_low)` can legitimately be zero on a strong day, which would otherwise make the ratio undefined. Minimal distortion, standard practice.
- `t-21` matches `tt_4`'s `SLOPE_MIN_DURATION` exactly (~1 month), reused for consistency — the book doesn't specify an exact window for this particular ratio, so this reuses an existing, already-justified convention rather than inventing a second unexplained number.
- This is a **two-point comparison**, not a monotonic-increase-every-day check — same clarification `tt_4` needed. Confirm this is what gets implemented; don't assume.

### 2.3 `leader_pullback_shallow`

- **Leader definition**: top decile by RS percentile (`RS ≥ 90`), reusing `tt_9`'s already-built `relative_strength_computation` — not a separate ranking system.
- **Rule**: `pullback_depth ≤ 10%` **AND** `days_since_local_high ≤ 10 trading days`. Both required — the book describes this signal as "brief (days, not weeks) **and** shallow," and the original spec only checked depth.
- `10 trading days` is an interpretation of "days, not weeks" (two trading weeks), not a book-given number — flagged as such, defensible but not literal.
- **"Local high" window: 20 days.** This was implemented as 21 in an early build (a stale artifact, most likely bled over from `new_high_low_ratio_favorable`'s unrelated `t-21` lookback in the same editing session) — confirmed and corrected. 20 days reuses the window already established for `leader_divergence`'s higher-low check (Section 2.4); neither number is book-derived, but reusing an already-justified one beats inventing a third.
- **Tie-breaking on `days_since_local_high` — real bug, must be handled explicitly**: if a stock's price is flat at its peak for multiple consecutive days before pulling back, "days since the local high" must count from the **most recent** day at that peak, not the first. A naive `argmax()` over the rolling window returns the first occurrence on a tie, which overstates the duration — a stock with a genuinely recent, shallow pullback could incorrectly fail the ≤10-day check purely from this artifact. **Fix**: reverse the window before taking `argmax`, so ties resolve to the most recent occurrence. This is not a hypothetical edge case for this project — `STATUS-technical-thread.md` already documents `NDRL` by name as a thin/flat-trading EGX ticker, and sparse EGX names with repeated identical closes are exactly the condition that triggers this.

### 2.4 `leader_divergence`

The book's own wording (`ch09-notes.md`) is directional, not magnitude-based: *"leading stocks making higher lows while the general index is still making lower lows."* Two simultaneous clauses — build it as two direct checks, not a percentage-point gap (a gap-based version was tried and rejected — see Section 2.7's note on process).

```
per-stock higher_low[t] = low_20d[t] > low_20d[t-20]   (same "compare a rolling stat to itself N days earlier" pattern as tt_4)

leader_condition   = (% of RS>=90 leader basket with higher_low[t]=True) > 50%
universe_condition = (% of full universe with higher_low[t]=True) < 50%

leader_divergence = leader_condition AND universe_condition
```

- `50%` is a natural majority/plurality pivot (is this basket net-positive or net-negative on this stat), not an invented magnitude gap — a different *kind* of number than an earlier-considered 15-percentage-point threshold, not just a smaller version of it.
- **Known simplification, not a bug**: "the general index" in the book's wording is proxied here by full-universe breadth, since no separate EGX benchmark index series is in the current data pipeline. Document this clearly in code — it's a deliberate v1 simplification, not the book's fuller concept, and not full swing-low pattern detection either (`ch10-notes.md` already flags that as genuinely hard to proceduralize).

### 2.5 Leadership basket must be recomputed fresh every cycle

`MANIFESTO.md` Part 1, direct requirement: *fewer than 25% of one cycle's leading stocks/sectors lead the next cycle.* The RS≥90 leader basket used in 2.3 and 2.4 must be recomputed from the live universe every single cycle — never cached, never biased toward a prior cycle's membership. This is an implementation requirement, not a scoreable condition, but a caching bug here would be invisible in testing and wrong in production. Test for it explicitly (Section 3).

### 2.6 Process note on `leader_divergence`'s threshold

An earlier draft of this condition used a magnitude-gap threshold (leader% exceeds universe% by a fixed number of percentage points). That version is superseded — the book's own wording is directional (two simultaneous clauses), not magnitude-based, so the directional formulation in Section 2.4 is the one to build. If you encounter any reference to a percentage-point gap version of this condition elsewhere, it's stale.

---

## 3. Testing standard

Same discipline as Features 1 and 2 (known-answer fixtures, predictions written before running code, no circular verification, wrong predictions left visible with a correction note, no narrative-only reports).

Feature-specific requirements:

- **Fixture 1 — `new_high_low_ratio_favorable` in isolation**: synthetic daily counts of 52-week-high/low stocks across a fake universe, over at least 22+ days, including at least one day where `count(52wk_low) = 0` (to confirm the `+1` fix actually prevents a crash/undefined result, not just in theory). Hand-calculate the ratio at `t` and `t-21` before running code.
- **Fixture 2 — `leader_pullback_shallow`**: synthetic price series for a stock tagged as a leader (RS≥90), with a controlled pullback. Build at least **four** sub-cases: passes both depth and duration; fails depth only (>10%, ≤10 days); fails duration only (≤10%, >10 days); and **a price-plateau case** (the local high held flat for several consecutive days before the pullback began) — confirms `days_since_local_high` counts from the most recent day at the peak, not the first. This last case is required, not optional: it's the exact scenario that caused a real bug to slip past an earlier version of this test file entirely.
- **Fixture 3 — `leader_divergence`**: a synthetic leader basket and a synthetic universe with known, hand-counted higher-low percentages straddling the 50% pivot on each side independently (e.g., leader basket at 60% higher-low, universe at 35% higher-low → should pass; leader basket at 45% → should fail even if universe is favorable, to prove both conditions are actually checked, not just one).
- **Fixture 4 — full gate AND-logic**: at least one case where 2 of 3 conditions pass and 1 fails, confirming the overall gate stays closed — this is the direct test of the OR→AND correction actually being real in the code, not just in the JSON. This is the single highest-value test in this feature, since it's the corrected bug with the most consequence if it regresses.
- **Fixture 5 — leader basket freshness**: confirm the basket is recomputed, not cached, across two different synthetic "cycles" with deliberately different top-decile membership. A caching bug would pass every other fixture and only show up here.

---

## 4. Deliverables checklist

- [ ] `market_regime_gate.py` (or equivalent) implementing all three conditions as separately callable/testable functions, plus the AND-gate combinator
- [ ] Leader-basket computation reuses `tt_9`'s existing `relative_strength_computation`/RS-percentile function — not a duplicated ranking implementation (same "one canonical implementation" standard already enforced for `compute_rs_percentile`)
- [ ] Leader basket recomputed fresh every cycle, with an explicit test proving this (Fixture 5) — not just assumed from the code reading correct
- [ ] Known-answer test file covering all 5 fixtures in Section 3, predictions written before running, corrected in place (not erased) if any are wrong
- [ ] Updated `minervini_sepa_v1_strategy_config.json` if anything discovered during implementation requires a spec correction — keep the two files in sync, same standard as Features 1 and 2

---

## Change Log

- v1 (superseded, never distributed as final) — first draft, written at JSON v0.13. Used a 15-percentage-point magnitude-gap threshold for `leader_divergence`.
- v2 — rewritten against JSON v0.15. Replaces the magnitude-gap threshold with the directional formulation matching the book's literal two-clause wording (Section 2.4), and adds the exact two-point ratio comparison and division-by-zero fix for `new_high_low_ratio_favorable` (Section 2.2) that v1 predated. This is the version to build against.
- v3 — two corrections after the first real implementation. (1) Confirmed and fixed the 21-vs-20-day window discrepancy between this doc and the JSON (20 is correct). (2) Added the `days_since_local_high` tie-breaking fix (Section 2.3) — a real bug found through independent testing beyond the delivered fixture suite, directly relevant given `NDRL`'s already-documented thin/flat EGX trading pattern. Added a required plateau sub-case to Fixture 2 so this stays covered going forward.

---

## v4 Update — Profit-First Principle Applied

**Gate logic changed from AND to OR.**

The original spec required all three conditions simultaneously. The book
(ch09-notes.md) describes three signals to watch, not three simultaneous
requirements. One confirming signal is sufficient to begin evaluating
individual stocks.

```
OLD: gate_open = ratio_favorable AND pullback_shallow AND divergence
NEW: gate_open = ratio_favorable OR pullback_shallow OR divergence
```

Effect: dramatically increases regime-open bars, increases trade
opportunities. The regime gate was the single tightest constraint in
the pipeline — the S&P 500 backtest showed only 31 open bars with AND
logic. OR logic will open significantly more.

**Change Log v4**: AND → OR gate logic. Profit-first principle —
within book rules, take the more aggressive option.
