# Kashif — Backtest Roadmap

*Defines every problem, constraint, and solution that must be resolved
before the backtest produces trustworthy results. Written before Feature 8
spec or code. Nothing gets skipped without an explicit decision.*

**Version**: v4 — 24 problems catalogued. 12 blockers before Phase A.
Adds Problems 19–24 from deep technical code audit.

---

## The Question We Are Answering

"If this system managed 100,000 EGP from January 2022 to today, what would
the verified return %, maximum drawdown, and benchmark comparison look like
— and can we trust that number?"

Three success metrics, equal weight:
- **Total return %** — did the money actually grow?
- **Maximum drawdown** — how bad before recovering?
- **Benchmark** — did it beat holding EGX 30?

---

## Priority Table — Full Picture (v4)

| # | Problem | Blocks Phase A? | Priority | Can Skip? |
|---|---|---|---|---|
| 3 | Adjusted volume inflates liquidity | **YES** | **BLOCKER** | ❌ |
| 4 | Corporate Action Trap (splits → false stops) | **YES** | **BLOCKER** | ❌ |
| 5 | No market friction | **YES** | **BLOCKER** | ❌ |
| 6 | Overfitting / no OOS enforcement | **YES** | **BLOCKER** | ❌ |
| 7 | No Independent Auditor | **YES** | **BLOCKER** | ❌ |
| 8 | defensive_mode fires too early | **YES** | **BLOCKER** | ❌ |
| 9 | Intraday Path / Gap fills at wrong price | **YES** | **BLOCKER** | ❌ |
| 12 | CONFIG_PATH hardcoded in 7 files | **YES** | **BLOCKER** | ❌ |
| 13 | category_tagging stubbed in pipeline | **YES** — F3 never runs | **BLOCKER** | ❌ |
| 16 | Ledger reconciliation check | **YES** | **BLOCKER** | ❌ |
| 19 | RS percentile flat broadcast (lookahead) | **YES** — every bar gets today's RS | **BLOCKER** | ❌ |
| 20 | No real data loader / runner script | **YES** — no path to first trade | **BLOCKER** | ❌ |
| — | Limit-Down gap execution at open | **YES** | **BLOCKER** | ❌ |
| 14 | fundamentals_screen not wired to live data | No — F2 stubbed Phase A | P1 | ✅ Skip Phase A |
| 15 | .env not in .gitignore | No — before first git commit | P1 | ✅ Before git |
| 21 | Decision receipts write to CWD | No — files scatter | P1 | ✅ Fix early |
| 22 | No requirements.txt | No — breaks new machine setup | P1 | ✅ Fix early |
| 1 | No historical fundamentals | No — F2 stubbed | P1 | ✅ Skip Phase A |
| 2 | No historical news / catalyst lookahead | No — F6 stubbed | P1 | ✅ Skip Phase A |
| 10 | Currency Devaluation Mirage | No — F2 stubbed | P2 | ✅ Skip Phase A |
| 11 | Data persistence / decision records | No | P2 | ✅ Before paper trading |
| 17 | ai_context_review / ai_synthesis | No — qualitative layer | P2 | ✅ Skip Phase A |
| 18 | Technical reviewer / pipeline health | No — monitoring only | P2 | ✅ Skip Phase A |
| 23 | KILL_SWITCH snapshot not live reference | No — affects long backtests | P2 | ✅ Fix before backtest |
| 24 | RS warmup 253-bar dead period | No — document in report | P2 | ✅ Document only |
| — | Chaos Engineering (data_mutator.py) | No — before OOS | P1 | ✅ After IS |
| — | Parquet migration | No — performance | P2 | ✅ Skip Phase A |
| — | Survivorship bias | No — accept + document | P3 | ✅ Document only |
| — | Arabic name coverage 13/224 | No — gracefully handled | P2 | ✅ Extend incrementally |
| — | Paper trading loop + state diffing | No — after backtest | P1 | ✅ After Phase A |
| — | Code-based supervisor | No — after backtest | P1 | ✅ After Phase A |

