# Kashif — Complete Change Register

*Every design decision, bug fix, correction, and philosophy change made
across the entire project. Ordered by category, not chronology. Use this
file to understand why any rule or parameter is what it is.*

**Current JSON version**: v0.27.0-draft
**Last updated**: August 2026

---

## Part 1 — Philosophy Changes

### P1: Profit-First Principle (applied v0.27)

**What changed**: where the book gives a range or option between more and
less aggressive, always take the more aggressive choice that maximizes
gain potential. Applied across position sizing, regime gate logic,
defensive mode triggers, and entry thresholds.

**Why**: the original design added extra conservatism on top of what the
book states — before the strategy was even validated on real data. The
S&P 500 backtest produced 0 trades with AND-gate regime logic in one of
the strongest bull markets in a decade. The system was over-engineered
toward caution before earning that caution.

**Book basis**: Minervini's strategy is already concentrated and high-conviction.
The book's own position sizing example is 25% per position (4 positions).
Extra conservatism added by us was never in the book.

---

## Part 2 — Fundamentals Screen (Feature 2)

### F2-A: Composite scoring system REMOVED (v0.27)

**What was built**: a 6-sub-screen weighted composite scoring system
(weights: earnings_growth 0.25, earnings_acceleration 0.20,
revenue_confirmation 0.15, code_33 0.20, earnings_quality 0.10,
price_reaction_to_earnings 0.10) with a 65-point pass threshold.

**Why it was removed**: yfinance provides 5-7 quarters maximum. The
composite required 5+ quarters to compute growth comparisons, leaving
only 1-2 usable data points. Code 33 (3 consecutive accelerating quarters)
was structurally impossible to confirm. Maximum achievable score was 35
against a threshold of 65. Confirmed in the S&P 500 backtest: 303 tickers
evaluated, 0 passed (highest score: 35.0). The screen could never pass
any real stock.

**What replaced it**: 3 yes/no questions directly from ch07-notes.md.
See F2-B below.

### F2-B: 3-Question Fundamentals Screen (v0.27)

**What it is**:
- Q1: EPS growth ≥20% YoY in most recent quarter (REQUIRED)
- Q2: current quarter growth > prior quarter growth (SKIPPED if only 1 quarter)
- Q3: revenue growing YoY in most recent quarter (SKIPPED if unavailable)

**Book source**: ch07-notes.md — "minimum bar many successful growth
managers use: 20-25%+ in most recent 1-3 quarters" and "over 90% of
biggest historical winners showed earnings acceleration."

**Pass rule**: Q1=PASS AND Q2=(PASS or SKIPPED) AND Q3=(PASS or SKIPPED)

### F2-C: PEG Modifier REMOVED (v0.27)

**What was built**: a log-distance PEG modifier: `clamp(-0.10 * log2(peg), -0.10, 0.10)`

**Why removed**: the book says PEG is a "soft-score input only, never
standalone." It was added as a mathematical formula before validating
the basic strategy. With the composite removed, there is no composite
to modify.

### F2-D: Filing Lag Enforcement KEPT

**What it does**: only uses quarters whose 60-day FRA filing deadline
has elapsed as of the current bar date. Q ending June 30 is not visible
until August 29 at earliest.

**Why kept**: real lookahead bias protection. The book implicitly requires
this even if it doesn't state the mechanism explicitly. Without it,
backtest results are meaningless.

### F2-E: Cross-Source Consistency Checks REMOVED (v0.27)

**What was built**: if a ticker's data source (yfinance vs stockanalysis.com)
changed between quarters, mark the quarter as "unconfirmed."

**Why removed**: theoretical concern, not a proven problem causing wrong
signals. Unnecessary with the simplified 3-question approach.

### F2-F: Turnaround Override KEPT but simplified

**Original**: a curve override (floor=1.00, cap=1.40) with a specific
monotonicity formula.

**Simplified**: when category_tag = turnaround, Q1 threshold raises to
≥100% (1.00). The curve shape was an invented mathematical mechanism
the book never specified.

### F2-G: Earnings Quality and Price Reaction Sub-Screens REMOVED

**Why removed**: the book mentions checking for one-time items and price
reaction as informational context, not as scored components in a filter.
These were added as scored sub-screens without book justification.

---

## Part 3 — Market Regime Gate (Feature 3)

