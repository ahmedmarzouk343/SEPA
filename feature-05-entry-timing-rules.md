# Kashif — Engineering Rules: Entry Timing / VCP Detection (Feature 5)

*Source of truth for Claude Code on this feature. Supersedes verbal instructions
given in chat — if chat and this file disagree, this file wins until it's
explicitly updated. Living document.*

**Status:** Ready to build. Parameters confirmed from two rounds of visual
calibration on real EGX tickers (vcp_calibration_explorer.py, runs 1 and 2).
Architecture decisions grounded in what the charts actually showed, not assumed.

---

## 0. What this feature is

Feature 5 is the last deterministic gate before a buy signal can fire. It takes
a stock that has already passed Features 1–4 (market regime, trend template,
fundamentals, risk rules) and asks: is there a valid VCP base forming right now,
and has price cleared the pivot point on confirming volume?

Two outputs:
- `price_ready = True/False` — the actual buy trigger
- `vcp_quality_score` — feeds `position_sizing.prioritization_when_oversubscribed`

Neither output can fire without a confirmed VCP base. A fundamentals pass alone
is never a buy signal — this is explicit in `entry_timing.price_ready_status`
in the JSON.

---

## 1. Source of truth

1. `minervini_sepa_v1_strategy_config.json` → `entry_timing` block (v0.17+)
2. `MANIFESTO.md` Part 6
3. `ch10-notes.md` — the most detailed technical chapter, source for all VCP rules
4. `vcp_calibration_spec.md` and `vcp_calibration_explorer.py` — calibration
   parameters confirmed from visual inspection of real EGX charts

---

## 2. Detection architecture — dual timeframe, confirmed by calibration

Minervini identifies macro VCP structure on the weekly chart and refines entry
timing on the daily. The calibration confirmed this is necessary for EGX
specifically: TMGH's daily chart showed a cluster of tightly-packed peaks that
looked like 8 contractions in one base; the weekly chart correctly showed one
clean macro base. Always run both timeframes.

### 2.1 Weekly — identify and validate the base

Weekly bars via `resample('W').agg(Open=first, High=max, Low=min, Close=last,
Volume=sum)`. Run `detect_swings()` on weekly bars with `DISTANCE_WEEKS=2`.

Purpose: confirm a genuine multi-week base structure exists. If no valid base
is found on the weekly chart, don't proceed to the daily — a stock with no
macro structure on the weekly is not a VCP candidate regardless of what the
daily looks like.

### 2.2 Daily — count contractions and locate the pivot

Run `detect_swings()` on daily bars with `DISTANCE_DAYS=3`. Use the weekly-
identified base boundaries (start trough, end date) as a window constraint —
only detect sub-swings within that window, not across the whole price history.

Purpose: resolve the internal contraction sequence and find the exact pivot point
(high of the final/tightest contraction per the JSON).

---

## 3. The `detect_swings()` function — confirmed parameters

Same function called on both timeframes. Parameters locked from calibration:

```python
ATR_PERIOD       = 14    # confirmed working on EGX data
ATR_MULTIPLIER   = 1.0   # confirmed — 1.5x missed real structure on COMI
SMOOTHING_WINDOW = 5     # 5-day rolling median — removes thin-trading spikes
                         # without destroying weekly structure (confirmed on SWDY)
DISTANCE_DAYS    = 3     # daily bars — allows tight handle contractions to register
DISTANCE_WEEKS   = 2     # weekly bars — stable across both calibration passes
```

### Why rolling median, not mean
A stock like TRTO can move 5% in a single day on one thin trade, then be flat
for a week. Rolling mean would smooth that into the series and raise the ATR-
derived prominence threshold around it. Rolling median ignores the outlier
entirely — the 5-day median of [0.033, 0.033, 0.040, 0.033, 0.033] is 0.033,
not 0.034.

### Implementation
```python
def detect_swings(close, high, low, volume, atr_period, atr_multiplier,
                  smoothing_window, distance):
    # 1. Compute ATR via pandas_ta (handles any bar frequency)
    atr = pandas_ta.atr(high, low, close, length=atr_period)
    prominence_threshold = atr_multiplier * atr.iloc[-1]

    # 2. Smooth close with rolling median
    smoothed = close.rolling(smoothing_window, center=False).median()

    # 3. Detect peaks on smoothed series
    peaks, _ = scipy.signal.find_peaks(
        smoothed.dropna().values,
        prominence=prominence_threshold,
        distance=distance
    )

    # 4. Detect troughs (invert, detect peaks)
    troughs, _ = scipy.signal.find_peaks(
        -smoothed.dropna().values,
        prominence=prominence_threshold,
        distance=distance
    )

    # 5. Map indices back to original (pre-dropna) index
    # 6. Return actual HIGH/LOW prices from raw (unsmoothed) series at those indices
    #    — detected LOCATION from smoothed, measured VALUE from raw
    return peak_indices, trough_indices
```

---

## 4. Base identification and validation

### 4.1 Base definition
A base is a trough → peak → trough sequence. The sequence starts at the first
trough after the Stage 2 uptrend begins (i.e., after `hard_filter` passes) and
ends at the most recent trough before the current date.

