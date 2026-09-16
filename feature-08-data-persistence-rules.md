# Kashif — Engineering Rules: Data Persistence Layer (Feature 8)

*Source of truth for Claude Code on this feature. Supersedes verbal
instructions given in chat — if chat and this file disagree, this file
wins until it's explicitly updated. Living document.*

**Status:** Ready to build. Design agreed in chat before any code written.

---

## 0. Design Philosophy

**Reasons, not scores.** Every record must answer "why" in plain language,
not just "what number." A composite score of 78.4 is meaningless six months
later. "EPS grew 47% YoY accelerating from 31%, revenue also accelerating,
Code 33 confirmed, VCP base 8 weeks tight with volume drying up" is the
record worth keeping.

**Event-driven, not daily snapshots.** Records are written only when
something changes — a ticker enters the watchlist, fails a stage it
previously passed, generates a buy signal, or exits a position. Days where
nothing changes produce no records. This keeps files small and meaningful.

**Complete audit trail.** Every entry and exit must be fully reconstructable
from the records alone — entry date, entry price, shares, the exact reason
the system entered, the exact reason it exited, and what the market looked
like at both moments.

---

## 1. Source of truth

1. `minervini_sepa_v1_strategy_config.json` — pipeline stages, thresholds,
   graduation criteria
2. `backtest-roadmap.md` — P11 (data persistence, "before paper trading")
3. `kashif-project-summary.md` — original ledger and audit trail requirements
4. This document — schema and implementation spec

---

## 2. Two persistent stores

### 2.1 `watchlist_history.jsonl` — the event log

Append-only. One JSON line per event. Never overwrite, never delete.
This is the complete history of every decision the system made, in order.

**Location**: `Path(__file__).parent / "watchlist_history.jsonl"`

**Seven event types:**

| Action | When written |
|---|---|
| `ADDED` | First day a ticker passes hard_filter and enters the watchlist |
| `STAGE_FAILED` | Ticker was on watchlist, now fails a stage it previously passed |
| `ENTERED` | Buy signal fired — position opened |
| `HELD` | Position opened — written ONCE on the first holding day only, not daily |
| `STOP_HIT` | Position closed by stop-loss |
| `EXIT_SIGNAL` | Position closed by an exit signal (largest decline, P/E expansion, etc.) |
| `REMOVED` | Ticker dropped off watchlist without generating a buy (base expired, regime closed, etc.) |

**Re-entry rule**: if a ticker is REMOVED and later re-enters the watchlist,
write a new ADDED event. The prior cycle is already in the log. No artificial
linking between cycles.

**Schema — every event must include ALL of these fields:**