### R1: Gate Logic AND → OR (v0.27)

**What changed**: the regime gate previously required all three conditions
simultaneously (AND). Changed to OR — any one condition confirming is
sufficient to begin evaluating individual stocks.

**Why**: ch09-notes.md describes three signals to watch, not three
simultaneous requirements. The AND gate was blocking everything — the
S&P 500 backtest showed only 31 open bars in a 2-year strong bull market.
Profit-first principle: OR opens more opportunities.

**Book basis**: "New-high list starts outpacing new-low list... pullbacks
are shallow... leading stocks making higher lows while index makes lower
lows" — three signals described independently, not as a single combined condition.

### R2: leader_divergence Threshold — Magnitude Gap REPLACED with Directional

**Original**: leader% exceeds universe% by ≥15 percentage points (invented)

**Replaced with**: leader_condition (>50% of leader basket shows higher low)
AND universe_condition (<50% of full universe shows higher low)

**Why**: the book's own wording is directional — "leading stocks making
higher lows WHILE the general index is still making lower lows." Two
simultaneous clauses, not a magnitude gap. The 50% pivot is a natural
majority threshold, not an invented specific number.

### R3: leader_pullback_shallow Duration Added

**Original spec**: only checked pullback depth (≤10%)

**Added**: duration requirement (≤10 trading days) alongside depth.
The book describes pullbacks as "brief (days, not weeks) AND shallow" —
the original spec missed the duration requirement entirely.

### R4: new_high_low_ratio_favorable — Exact Formula

**Original**: "ratio trending up over trailing 21 days" (vague)