### 4.2 Hard filters applied before the monotonicity check

These are applied in this order — if any fails, discard the base entirely:

**Maximum base duration: 65 weeks (≈325 trading days)**
This is a hard cutoff from `ch10-notes.md`. Apply it BEFORE the monotonicity
filter. TMGH's charts showed why the order matters: a base spanning the full
2-year window was passing through to the contraction analysis and producing a
nonsensical 8-contraction result. Discard any base where
`(end_trough_date - start_trough_date) > 325 trading days`.

**Minimum base duration: 3 weeks (≈15 trading days)**
Per `ch10-notes.md`: "anything forming in under ~3 weeks is high-risk, insufficient
time to shake out weak holders." Flag, do not hard-reject — but record it.

**Maximum correction depth: 60%**
Per JSON: `avoid_above: 0.60`. Hard reject. A stock down more than 60% from its
highs has too much overhead supply.

**Pre-filter: minimum ATR > 0.5% of price**
Confirmed from calibration. TRTO had ATR of 0.0004–0.0028 EGP on a 0.033 EGP
stock (~1.2–8.5%), which sounds fine numerically but the price is quantized to
~11 unique values across 490 bars. Use minimum unique closing prices > 20 over
the lookback window as the primary filter — a stock with fewer than 20 unique
closing prices over 2 years is not forming VCP bases, it's tick-quantized.
Note: the Liquidity Lock in `kashif_sizer.py` (Feature 4) should catch most of
these upstream, but this filter provides defense-in-depth.

### 4.3 Contraction sequence validation (monotonicity filter)

This is a POST-DETECTION filter applied to the trough→peak→trough sequences
inside a validated base. The book says each successive pullback should be
"roughly half the size of the last" — strictly monotonic is too aggressive
(SWDY's third contraction at 16.7% after 13.2% would be rejected but is a
real base), but pure oscillation like TMGH's 8-swing base should be rejected.

**Rule**:
```
Accept a base if:
  (a) final_contraction_depth <= first_contraction_depth * 0.75  AND
  (b) no single contraction is larger than 110% of the immediately prior one

Reject if either fails.
```

Worked checks from calibration:
- COMI base 6 (16.9%→6.7%→3.4%): final=3.4% ≤ 16.9%×0.75=12.7% ✓, no step
  exceeds 110% of prior ✓ → ACCEPT
- SWDY (29.8%→13.2%→16.7%): final=16.7% ≤ 29.8%×0.75=22.4% ✓, step 3 is
  16.7/13.2=126% of prior — exceeds 110% → technically REJECT by strict rule.
  However: looking at the SWDY chart, this base clearly IS a real VCP visually.
  The 110% tolerance may need loosening to 130% for EGX. Flag SWDY as a
  boundary case in the test fixtures and revisit once backtesting exists.

**Contraction count**: must be 2–6 per JSON. Hard reject outside this range after
the monotonicity filter.

### 4.4 The judgement layer — `ai_context_review` stage

`ch10-notes.md` is explicit: some aspects of VCP detection are "genuinely closer
to pattern recognition than a checklist." Two things are not fully proceduralisable:

- Whether a base is a "real" cup-with-handle vs. random chop — given numeric
  checks pass, this gets a PASS/FAIL/UNCERTAIN from Claude
- Whether a post-breakout reaction is "tennis ball" (healthy) vs. "egg" (failing)

These go to `ai_context_review` stage with a fixed rubric. The numeric pipeline
(Features 1–5) feeds the shortlist; Claude reviews only the stocks that cleared
all numeric gates. Claude never makes the final buy decision — it returns
CONFIRM / UNCERTAIN / REJECT on the pattern quality, and the `price_ready`
trigger still requires a confirmed pivot breakout on volume regardless.

---

## 5. Pivot point and buy trigger

From `entry_timing.pivot_point` in the JSON — unchanged, already correct:

```
pivot_price = high of the final/tightest contraction's peak
buy_trigger = close > pivot_price
              AND volume >= 1.4 * 50day_avg_volume
              AND price_ready has not been set yet for this base
```

**Never enter in anticipation of a breakout** — the pivot must actually clear,
not just approach. This is a hard rule from `ch10-notes.md` and `MANIFESTO.md`.

**Squat tolerance**: if price breaks the pivot intraday but closes back below it
the same day, do not count as a failed breakout — give it up to 10 trading days
to re-attempt, per `post_breakout_health_check.squat_tolerance_days`.

---

## 6. Post-breakout health check

From `entry_timing.post_breakout_health_check` in the JSON:

- `close < sma_20` after breakout → `price_ready = False` (invalidated)
- Squat: price closes back inside range same day → wait up to 10 days, do not
  immediately invalidate
- A position that got stopped out from this base can re-enter the watch list —
  the base may "reset" (per `risk_rules.reentry_policy`)

---

## 7. `vcp_quality_score` — feeds position sizing priority

Composite of three components, all from the JSON:

