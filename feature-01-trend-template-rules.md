# Kashif — Engineering Rules: Trend Template Hard Filter (Feature 1)

*Source of truth for Claude Code on this feature. Supersedes verbal instructions given in chat — if chat and this file disagree, this file wins until it's explicitly updated. This is a living document; update it, don't just remember a newer verbal correction.*

**Status:** Active. First feature built — the testing standard here applies to it now and to every feature built after it.

---

## 0. What this document is for

This is **not** a spec for what the Trend Template does — that's already defined in `MANIFESTO.md` (Part 2) and `minervini_sepa_v1_strategy_config.json` (`hard_filter` block), and is not open to reinterpretation here. This document is the rules for **how Claude Code proves its own code is correct** before anyone — including Claude Code itself — treats the results as trustworthy.

---

## 1. Source of truth for the rule itself

Don't re-derive the 8 conditions from memory or from the book directly. Use these files, in this order:

1. `minervini_sepa_v1_strategy_config.json` → `hard_filter.conditions` — the literal, current, machine-readable spec (tt_1–tt_9)
2. `MANIFESTO.md` Part 2 — the human-readable version of the same 8 conditions
3. `ch05-notes.md` — full reasoning/context if a condition's intent is ambiguous

If the JSON and MANIFESTO ever disagree with each other, stop and flag it. Don't silently pick one.

---

## 2. Why known-answer tests exist (don't skip this reasoning)

Testing against real EGX stocks shows the code produces *plausible-looking* output. It does not prove the code is *correct*, because there's no independently-known right answer for a real stock. A known-answer test uses a price series we build ourselves, so the correct PASS/FAIL/NaN answer is known by hand-calculation before the code ever runs. The test result is never "is this a good stock" — it is only "did the code's answer match the answer already calculated independently."

---

## 3. Required test structure

Split into two tests, not one:

- **Test A — `test_trend_template_test_A.py`**: conditions tt_1 through tt_8b only (everything computable from one stock's own price/volume history: moving averages, 52-week high/low). Single synthetic series.
- **Test B — `test_trend_template_test_B.py`**: condition tt_9 only (relative strength percentile). Requires a small synthetic *universe* (8–10 series minimum) with deliberately different, known trailing-252-day returns — percentile ranking is cross-sectional and cannot be tested with one series.

Do not combine these into one fixture. tt_9 needs different data than tt_1–tt_8b.

---

## 4. Fixture construction rules

- **Zones must be explicit and documented in the file**:
  - Zone 1 — insufficient history → expect NaN/undefined (not FAIL) for every condition not yet computable
  - Zone 2 — sufficient history, deliberately failing → expect real FAIL
  - Zone 3 — deliberately passing → expect PASS on all conditions simultaneously
- **Don't assume a rise "comfortably" flips a slow condition.** Before writing any predicted answer for tt_3/tt_4 (the 200-day MA and its slope), hand-calculate the actual SMA values at the specific days being compared. If the rise isn't long/steep enough to flip it, adjust the fixture — don't adjust the prediction to match a weak fixture.
- **Zone 1 and Zone 2 prices must connect continuously.** Zone 1's prices still feed Zone 2's moving averages once those averages become defined. No artificial jump at a zone boundary that isn't part of what's being tested.
- **For tt_8a (≥30% above 52-week low)**: explicitly confirm by calculation that the fixture's minimum price falls inside the correct trailing 252-day window as measured from the test's final day, and that the final price clears it by ≥30%. Don't assume a "declining" zone automatically produces this.
- **Confirm which exact check the code runs for tt_4 before hand-calculating a prediction for it.** A two-point comparison (`sma_200[t] > sma_200[t-N]`) and a strict-monotonic check (rising every day for N days) are different tests and can give different answers on identical data.

---

## 5. Prediction discipline (non-negotiable)

- Predictions for every condition, per zone (or per day, where conditions are still resolving), must be **written down before running any code against the real fixture.**
- If a "hand calculation" is actually just calling the code under test and copying its output, it is not a prediction — it's circular, and any "match confirmed" claim built on it is meaningless. A real hand-check is computed independently: plain arithmetic, or a separate calculation path, never the function being tested.
- If a written prediction turns out wrong, **do not silently correct it.** Leave the wrong version visible in the file/history alongside the correction, with a one-line note on why it was wrong (transcription error vs. real misunderstanding of the rule vs. actual code defect). Same standard the project already applies to the ledger supervisor: the point is surfacing the error, not hiding that one occurred.

---

## 6. Refactors

If shared logic (e.g. `evaluate_conditions()`, `compute_rs_percentile()`) is extracted or changed to support these tests, it must be proven behavior-preserving: rerun the original real-universe test and diff the output byte-for-byte against the previously-delivered result. State the diff result explicitly in the report — "should be unchanged" is not the same as "confirmed unchanged."

---

## 7. Known gotchas already found on this feature — read before rediscovering them

- A rally confined only to a fixture's final ~20 days cannot flip tt_3/tt_4 — the 200-day MA is structurally too slow to move that fast. This matches the book's own logic (Stage 2 only confirms well after a move has started) — it's not a bug. Don't "fix" it by weakening the fixture; extend the recovery runway further back instead.
- `evaluate_conditions()`'s evaluable mask does not separately check `sma_200.shift(21)` for NaN — there's a window (~day 200–220) where tt_4 could resolve `False` from an unhandled NaN comparison rather than a genuine trend failure. Currently harmless because the 252-day columns mature later and dominate the gate — but leave a `# TODO` in the code so a future refactor doesn't accidentally rely on that coincidence.
- The percentile method behind `compute_rs_percentile()` (nearest-rank, linear interpolation, `pandas.rank(pct=True)`, etc.) must be named explicitly in the code/docstring. Different methods can disagree right around the 70th-percentile cutoff, which is a real hard-gate threshold in production, not just a test detail.

---

## 8. Reporting standard

A narrative report is not proof. Every delivery for this feature must include:

- The actual `.py` file contents — not a description of them
- Exit codes / pass-fail output from an actual run, reproducible independently
- Any refactor's before/after diff — not just a claim that it's unchanged

---

## 9. Deliverables checklist for this feature

- [ ] `trend_template_test.py` — implementation, with `evaluate_conditions()` and `compute_rs_percentile()` as separately callable, tested functions
- [ ] `test_trend_template_known_answer.py` — original overall known-answer test
- [ ] `test_trend_template_test_A.py` — tt_1–tt_8b, per-zone predictions written before running, corrected in place (not erased) if wrong
- [ ] `test_trend_template_test_B.py` — tt_9, synthetic universe, rank order + percentile values confirmed
- [ ] All four scripts run clean in one regression sweep, with output stated explicitly — not just "all passed"

---

## Change Log

- v1 — initial version, written after Test A/B build-out and review.