```json
{
  "event_id": "uuid4",
  "pipeline_run_id": "uuid4 — links all events from the same run",
  "date": "YYYY-MM-DD",
  "timestamp": "ISO 8601 with timezone",
  "ticker": "COMI",
  "action": "ENTERED",

  "pipeline_state": {
    "market_regime": {
      "result": "OPEN or CLOSED",
      "reason": "plain English — e.g. 'new high/low ratio rising over 21 days, leader basket showing higher lows while universe still declining'"
    },
    "hard_filter": {
      "result": "PASS or FAIL or SKIPPED",
      "conditions_passed": ["tt_1", "tt_2", "tt_3", "tt_4", "tt_5", "tt_6", "tt_7", "tt_8a", "tt_8b", "tt_9"],
      "conditions_failed": [],
      "reason": "plain English — e.g. 'all 10 Trend Template conditions confirmed, RS percentile 87th across EGX universe'"
    },
    "category_tag": {
      "result": "market_leader or turnaround or cyclical etc.",
      "market_cap_band": "small or mid or large",
      "years_since_ipo": 4.2,
      "reason": "plain English — e.g. 'mid-cap, 4 years since IPO, categorized as market_leader based on RS rank and sector position'"
    },
    "fundamentals": {
      "result": "PASS or FAIL or SKIPPED",
      "composite_score": 78.4,
      "earnings_growth": {
        "score": 0.85,
        "value": "47% YoY",
        "prior_quarter": "31% YoY",
        "reason": "accelerating, above 30% reward threshold"
      },
      "earnings_acceleration": {
        "score": 1.0,
        "quarters_accelerating": 3,
        "reason": "3 consecutive quarters of accelerating YoY EPS growth"
      },
      "revenue_confirmation": {
        "score": 0.9,
        "value": "38% YoY",
        "reason": "revenue growing alongside earnings, not earnings-only growth"
      },
      "code_33": {
        "result": "CONFIRMED or NOT_CONFIRMED or EXCLUDED",
        "reason": "3 consecutive quarters of simultaneous EPS + revenue + margin acceleration confirmed"
      },
      "earnings_quality": {
        "score": 0.8,
        "reason": "price held gains post-earnings for 8 trading days"
      },
      "deceleration_flag": {
        "penalty": 0.0,
        "reason": "no deceleration — growth rate increasing, not slowing"
      },
      "peg_modifier": {
        "modifier": 0.08,
        "peg_value": 0.6,
        "reason": "PEG 0.6 — below 1, growth at reasonable price"
      },
      "overall_reason": "plain English summary — e.g. 'Strong accelerating growth confirmed across earnings, revenue, and margins. Code 33 confirmed. No deceleration. PEG favorable.'"
    },
    "catalyst": {
      "result": "STRONG_POSITIVE or NEUTRAL or STRONG_NEGATIVE or SKIPPED",
      "source": "source name, YYYY-MM-DD",
      "event_description": "plain English — e.g. 'CBE preliminary approval for digital bank yomo, confirmed by Q2 2026 revenue +23% YoY'",
      "disclosure_category": "FinancialResults",
      "priority_tier": "HIGH",
      "reason": "regulatory approval — textbook catalyst type, reinforced by earnings beat in same window"
    },
    "entry_timing": {
      "result": "PASS or FAIL or SKIPPED",
      "base_number": 2,
      "base_duration_weeks": 8,
      "contraction_count": 3,
      "contraction_depths": [18.2, 11.4, 5.7],
      "final_contraction_depth_pct": 5.7,
      "volume_at_final_contraction": "below 50-day average — confirmed dry-up",
      "pivot_price": 142.5,
      "breakout_volume_ratio": 1.8,
      "reason": "plain English — e.g. '3-contraction VCP, depths decreasing 18%→11%→6%, volume dried up at handle, breakout on 1.8x average volume confirming institutional buying'"
    }
  },

  "position": {
    "entry_price": 142.5,
    "entry_date": "2024-03-15",
    "shares": 176,
    "position_value_egp": 25080.0,
    "stop_price": 128.25,
    "initial_stop_distance_pct": 10.0,
    "portfolio_equity_at_entry": 108450.0,
    "position_size_pct_of_portfolio": 23.1
  },

  "exit": {
    "exit_price": null,
    "exit_date": null,
    "exit_reason": null,
    "exit_description": null,
    "pnl_egp": null,
    "pnl_pct": null,
    "holding_days": null,
    "portfolio_equity_at_exit": null
  }
}
```

**Exit fields**: populated when STOP_HIT or EXIT_SIGNAL is written.
`exit_reason` is the specific trigger in plain English — e.g.:
- "Stop-loss hit — price gapped down to 118.0 at open, below stop of 128.25"
- "Largest single-day decline since entry (-8.4%) on 1.7x average volume — distribution signal"
- "P/E expanded to 3.1x entry P/E — extended, reduced conviction"
- "Post-earnings pop failed to hold over 7 trading days"

---

### 2.2 `ticker_state.parquet` — current state snapshot

One row per ticker, updated (not appended) on each event.
Used by the supervisor and paper trading loop for fast "what is the current
status of every ticker" queries without replaying the full JSONL history.

**Schema:**