**12 BLOCKERS — all must be fixed before Phase A runs:**
1. CONFIG_PATH relative to `__file__` in all 7 files
2. RS percentile computed per-bar cross-sectionally (not today's snapshot)
3. Real data loader + runner script (`run_backtest.py`)
4. category_tagging wired into `_evaluate_entry_pipeline()`
5. Ledger reconciliation check
6. Gap-down stops fill at open price
7. defensive_mode minimum trade count guard (≥10 trades)
8. Dual data feed (adjusted OHLC + raw volume)
9. Broker friction (0.5% commission + 0.1% slippage)
10. OOS data partition locked before parameters are set
11. Independent Auditor script
12. Corporate Action Guard extended to all gap-down stops

---

## The 24 Problems

### Problem 1 — No historical fundamentals
F2 stubbed to PASS for Phase A. Phase C adds F2 when point-in-time data exists.
Label every Phase A report: "Technical signals only — F2 not applied."

### Problem 2 — No historical news / catalyst lookahead
F6 stubbed to PASS for Phase A. Phase B runs catalyst_check() post-hoc
on Phase A entry dates only (current news on specific historical dates).

### Problem 3 — Adjusted volume inflates liquidity ❌ BLOCKER
Dual data feed: `auto_adjust=True` for OHLC, `auto_adjust=False` for Volume.
Raw volume used exclusively by MinerviniSizer ADDV/Liquidity Lock.

### Problem 4 — Corporate Action Trap ❌ BLOCKER
Use `auto_adjust=True` (Adjusted Close) for all trigger calculations.
Corporate Action Guard (Feature 4) detects >20% overnight gaps and
reclassifies. Extend to all gap-down stops (see Blocker 12 above).

### Problem 5 — No market friction ❌ BLOCKER
```python
cerebro.broker.setcommission(commission=0.005)  # 0.5% per leg
cerebro.broker.set_slippage_perc(perc=0.001)    # 0.1% additional
```
Round-trip ~1.2%. Conservative — real results likely better, never worse.

### Problem 6 — Overfitting / no OOS enforcement ❌ BLOCKER

| Period | Role | Dates |
|---|---|---|
| In-Sample (IS) | Only period where parameters may be adjusted | 2022–2023 |
| Validation | Sanity check, no tuning | 2024 |
| Out-of-Sample (OOS) | Run ONCE after parameters locked | 2025–today |

OOS run exactly once. Re-running with adjustments = overfitting by definition.
All three periods shown side by side in final report. OOS cannot be hidden.

### Problem 7 — No Independent Auditor ❌ BLOCKER
`independent_auditor.py`: reads only `trade_log.csv` and raw prices.
Recalculates every P&L independently. Flags any difference vs strategy
ledger. QuantStats report uses auditor-verified numbers only.

### Problem 8 — defensive_mode fires too early ❌ BLOCKER
Minimum 10 closed trades before defensive_mode activates. Calibrate
after backtest shows trades per month.

### Problem 9 — Intraday Path / Gap fills at wrong price ❌ BLOCKER
All orders execute at next bar's OPEN (`cheat_on_close=False`, default).
Gap-down stops: any stop-loss where price opens below the stop fills at
open price, not the stop price. This covers both the Intraday Path Paradox
and the Limit-Down scenario.
Watchlist Traffic Jam: verify Scoring Queue processes simultaneous signals
in priority order with real cash constraints.

### Problem 10 — Currency Devaluation Mirage
Not a Phase A blocker (F2 stubbed). For Phase C: Macro Devaluation Filter
raises required EPS growth threshold in quarters following EGP devaluation.
Devaluation dates to flag: November 2016, March 2022, January 2023, post-2023.

### Problem 11 — Data Persistence / Decision Records
Three stores — build before paper trading:
- `ticker_state.parquet` — one row per ticker per date, what was seen and decided
- `watchlist_history.jsonl` — append-only log of every add/remove with reasons
- Decision Receipts — already built in Feature 7, extend to populate the above

### Problem 12 — CONFIG_PATH Hardcoded in 7 Files ❌ BLOCKER
Add to `kashif_config.py`:
```python
from pathlib import Path
CONFIG_PATH = Path(__file__).parent / "minervini_sepa_v1_strategy_config.json"
```
All 7 files import from here. `catalyst_check.py` already does this correctly
for TRACK_RECORD_PATH — apply the same pattern everywhere.

### Problem 13 — category_tagging Stubbed in Pipeline ❌ BLOCKER
`category_tagging.py` exists and passes all tests. `_evaluate_entry_pipeline()`
never calls it. Wire `tag_universe()` between hard_filter and fundamentals_screen
per `pipeline_order` in the JSON. Wiring task, not a build task.

### Problem 14 — fundamentals_screen Not Wired to Live Data
Biggest gap between "code exists" and "system works." F2 is stubbed to
PASS for Phase A. Must be wired before paper trading produces real signals.
Fetch quarterly data from yfinance/stockanalysis per `fundamentals_data_source_routing`.

### Problem 15 — .env Not in .gitignore
`GOOGLE_AI_STUDIO_KEY` is in `.env` with no `.gitignore`. Create before
first `git init`:
```
.env
*.pkl
__pycache__/
daily_ops_log/
vcp_calibration_output/
decision_receipts/
```

### Problem 16 — Ledger Reconciliation Check ❌ BLOCKER
backtrader handles portfolio math. Add reconciliation assertion in `notify_trade()`:
```python
assert abs(self.broker.getvalue() -
           (self.broker.getcash() + sum_open_positions)) < 0.01
```
Flag immediately on drift. Log daily: cash balance + positions value + equity.
Starting capital: `cerebro.broker.setcash(100_000)`.

### Problem 17 — ai_context_review / ai_synthesis
Not a Phase A blocker. Build after paper trading is running.
`ai_context_review_rubric.md` (business doc) + Gemini call at end of
`_evaluate_entry_pipeline()`. CONFIRM/UNCERTAIN/REJECT — only REJECT blocks.

### Problem 18 — Technical Reviewer / Pipeline Health
Extend ops log schema with `schema_validation_failures` and `scan_coverage`
(`{scanned: N, failed: M, reasons: [...]}`). No new module needed.

### Problem 19 — RS Percentile Flat Broadcast ❌ BLOCKER (NEW)
**The bug** (`kashif_strategy.py:447`):
```python
rs_pct = pd.Series([rs_snapshot.get(ticker, float("nan"))] * len(df))
```
Today's RS snapshot broadcast to every historical bar. Every bar gets
today's rank, not its actual rank on that date. Lookahead bias + correctness
error combined.

**Fix**: compute RS percentile in `next()` per bar, using only data available
up to `self.data.datetime.date(0)`. Vectorized cross-sectional rank across
all tickers for that bar date. Cache per date to avoid recomputing within
the same `next()` call.

### Problem 20 — No Real Data Loader / Runner Script ❌ BLOCKER (NEW)
No code takes the 224 tickers, fetches yfinance history, creates
`bt.feeds.PandasData`, and feeds Cerebro. Test fixtures use synthetic data.
The pipeline cannot run on real EGX data without this.

**Solution**: `run_backtest.py`:
```python
for ticker in TICKERS:
    adj_df = yf.download(f"{ticker}.CA", auto_adjust=True, start=START, end=END)
    raw_df = yf.download(f"{ticker}.CA", auto_adjust=False, start=START, end=END)
    cerebro.adddata(bt.feeds.PandasData(dataname=adj_df), name=f"{ticker}_adj")
    cerebro.adddata(bt.feeds.PandasData(dataname=raw_df), name=f"{ticker}_raw")
```
IS/Validation/OOS partition enforced via START/END dates passed here.
Pre-load 253 warmup bars before IS start date (see Problem 24).

### Problem 21 — Decision Receipts Write to CWD (NEW)
**Bug** (`kashif_strategy.py:704`):
```python
path = f"decision_receipts_{date.strftime('%Y%m%d')}.jsonl"  # CWD
```
Fix — same pattern `catalyst_check.py` already uses:
```python
RECEIPTS_DIR = Path(__file__).parent / "decision_receipts"
RECEIPTS_DIR.mkdir(exist_ok=True)
path = RECEIPTS_DIR / f"decision_receipts_{date.strftime('%Y%m%d')}.jsonl"
```

### Problem 22 — No requirements.txt (NEW)
Direct dependencies: `backtrader`, `yfinance`, `pandas`, `pandas_ta`,
`numpy`, `scipy`, `beautifulsoup4`, `requests`, `python-dotenv`,
`google-generativeai`, `quantstats`, `pyarrow`.
Create: `pip freeze > requirements.txt`, then trim to direct deps only.
Pin major versions, not patch versions.

### Problem 23 — KILL_SWITCH Snapshot Not Live Reference (NEW)
**Bug**: `from kashif_config import KILL_SWITCH` copies the value at
import time. Cannot toggle mid-run without restart.

**Fix**:
```python
import kashif_config
if kashif_config.KILL_SWITCH:  # reads live value on each next() call
```

### Problem 24 — RS Warmup 253-Bar Dead Period (NEW)
First ~253 bars of any backtest: RS snapshot returns `{}`, every ticker's
`tt_9` fails, no screening occurs. Expected behavior, not a bug.
A backtest starting January 2022 has ~12 months of dead bars before first
signal (~December 2022).

**Fix**: pre-load 253 extra bars before IS start date in `run_backtest.py`.
Document the warmup period in the QuantStats report header.

---

## Additional Items from Considerations Document

**Chaos Engineering** (`data_mutator.py`) — run before OOS:
1. Delete 2 trading weeks → confirm no crash
2. Zero volume 10 days → Liquidity Lock returns 0
3. Multiply close by 10× → Corporate Action Guard fires
4. Full NaN ticker → graceful exclusion
5. Pre-lag fundamentals → PiT enforcement blocks (Phase C)

**Parquet migration** — before heavy backtest loads.

**Survivorship bias** — mandatory disclaimer on every report:
> "Results carry a positive survivorship bias. Delisted/failed companies
> excluded. True performance is likely lower than reported."

**Benchmark** — `^CASE30` confirmed available via yfinance.

---

## Complete Build Order — v4

```
PREREQUISITE PHASE
│
├── P22: requirements.txt
├── P15: .gitignore before first git init
├── P12: CONFIG_PATH relative to __file__ in all 7 files
├── P21: Decision receipts → defined directory
├── P23: KILL_SWITCH → module reference
├── P8:  defensive_mode minimum trade count guard
├── P9:  Gap-down stops fill at open price
├── P13: Wire category_tagging into pipeline
├── P16: Ledger reconciliation check
├── P19: RS percentile per-bar cross-sectional ranking
├── P20: run_backtest.py real data loader
└── P7:  independent_auditor.py

DATA PREPARATION
│
├── P3+4: Dual data feed setup
├── P5:   Broker friction configured
├── P24:  Pre-load 253 warmup bars before IS start
└── OOS partition locked before parameters are set

PHASE A — Price-only In-Sample (2022–2023)
│
├── F0, F1, F3, F5, F4 — real
├── F2, F6 — STUBBED to PASS
├── RS per-bar, fills at open, dual feed, friction
├── trade_log.csv + equity curve + ops log
├── Independent Auditor verifies
└── QuantStats IS report

CHAOS ENGINEERING → fix before OOS

VALIDATION (2024) → compare to IS, no tuning

OOS — ONE TIME ONLY (2025–today)
└── QuantStats: all three periods + survivorship disclaimer

STRESS TEST → 2018–2022 bear market

PHASE B → post-hoc catalyst on Phase A entry dates

BEFORE PAPER TRADING
├── P14: Wire fundamentals_screen to live data
├── P18: Extend ops log
└── P11: ticker_state + watchlist_history

PHASE C → when point-in-time fundamentals available

AFTER PAPER TRADING
├── P17: ai_context_review + ai_synthesis
└── Optuna optimization
```

---

## Graduation Criteria

| Metric | Minimum | Target |
|---|---|---|
| Trade count | ≥30 | — |
| Win/loss size ratio | ≥2.0 | 3.0 |
| Max drawdown | ≤25% | — |

---

## Change Log

- v1 — 8 problems identified.
- v2 — Problems 9–11 added (Intraday Path, Currency Devaluation, Data
  Persistence). Priority Table. T+2 removed.
- v3 — Problems 12–18 added (CONFIG_PATH, category_tagging stub,
  fundamentals not wired, .env, Ledger, ai stages, technical reviewer).
- v4 — Problems 19–24 added from deep technical code audit (RS flat
  broadcast, no runner script, CWD receipts, requirements.txt,
  KILL_SWITCH snapshot, RS warmup). Blockers corrected to 12.

---

## v5 Additions — Runtime-Confirmed Bugs from Execution Testing

**Version**: v5 — 45 items catalogued total. Three confirmed Tier 0 structural
impossibilities (pipeline can NEVER produce a signal in current state).
Three confirmed runtime crashes. Updated blocker count.

---

### TIER 0 — Structurally Impossible to Produce a Signal (Fix First)

These three bugs mean the pipeline cannot generate a single trade regardless
of data quality, parameters, or configuration. Everything else is irrelevant
until these are fixed.

**T0-A: Market Regime Gate permanently closed** (confirmed across 490 bars)

`kashif_strategy.py:414` — `_new_high_low_ratio_favorable_snapshot` builds
a constant series by repeating today's single count 22 times:
```python
pd.Series([sum(highs)] * 22)
```
Then `new_high_low_ratio_favorable()` checks `ratio > ratio.shift(21)`.
A constant compared to itself shifted is always equal, never greater.
`new_high_low_ratio_favorable` is **False on every bar, forever.**
Since the regime gate is an AND of 3 conditions, the gate never opens.
No ticker ever reaches the hard filter.

**Fix**: compute the ratio as a rolling time series, not a single-value
broadcast. Fetch 22+ days of universe-wide 52-week high/low counts and
build a real rolling series before comparing `ratio[t] > ratio[t-21]`.

**T0-B: VCP weekly monotonicity impossible with 1 contraction** (confirmed
all 5 test tickers return `WEEKLY_BASE_REJECTED:MONOTONICITY_FAILED`)

`vcp_detection.py:440` — `rule_a` requires `depths[-1] <= depths[0] * 0.75`.
With only 1 contraction: `depths[-1] == depths[0]`, so the rule demands
`depth <= depth * 0.75` — impossible for any positive depth.

With 2 years (~105 weekly bars), `detect_swings` finds 3–4 peaks/troughs,
producing 1-contraction bases. Every weekly base fails rule_a automatically.

**Fix**: rule_a must be skipped (or trivially True) when there is only one
contraction — a single-contraction base cannot fail a monotonicity test
by definition. Rule_a compares the first and last contraction — with only
one, they are the same contraction, and the comparison is meaningless.
Apply monotonicity only when `len(depths) >= 2`.

**T0-C: Regime gate requires 22+ viable tickers** (runtime constraint)

`kashif_strategy.py:412` — `_new_high_low_ratio_favorable_snapshot` returns
`False` early if `len(highs) < 22`. With 29 of 224 tickers returning zero
data from yfinance (confirmed — see item 39 below), the effective universe
is ~195. At full scale this threshold is reachable, but any subset test,
demo run, or development test with fewer than 22 viable tickers can never
open the gate. Not a production blocker, but blocks all development testing.

**Fix**: document the 22-ticker minimum in the runner script. Add a startup
check that warns if the loaded universe is below 22 viable tickers.

---

### Confirmed Runtime Crashes

**C-1: `compute_composite` crashes on empty `eps` list** (IndexError confirmed)

`fundamentals_screen.py:248` — `score_earnings_growth(eps[-1], category)`
throws `IndexError` when `eps_yoy_growth_by_quarter` is an empty list.
No length guard exists in `compute_composite`. Turnaround companies or
newly-listed tickers with no quarterly history will crash the pipeline.

**Fix**: guard at entry to `compute_composite`:
```python
if not eps_yoy_growth_by_quarter:
    return {"composite": None, "excluded": ["all"], "reason": "no_eps_data"}
```

**C-2: `compute_peg_modifier` crashes on PEG ≤ 0** (ValueError confirmed)

`fundamentals_screen.py:160` — `math.log2(peg)` raises `ValueError: math
domain error` when `peg <= 0`. Turnaround companies with negative earnings
commonly have negative or undefined PEG.

**Fix**:
```python
if peg is None or peg <= 0:
    return 0.0  # no modifier — same as neutral PEG
```

**C-3: `compute_composite` crashes when `margin_by_quarter` is None** (TypeError confirmed)

`fundamentals_screen.py:104` — `score_code_33` calls `len(margin_by_quarter)`
which throws `TypeError` when margin is `None`. The None check only covers
`revenue_yoy_growth_by_quarter`, not margin.

**Fix**: add `if margin_by_quarter is None: return None` guard at the top
of `score_code_33`, parallel to the revenue guard.

---

### New Items — Not Previously in Roadmap

**N-1: `code_33 None → 0.0` latent bug** (harmless now, breaks on refactor)

`fundamentals_screen.py:269` — `1.0 if scores_bool["code_33"] else 0.0`
converts `None` (legitimately excluded) to `0.0` and includes it in the
weighted sum. Currently harmless because excluded screens have 0.0 weight
(so `0.0 * 0.0 = 0`), but breaks silently if exclusion logic changes.

**Fix**: explicit None check:
```python
if scores_bool["code_33"] is None:
    pass  # already excluded via renormalization
else:
    score = 1.0 if scores_bool["code_33"] else 0.0
```

**N-2: `detect_source_flip` ignores its first argument** (misleading signature)

`fundamentals_screen.py:256-261` — Function signature `detect_source_flip(sources, window)`
but only `window` is iterated inside. `sources` parameter is unused.
Harmless now, dangerous if someone adds logic using `sources` expecting
the full list.

**Fix**: remove the unused `sources` parameter or rename to make clear only
`window` is used.

**N-3: Two competing stop orders on add-on buys** (real money risk)

`kashif_strategy.py:720-727` — When a second buy fills for the same ticker,
`self.stop_order[d]` is overwritten with a new stop for the second tranche.
The first stop is still live — now two competing stop orders exist for
different sizes. The first could fill unexpectedly, partially closing the
position while the second is still pending for shares that may not exist.

**Fix**: cancel the existing stop before placing a new one:
```python
if d in self.stop_order and self.stop_order[d]:
    self.cancel(self.stop_order[d])
self.stop_order[d] = self.sell(...)  # new consolidated stop
```
The new stop should cover the full position size at the blended entry price.

**N-4: Breakeven stop uses first-entry price, not blended average**

`kashif_strategy.py:690` — `self.entry_price[d]` holds the first entry
price. If a second buy added at a higher price, the blended cost basis
is higher than `entry_price` — the stop is placed too low, giving more
risk than the intended 10% per position.

**Fix**: update `self.entry_price[d]` to `pos.price` (backtrader's
blended average) after every add-on buy in `notify_order`.

**N-5: `backfill_catalyst_returns` uses calendar days, not trading days**

`backfill_catalyst_returns.py:115` — `target_date = score_date + timedelta(days=days)`.
The `FORWARD_RETURN_DAYS = [10, 20, 60]` constants should be trading days
per Minervini's methodology. 10 calendar days ≈ 7–8 trading days. Combined
with `_fetch_close_on_or_after` fetching the nearest available bar, forward
returns can be measured over systematically shorter trading periods.

**Fix**: use `pandas_market_calendars` or a simple business-day offset:
```python
from pandas.tseries.offsets import BDay
target_date = score_date + BDay(days)
```

**N-6: `catalyst_check` appends track record on every call, including backtests**

`catalyst_check.py:906` — Unconditional append. A 195-ticker × 500-bar
backtest writes ~97,500 lines per run with duplicates across reruns.
Confirmed: 3 duplicate COMI entries already after a few test runs.

**Fix**: add a `log_track_record=True` parameter to `catalyst_check()`.
The backtest runner passes `log_track_record=False`. Live/paper trading
passes `log_track_record=True` (default).

**N-7: 29 of 224 tickers return zero data from yfinance** (confirmed list)

Zero-data tickers: QNBE, VLMR, VLMRA, VALU, TAQA, UBEE, BONY, KORA,
ACAP, NAPR, GOUR, CRST, ACTF, GTWL, ALRA, NARE, PHGC, GPIM, GGRN, AMII,
AIDC, GTEX, POCO, KRDI, TANM, TYCN, AIHC, DGTZ, CPME.

**Fix**: pre-filter in `run_backtest.py` before loading feeds:
```python
SKIP_TICKERS = {"QNBE", "VLMR", ...}  # confirmed zero-data list
valid_tickers = [t for t in TICKERS if t not in SKIP_TICKERS]
```
Add a startup log: "Loaded N tickers, skipped M zero-data tickers."

**N-8: `google-generativeai` SDK deprecated — could stop working**

`FutureWarning: All support for the google.generativeai package has ended.`
The replacement is `google.genai`. The old SDK could stop working at any time.

**Fix**: migrate from `google.generativeai` to `google.genai` before the
old SDK breaks. This is a dependency update, not a logic change. Low effort,
high importance before any production use.

**N-9: `score_with_model` is NOT a stub — makes real Gemini calls, costs money**

The strategy docstring says "score_with_model() is still a deliberate stub."
The actual code at `catalyst_check.py:686` makes live Gemini 3.6 Flash API
calls and returns real scores. The docstring is stale. Every backtest bar
that reaches catalyst_check() costs real API quota.

**Fix**: update the docstring. Add a `IS_STUB = False` constant so callers
can programmatically check whether the model is wired. Pass
`log_track_record=False` in backtests (N-6) to avoid accumulating costs.

**N-10: `compute_indicators` rebuilds all rolling windows from scratch every bar**

`kashif_strategy.py:443-445` — Each `_evaluate_entry_pipeline` call
converts the full 260-bar deque to a DataFrame and recomputes all 7 rolling
windows (SMA-50, SMA-150, SMA-200, 52-week high/low, 252-day return,
SMA-200 slope). Benchmarked at 1.6ms per call. At 195 tickers × 490 bars:
~152 seconds of pure indicator recomputation.

**Fix**: compute indicators once per bar for all tickers (vectorized),
cache the result in a dict keyed by `(ticker, bar_date)`, and read from
cache in `_evaluate_entry_pipeline`. Same approach as the RS snapshot cache.

**N-11: Fundamentals wireable at ~65% coverage — positive finding**

COMI returns 7 quarters of Net Income, Total Revenue, Basic EPS, Diluted EPS
via `quarterly_income_stmt`. ~35% of tickers have no quarterly data.
This means F2 can be wired with robust NaN handling — better than expected.
Update P14 in the roadmap: fundamentals wiring is feasible now, not "future."

---

## Updated Priority Table Additions (v5)

| # | Problem | Blocks Phase A? | Priority | Can Skip? |
|---|---|---|---|---|
| T0-A | Regime gate permanently closed (confirmed) | **YES** | **TIER 0** | ❌ |
| T0-B | VCP weekly monotonicity impossible (confirmed) | **YES** | **TIER 0** | ❌ |
| T0-C | Regime needs 22+ tickers minimum | Dev testing only | P1 | ✅ Workaround |
| C-1 | empty eps IndexError (confirmed crash) | **YES** | **BLOCKER** | ❌ |
| C-2 | PEG≤0 log2 crash (confirmed crash) | **YES** | **BLOCKER** | ❌ |
| C-3 | margin None TypeError (confirmed crash) | **YES** | **BLOCKER** | ❌ |
| N-1 | code_33 None→0.0 latent bug | No — harmless now | P2 | ✅ Fix before refactor |
| N-2 | detect_source_flip ignores first arg | No — misleading | P2 | ✅ Fix before refactor |
| N-3 | Two competing stops on add-on buys | **YES** | **BLOCKER** | ❌ |
| N-4 | Breakeven stop wrong blended price | **YES** | **BLOCKER** | ❌ |
| N-5 | Backfill uses calendar not trading days | No — post-hoc only | P1 | ✅ Fix before Phase B |
| N-6 | Track record appends in backtest | **YES** — costs money | **BLOCKER** | ❌ |
| N-7 | 29 zero-data tickers (confirmed list) | **YES** — crashes | **BLOCKER** | ❌ |
| N-8 | google-generativeai SDK deprecated | No — not broken yet | P1 | ✅ Fix before production |
| N-9 | score_with_model NOT a stub — real cost | **YES** — stale docs | **BLOCKER** | ❌ |
| N-10 | compute_indicators rebuilt every bar | No — performance | P2 | ✅ Fix before full backtest |
| N-11 | Fundamentals wireable at 65% | Positive — update P14 | — | — |

**Updated BLOCKER count: 19 total** (was 12 before v5 audit)

Two Tier 0 structural bugs (T0-A, T0-B) sit above all blockers in priority.
Fix these first or nothing else matters.

---

## v5 Change Log Entry

- v5 — 45 items total. Three Tier 0 structural impossibilities confirmed by
  runtime execution (regime gate always False, VCP weekly monotonicity always
  fails, 22-ticker minimum). Three confirmed runtime crashes (empty eps
  IndexError, PEG≤0 log2 ValueError, margin None TypeError). Eleven new items:
  latent code_33 bug, misleading source_flip signature, competing stops on
  add-on buys, wrong blended price for breakeven stop, calendar-vs-trading-day
  backfill error, unconditional track record appending, 29 confirmed zero-data
  tickers, deprecated SDK, stale stub docstring with real API cost, indicator
  rebuild performance, and the positive finding that fundamentals are wireable
  at ~65% EGX coverage.