```
vcp_quality_score = base_count_modifier + depth_score + contraction_count_score

base_count_modifier: from entry_timing.base_count_modifier.scoring
  1st/2nd base: +0.05
  3rd base:      0.00
  4th+:         -0.05

depth_score: how close the final contraction is to the ideal
  final_depth < 10%:  1.0 (tight, ideal)
  10-20%:             0.7
  20-35%:             0.4
  >35%:               0.0 (too deep, wouldn't pass the 35% preference anyway)

contraction_count_score: within the 2-6 valid range
  2-4 contractions: 1.0 (book's "ideal" range)
  5-6:              0.5 (valid but less ideal)
```

This score is NOT a pass/fail gate. It is used by `position_sizing` to rank
simultaneous candidates when more qualify than there are available slots.

---

## 8. Testing standard

Same discipline as Features 1–4 (known-answer fixtures, predictions before code,
wrong predictions left visible).

**Key difference**: VCP detection operates on multi-week price sequences. Use
synthetic OHLCV DataFrames with hand-crafted patterns — not random price walks.

Required fixtures:

- **Fixture 1 — clean 3-contraction VCP (daily)**: synthetic price series with
  three progressively shallower pullbacks (e.g. 20%→12%→6%), volume drying up
  at the third contraction. Should ACCEPT. Hand-calculate the pivot price and
  confirm the function returns it.
- **Fixture 2 — oscillating sequence rejected**: three contractions where depths
  oscillate (15%→8%→11%). Should REJECT at the monotonicity filter. Confirm the
  rejection reason is recorded.
- **Fixture 3 — duration boundary cases**: one base of exactly 15 trading days
  (minimum threshold), one of 326 trading days (one over the 325-day max). First
  should pass with a flag, second should hard-reject.
- **Fixture 4 — depth boundaries**: one base with final correction 61% (should
  hard-reject), one with 59% (should pass with caution flag). The 60% threshold
  must be strictly enforced.
- **Fixture 5 — volume confirmation on breakout**: a valid VCP base followed by
  a breakout day. Sub-case A: volume = 1.5× 50-day avg → `price_ready = True`.
  Sub-case B: volume = 1.2× 50-day avg → `price_ready = False` (below 1.4×
  threshold). Both at the same pivot price — confirms volume check is independent
  of price check.
- **Fixture 6 — squat tolerance**: price pierces the pivot intraday (high >
  pivot) but closes below it. `price_ready` must NOT fire. Advance 3 days, price
  closes above pivot with confirming volume — `price_ready` must fire now.
- **Fixture 7 — SWDY boundary case**: 3-contraction base with depths
  29.8%→13.2%→16.7%. With the 130% tolerance: ACCEPT. With 110%: REJECT.
  This fixture exists specifically to make the tolerance decision visible and
  testable — whichever value is chosen, this fixture locks in that choice.
- **Fixture 8 — tick-quantized stock pre-filter**: fewer than 20 unique closing
  prices over the lookback window. Should be filtered out before detect_swings()
  even runs. Confirm the pre-filter fires, not the VCP logic.
- **Fixture 9 — dual-timeframe consistency**: a synthetic series where the weekly
  shows no valid base (only 1 trough, no peak-trough pair) but the daily would
  find structure. Should NOT produce a VCP signal — weekly validation is
  required before daily analysis runs.

---

## 9. Deliverables checklist

- [ ] `vcp_detection.py` — `detect_swings()`, `identify_bases()`,
  `validate_base()` (hard filters + monotonicity), `score_vcp_quality()`,
  `find_pivot()`, `check_breakout()`, `check_post_breakout_health()`
- [ ] `entry_timing.py` — orchestrator that calls the above in the dual-
  timeframe sequence (weekly validate → daily refine) and returns
  `{price_ready, pivot_price, vcp_quality_score, base_details}`
- [ ] `ai_context_review_rubric.md` — the fixed rubric for the judgement layer
  (cup-with-handle quality, tennis-ball vs egg post-breakout read). This is a
  separate deliverable — Claude Code builds the numeric pipeline; the AI rubric
  is a strategy/business document written by the business-side chat, same
  division of responsibility as the catalyst_check rubric.
- [ ] Known-answer test file covering all 9 fixtures, predictions written before
  running, corrected in place if wrong
- [ ] Updated `minervini_sepa_v1_strategy_config.json` with the confirmed
  calibration parameters, the dual-timeframe architecture, the monotonicity
  filter formula, and the pre-filter for tick-quantized stocks
- [ ] The SWDY boundary case decision (110% vs 130% tolerance) must be explicitly
  decided and recorded in the JSON before the test file is written — Fixture 7
  is designed to make that decision testable, not to defer it

---

## Change Log

- v1 — initial version. Parameters confirmed from two-pass visual calibration
  on COMI, TMGH, SWDY, TRTO. Architecture decisions (dual-timeframe, ATR-scaled
  dynamic prominence, rolling median pre-smoothing, monotonicity filter,
  65-week hard cutoff, tick-quantized pre-filter) all grounded in what the
  calibration charts actually showed, not assumed from theory.