| Column | Type | Description |
|---|---|---|
| ticker | string | EGX ticker symbol |
| last_updated | date | Date of most recent event |
| current_status | string | WATCHING / HELD / REMOVED / NEVER_QUALIFIED |
| days_on_watchlist | int | Calendar days since ADDED event (null if REMOVED) |
| stage_reached | string | Furthest pipeline stage reached |
| stage_failed_at | string | Stage where it currently fails (null if HELD) |
| failure_reason | string | Plain English reason for current failure |
| composite_score | float | Most recent fundamentals composite (null if SKIPPED) |
| vcp_quality_score | float | Most recent VCP quality score (null if not reached) |
| catalyst_score | string | Most recent catalyst result |
| position_entry_price | float | null if not currently held |
| position_entry_date | date | null if not currently held |
| position_shares | int | null if not currently held |
| position_current_stop | float | Current stop-loss price (updated as stop trails) |
| total_closed_trades | int | Lifetime count of closed positions |
| lifetime_pnl_egp | float | Lifetime realized P&L in EGP |

**Write pattern**: on every event for ticker X, read the current row for X,
update the relevant fields, write back. If X has no row yet, create one.

---

## 3. What does NOT get stored

- Daily snapshots when nothing changed — event-driven only
- Raw price data — that lives in yfinance cache
- Full OHLCV history — not duplicated here
- Intermediate calculation steps — only the final reason in plain English

---

## 4. Testing standard

Same discipline as Features 1–7 (known-answer fixtures, predictions before
code, wrong predictions left visible with correction notes).

**Required fixtures:**

- **Fixture 1 — ADDED event**: ticker passes hard_filter for the first time.
  Confirm event written with all pipeline_state fields populated. Confirm
  ticker_state.parquet row created with status=WATCHING.

- **Fixture 2 — STAGE_FAILED event**: ticker on watchlist fails fundamentals
  on a subsequent bar. Confirm event written with the specific sub-screen
  that failed and the plain English reason. Confirm ticker_state updated.

- **Fixture 3 — ENTERED event**: buy signal fires. Confirm all position
  fields populated (entry_price, shares, stop_price, portfolio_equity).
  Confirm plain English reason for entry timing includes contraction depths
  and volume ratio. Confirm ticker_state updated to HELD.

- **Fixture 4 — STOP_HIT event**: position stops out. Confirm exit fields
  populated including the specific gap-down or close-below-stop scenario.
  Confirm pnl_egp calculated correctly. Confirm ticker_state updated,
  lifetime_pnl_egp updated, total_closed_trades incremented.

- **Fixture 5 — REMOVED event**: ticker drops off watchlist (base exceeded
  65-week max duration). Confirm removal reason is specific, not generic.
  Confirm ticker_state status=REMOVED, days_on_watchlist populated.

- **Fixture 6 — Re-entry**: same ticker gets REMOVED then later re-enters.
  Confirm a fresh ADDED event is written. Confirm ticker_state reflects the
  new cycle, not the old one. Confirm watchlist_history.jsonl shows both
  cycles in order.

- **Fixture 7 — Append-only integrity**: run two consecutive events for the
  same ticker. Confirm watchlist_history.jsonl has two lines (not one
  overwritten). Confirm ticker_state.parquet has one row (updated, not
  duplicated).

---

## 5. Deliverables checklist

- [ ] `data_persistence.py` — `write_event()`, `update_ticker_state()`,
  `get_current_state(ticker)`, `query_watchlist_history(filters)` as
  separately callable/testable functions
- [ ] `watchlist_history.jsonl` — created on first run, append-only
- [ ] `ticker_state.parquet` — created on first run, one row per ticker
- [ ] Wire into `kashif_strategy.py` — call `write_event()` at every
  ADDED/STAGE_FAILED/ENTERED/HELD/STOP_HIT/EXIT_SIGNAL/REMOVED transition
- [ ] Known-answer test file covering all 7 fixtures
- [ ] Updated `minervini_sepa_v1_strategy_config.json` — add data_persistence
  section confirming stores are active, bump version

---

## Change Log

- v1 — initial version. Design agreed before any code written. Key decisions:
  event-driven not daily snapshots (only write on change), reasons not scores
  (plain English explanations at every stage), complete audit trail for every
  entry and exit. Schema covers all three use cases: "why did it buy X",
  "which stocks sat longest", "how many passed Trend Template but failed
  fundamentals."