**Resolved to**: `ratio[t] > ratio[t-21]` (two-point comparison, same
pattern as tt_4's sma_200 slope check)

**Division-by-zero fix**: denominator changed to `count(52wk_low) + 1`
because count_low can legitimately be zero on a strong day.

### R5: leader_pullback_shallow — 21→20 Day Window Corrected

**Bug**: was documented as "21-day local high window" — leaked from
new_high_low_ratio_favorable's unrelated t-21 lookback during the same
editing session. Corrected to 20 days, matching leader_divergence's window.

### R6: days_since_local_high Tie-Breaking Fix

**Bug**: `argmax()` on a rolling window returns the FIRST occurrence on
a tie. A stock with a flat plateau at its peak would show "19 days since
local high" when the correct answer was "10 days since most recent peak."

**Fix**: reverse the window before argmax — `argmax(window[::-1])` —
so ties resolve to the most recent occurrence.

**EGX relevance**: NDRL confirmed as a thin/flat-trading EGX ticker that
triggered this exact behavior.

### R7: T0-A Bug — Regime Gate Permanently Closed

**Bug confirmed**: `_new_high_low_ratio_favorable_snapshot` was building
a constant series of 22 identical values (today's single ratio repeated).
`ratio > ratio.shift(21)` on a constant series is always False. Gate never
opened. Confirmed across 490 bars on EGX and all 522 IS bars on S&P 500
(0 open bars despite the strongest bull market in a decade).

**Root cause**: `prenext` was not set to `next` in the backtrader strategy.
With 500 tickers, some recently-added constituents have data starting much
later, delaying `next()` so the strategy never accumulated enough history.

**Fix**: `prenext = next` (standard backtrader pattern for multi-data strategies).

---

## Part 4 — Trend Template / Hard Filter (Feature 1)

### T1: Condition Count Corrected 9 → 10

**Bug**: documentation said "ALL 9 boolean checks." Actual count is 10
(tt_1 through tt_9, with tt_8 split into tt_8a/tt_8b).

### T2: RS Percentile Convention Specified

**Resolved**: `pandas.Series.rank(pct=True) * 100` using default
tie-handling (method='average'). Confirmed against reported test behavior
(7/9 = 77.78% in the 9-series synthetic universe).

### T3: RS Percentile Flat Broadcast Bug Fixed

**Bug** (`kashif_strategy.py:447`): took today's single RS snapshot and
broadcast it to every historical bar. Every bar got today's RS rank, not
its actual rank on that date. Both lookahead bias and correctness error.

**Fix**: compute RS percentile per bar cross-sectionally using only data
available up to that bar's date. Cache per bar date to avoid recomputation.

### T4: dropna(how='any') vs na_option='keep' Fixed

**Bug**: `compute_rs_percentile()` used `dropna(how='any')` — if even
one ticker lacked data on a date, that date was dropped for every ticker.

**Fix**: changed to `na_option='keep'` — ranks whoever has data, never
drops everyone for one missing ticker.

### T5: 52-Week High/Low from High/Low Columns (Not Close)

**Finding**: high_52wk and low_52wk are computed from the High/Low OHLC
columns, not the Close column. A reasonable interpretation but worth
documenting explicitly since the book doesn't specify intraday vs. closing.

---

## Part 5 — VCP / Entry Timing (Feature 5)

### V1: Calibrated Parameters from Real EGX Data

**Parameters locked from two-pass visual calibration on COMI, TMGH, SWDY, TRTO**:
- ATR_MULTIPLIER = 1.0 (1.5× missed real COMI structure)
- SMOOTHING_WINDOW = 5 (rolling median, not mean — removes thin-trading spikes)
- DISTANCE_DAYS = 3 (5 was too coarse for tight handle contractions)
- DISTANCE_WEEKS = 2 (stable across both calibration passes)

### V2: Dual-Timeframe Architecture

**What**: weekly to identify and validate macro base structure, daily to
resolve internal contractions and locate the pivot.

**Why**: TMGH calibration charts showed daily detection produced a
nonsensical 8-contraction base that the weekly correctly reduced to one
clean macro base. Faithful to Minervini's own described process.

### V3: T0-B Bug — VCP Weekly Monotonicity Always Failed

**Bug**: `rule_a` required `depths[-1] <= depths[0] * 0.75`. With only
1 contraction (common on weekly bars with 2 years of data), this demanded
`depth <= depth * 0.75` — impossible for any positive depth. ALL test
tickers returned `WEEKLY_BASE_REJECTED:MONOTONICITY_FAILED`.

**Fix**: skip rule_a and rule_b when `len(depths) < 2`. A single contraction
cannot fail a monotonicity test by definition — there is nothing to compare.

### V4: Monotonicity Tolerance Set at 130%

**Decision**: SWDY's real base (29.8%→13.2%→16.7%) — step 3 is 126% of
step 2. At 110% tolerance this would be rejected; at 130% it passes.
Charts confirmed SWDY's base is a real VCP. Tolerance set at 130%.

### V5: Tick-Quantized Pre-Filter

**Added**: minimum 20 unique closing prices over the lookback window.
TRTO had only 11 unique values across 490 bars — algorithm correctly
found 0 meaningful peaks. Pre-filter catches this before VCP logic runs.

### V6: 65-Week Maximum Base Duration

**Added**: hard cutoff of 325 trading days applied BEFORE the monotonicity
filter. TMGH's charts showed a 2-year-spanning base being treated as one
base, producing meaningless 8-contraction results.

### V7: Breakout Volume Threshold Lowered 1.4× → 1.2× (v0.27)

**Original**: 1.4× 50-day average volume (invented specific number)

**Changed to**: 1.2× — the book says "meaningfully above average volume."
1.2× still confirms institutional interest while capturing more genuine
breakouts that don't happen to hit an arbitrary threshold.

---

## Part 6 — Risk Rules & Position Sizing (Feature 4)

### RI1: Stop-Loss Hard Maximum KEPT at 10%

**Book**: "set an absolute maximum line in the sand of no more than 10%."
Backed by the Loss Adjustment Exercise — same trades with losses capped
at 10% turned -12.05% into +79.89%.

**Not changed**: this is the single most load-bearing number in the book.
Non-negotiable regardless of profit-first principle.

### RI2: Position Count 4 → 6 (v0.27)

**Book**: "typically 4-6 concurrent positions for a smaller portfolio."

**Changed**: default set to 6 (top of the book's stated range). More
concurrent positions = more opportunities captured simultaneously.

### RI3: Position Size 25% → 16.7% (v0.27)

**From**: 25% per position (4 positions)
**To**: 16.7% per position (6 positions)

Same capital, more opportunities. Book says 4-6 at 25% sizing — at 6
positions this is 16.7% each.

### RI4: Losing Streak Step-Down REMOVED (v0.27)

**Original**: 3 consecutive stops → 40% size, 5 → 20% size (invented numbers)

**Removed**: specific triggers were invented, not in the book. The book
says "reduce position size in steps during losing streaks" without giving
specific trigger points. Defensive mode handles sustained underperformance.
Full size maintained until defensive mode activates.

### RI5: Defensive Mode Trigger Loosened (v0.27)

**Original**: rolling_win_loss_ratio < 2.0 OR win_rate < 0.50

**Changed to**: rolling_win_loss_ratio < 1.5 OR win_rate < 0.40

Less aggressive trigger = more time at full size before defensive mode
activates. The book says activate when performance degrades, not at the
first sign of difficulty.

### RI6: Pilot Size on Reentry 50% → 75% (v0.27)

**Book**: "start with small pilot positions, increase only after early
trades confirm." 75% is still smaller than full size but deploys capital
faster. Profit-first takes the less conservative interpretation.

### RI7: Breakeven Trigger KEPT at 3×

**Book**: "once an open position's gain reaches ~3× the original risk,
move the stop to at least breakeven." This is the book's precise stated
rule. Not changed.

### RI8: N-3 Fix — Competing Stops on Add-On Buys

**Bug**: when a second buy fills for the same ticker, `self.stop_order[d]`
was overwritten with a new stop for only the second tranche's shares.
The first stop was still live — two competing stop orders for different
sizes, only the second tracked.

**Fix**: cancel the existing stop before placing a new consolidated stop
covering the full position size.

### RI9: N-4 Fix — Breakeven Stop Wrong Blended Price

**Bug**: `self.entry_price[d]` held the first entry price. After a second
buy at a higher price, the blended cost basis was higher — the stop was
placed too low, giving more risk than intended.

**Fix**: update `self.entry_price[d]` to `pos.price` (backtrader's blended
average) after every add-on buy.

### RI10: Defensive Mode Minimum 10-Trade Guard

**Added**: defensive mode only activates when at least 10 closed trades
exist in the trailing window. After the first loss in a fresh portfolio,
win_rate = 0%, which would fire defensive mode immediately. Not meaningful
with fewer than 10 data points.

---

## Part 7 — Catalyst Check (Feature 6)

### C1: Google News RSS as News Source

**Decision**: DuckDuckGo's HTML endpoint hit a CAPTCHA bot-wall. Google
News RSS is a legitimate machine-readable format, confirmed working for
both English and Arabic queries.

**Risk**: Google has never officially committed to this endpoint's stability.
Documented as a second single point of failure alongside ArabFinance.

### C2: Model Wired — gemini-3.6-flash

**History**: gemini-2.0-flash was retired; gemini-2.5-flash returned 404
for new users; gemini-3.6-flash confirmed working.

**Architecture**: synchronous call, no Batch API. The pipeline is an EOD
cron job — batch API adds async complexity for no benefit.

**Provider decision**: Google AI Studio (free tier) over Claude Haiku 4.5
(paid). Rationale: the strategy has not yet proven it generates alpha.
Optimizing cost structure before validation is premature. Free tier costs
nothing during the heavy backtesting and paper-trading validation phase.

### C3: Arabic Search is Not Optional

**Finding from OCDI**: English search alone found a stale FY2025 +77%
figure and would have scored a FALSE POSITIVE. Arabic search found the
real H1 2026 -35.7% result. Arabic search is the ONLY way to find certain
real EGX results — confirmed in 2 of 3 initial test cases.

### C4: Arabic Name Mapping Gap

**Current coverage**: ~13 of 224 tickers have Arabic names mapped.
The 211 uncovered tickers skip Arabic search (logged, not silent).
Target: extend to top 50 by market cap.

### C5: Three Edge Case Rules from Live Testing

- **reporting_basis_conflict_rule**: standalone vs consolidated directions
  disagree → score NEUTRAL, state both figures
- **source_reconciliation_rule**: different P&L lines can both be correct
- **debunked_rumor_rule**: denial of negative rumor → net-neutral, not NEGATIVE

---

## Part 8 — Infrastructure and Data

### I1: CONFIG_PATH Relative to __file__

**Bug**: `r"C:\Users\Asuss\Stocks\minervini_sepa_v1_strategy_config.json"`
hardcoded in 7 files. Breaks on any other machine, any other directory.

**Fix**: `kashif_config.py` defines `CONFIG_PATH = Path(__file__).parent / "..."`.
All 7 files import from here.

### I2: RS Computation Performance

**Bug**: `_compute_rs_snapshot` recomputed ~196× per bar (once in regime
+ once per ticker). Each call iterated all tickers' 253-bar history.
~4.8 billion operations per backtest.

**Fix**: compute once per bar, cache by (ticker, bar_date). 99.5% reduction
in redundant RS computations confirmed.

### I3: Dual Data Feed for Backtest

**Architecture**: two parallel `bt.feeds.PandasData` per ticker:
- `auto_adjust=True` for OHLC — all signal calculations (Trend Template,
  VCP, stop-loss triggers)
- `auto_adjust=False` for Volume only — MinerviniSizer ADDV calculation

**Why**: adjusted volume inflates historical liquidity after splits.
A 5-for-1 split shows 5× the real 2021 volume in adjusted data. The
Liquidity Lock would accept a position that was physically impossible to fill.

### I4: Broker Friction Configured

```python
cerebro.broker.setcommission(commission=0.005)  # 0.5% per leg
cerebro.broker.set_slippage_perc(perc=0.001)    # 0.1% additional
```

EGX friction: brokerage ~0.3%, stamp duty 0.15%, FRA fee 0.005%,
slippage variable. Round-trip ~1.2%.

### I5: OOS Partition Enforcement

**Mechanism**: OOS period refuses to run unless `oos_locked.flag` exists.
The flag file is created manually after IS + Validation are complete and
parameters are confirmed. Prevents accidental OOS contamination.

### I6: Gap-Down Stops Fill at Open Price

**Bug**: stops were assumed to fill at the stop price. A stock opening
15% below a 10% stop fills at the open, not at the stop.

**Fix**: any bar where `open < stop_price` fills at open. This covers
both the intraday path paradox and the limit-down scenario.

### I7: Decision Receipts Write to Defined Directory

**Bug**: `path = f"decision_receipts_{date}.jsonl"` — wrote to CWD.

**Fix**: `RECEIPTS_DIR = Path(__file__).parent / "decision_receipts"`.
Same pattern catalyst_check.py already used for TRACK_RECORD_PATH.

### I8: KILL_SWITCH Module Reference

**Bug**: `from kashif_config import KILL_SWITCH` — snapshot at import time.
Toggling the value mid-run had no effect.

**Fix**: `import kashif_config; if kashif_config.KILL_SWITCH:` — reads
the live value on each `next()` call.

### I9: 29 Zero-Data Tickers Pre-Filtered

**Confirmed list**: QNBE, VLMR, VLMRA, VALU, TAQA, UBEE, BONY, KORA,
ACAP, NAPR, GOUR, CRST, ACTF, GTWL, ALRA, NARE, PHGC, GPIM, GGRN, AMII,
AIDC, GTEX, POCO, KRDI, TANM, TYCN, AIHC, DGTZ, CPME — all return 0 bars
from yfinance.

### I10: Fundamentals Suffix Parameter

**Bug**: `symbol = f"{ticker}.CA"` hardcoded in fundamentals_fetcher.py.
S&P 500 tickers were being looked up as DELL.CA, XOM.CA etc. — not found.

**Fix**: `suffix=".CA"` parameter, defaulting to EGX. S&P 500 runner
passes `suffix=""`.

### I11: Deprecated google-generativeai SDK

**Finding**: `google.generativeai` package ended support.
**Fix**: migrated to `google.genai`.

### I12: Track Record Appends in Backtest

**Bug**: `log_to_track_record()` was unconditional — appended a new line
on every call. A 195-ticker × 500-bar backtest would write ~97,500 lines
per run with duplicates across reruns.

**Fix**: added `log_track_record=True` parameter. Backtest runner passes
`log_track_record=False`.

---

## Part 9 — Data Persistence (Feature 8)

### D1: Event-Driven, Not Daily Snapshots

**Decision**: records written only when something changes. Days where
nothing changes produce no records. Keeps files small and meaningful.

### D2: Reasons, Not Scores

**Decision**: every record must explain WHY in plain English, not just
what number came out. A composite score of 78.4 is meaningless six months
later. "EPS grew 47% YoY accelerating from 31%, revenue also accelerating,
Code 33 confirmed" is the record worth keeping.

### D3: Seven Event Types

ADDED, STAGE_FAILED, ENTERED, HELD, STOP_HIT, EXIT_SIGNAL, REMOVED.
Re-entry is a fresh ADDED event — prior cycle stays in the log.

### D4: market_regime.reason Plain English

**Bug**: `market_regime.reason` showed a raw Python dict string
`{'open': True, 'pullback_pass': True, ...}`.

**Fix**: `_build_regime_reason()` constructs a human-readable narrative
from the diagnostic components: "new high/low ratio rising over 21 days —
leader basket (51 tickers, RS≥90) pullback avg 3.0% over 1 days..."

---

## Part 10 — Backtest Validity

### B1: Fundamentals Lookahead Bias

Filing lag enforced: only use quarters whose 60-day FRA deadline has
elapsed as of the current bar date.

### B2: Survivorship Bias — Accepted Limitation

The 224-ticker universe excludes companies that were delisted or failed.
Mandatory disclaimer on every report: "True performance is likely lower."

### B3: Chaos Engineering Completed

Five corruption tests — all PASS:
1. Delete 2 trading weeks → no crash
2. Zero volume 10 days → Liquidity Lock returns 0
3. Multiply close 10× → Corporate Action Guard fires
4. Full NaN ticker → graceful exclusion
5. Pre-lag fundamentals → guard mechanism confirmed

### B4: Currency Devaluation Mirage

EGP devaluation dates flagged for Phase C: November 2016, March 2022,
January 2023, post-2023. When F2 is added with real data, the Macro
Devaluation Filter will raise EPS growth thresholds in quarters following
each devaluation to filter out currency-driven growth.

### B5: Out-of-Sample Protocol

| Period | Dates | Role |
|---|---|---|
| Warmup | 2022-08-01 to 2023-08-26 | No screening — RS warmup |
| In-Sample (IS) | 2023-08-27 to 2025-08-26 | Parameter calibration only |
| Validation | 2025-08-27 to 2026-02-26 | Sanity check, no tuning |
| OOS | 2026-02-27 to 2026-08-27 | Run ONCE after parameters locked |

OOS is blocked without `oos_locked.flag`. Re-running OOS after adjustments
is overfitting by definition.

---

## Summary — What Was Removed vs. Kept vs. Changed

| Component | Status | Reason |
|---|---|---|
| Weighted composite (F2) | REMOVED | Could never pass any real stock |
| 65-point threshold (F2) | REMOVED | Invented, never in the book |
| PEG modifier (F2) | REMOVED | Book says contextual note only |
| Cross-source consistency (F2) | REMOVED | Theoretical, not proven |
| Partial-data renormalization (F2) | REMOVED | Unnecessary with yes/no |
| Earnings quality sub-screen (F2) | REMOVED | Not a book-required filter |
| Filing lag enforcement (F2) | KEPT | Real lookahead bias protection |
| 3-question fundamentals (F2) | NEW | Book-faithful replacement |
| Regime gate AND logic | CHANGED TO OR | Opens more opportunities |
| leader_divergence 15pp gap | REPLACED | Directional formulation from book's wording |
| Duration in pullback check | ADDED | Book says "brief AND shallow" |
| Losing streak step triggers | REMOVED | Invented numbers, not in book |
| Position count 4 → 6 | CHANGED | Top of book's 4-6 range |
| Position size 25% → 16.7% | CHANGED | Same capital, 6 positions |
| Pilot size 50% → 75% | CHANGED | Profit-first, faster deployment |
| Breakout volume 1.4× → 1.2× | CHANGED | Book says "meaningfully above average" |
| Defensive mode trigger loosened | CHANGED | Less conservative, more time at full size |
| Stop-loss 10% ceiling | KEPT | Non-negotiable, backed by Loss Adjustment Exercise |
| Breakeven at 3× gain | KEPT | Book's precise stated rule |
| No averaging down | KEPT | Book: "only losers average losers" |
| ATR-scaled VCP prominence | KEPT | Solves real EGX noise problem |
| Dual-timeframe VCP | KEPT | Faithful to book's process |
| Rolling median smoothing | KEPT | Real noise reduction on thin EGX names |

---

## Change Log

- v1 — initial version. Covers all changes from v0.1 through v0.27 of the
  JSON config, organized by category rather than chronology.
