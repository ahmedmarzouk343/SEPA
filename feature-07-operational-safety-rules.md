# Kashif — Engineering Rules: Operational Safety (Feature 7)

*Source of truth for Claude Code on this feature. Supersedes verbal instructions
given in chat — if chat and this file disagree, this file wins until it's
explicitly updated. Living document.*

**Status:** Ready to build. Both items are explicitly listed in the original
roadmap (kashif-roadmap.md Phase 2: "Build the global kill switch"; Phase 4:
"Daily spend tracker/alert live") and were never built during Features 1–6.
Neither is a trading feature — both are operational hygiene required before
paper trading starts.

---

## 0. What this feature is

Two small, additive items. No new trading logic. No changes to existing
pipeline decisions.

**Item 1 — Global Kill Switch**: a single flag that halts new entry evaluation
immediately when set to True. Required because without it, stopping the pipeline
in an emergency (bad data day, API outage, runaway retry loops) requires
manually killing the process.

**Item 2 — Daily Operations Log**: a lightweight JSON file written at the end
of each pipeline run. Answers: "did today's run complete, and did it cost
anything unexpected?" Directly motivated by the rate-limit finding from Feature 6
(gemini-3.6-flash free tier, 5 RPM cap, observed fallback-to-NEUTRAL behavior
documented in known_gaps_and_todos).

---

## 1. Source of truth

1. `kashif-roadmap.md` — Phase 2 item ("Build the global kill switch") and
   Phase 4 item ("Daily spend tracker/alert live")
2. `kashif-project-summary.md` — original kill switch requirement:
   "one global pause that halts all strategies immediately, independent of
   per-strategy logic"
3. `minervini_sepa_v1_strategy_config.json` → known_gaps_and_todos — rate-limit
   pacing entry (added v0.24) that motivated the ops log

---

## 2. Item 1 — Global Kill Switch

### 2.1 What it does

Halts ALL new entry evaluation across all strategies immediately when set to
True. Does NOT prevent exit checks on held positions — stopping losses on
existing positions must continue regardless of the kill switch state.

From `kashif-project-summary.md`: "one global pause that halts all strategies
immediately, independent of per-strategy logic."

### 2.2 Implementation

**New file: `kashif_config.py`**
```python
# Global operational flags — edit this file to control pipeline behavior.
# Restart the pipeline after changing any flag for it to take effect.

KILL_SWITCH = False  # Set to True to halt all new entry evaluation immediately.
                     # Held positions will still receive exit checks (stop-loss,
                     # largest-decline flag) — the kill switch only prevents
                     # NEW entries, it does not abandon existing positions.
```

**Change in `kashif_strategy.py` — top of `next()` only:**
```python
from kashif_config import KILL_SWITCH

def next(self):
    # --- KILL SWITCH CHECK (must be first, before any pipeline logic) ---
    if KILL_SWITCH:
        self._log_decision_receipt(
            date=self.data.datetime.date(0),
            ticker="ALL",
            stage="KILL_SWITCH",
            result="HALTED",
            note="KILL_SWITCH=True in kashif_config.py -- new entry evaluation skipped"
        )
        # Still run exit checks on held positions
        self._check_exit_signals()
        return
    # ... rest of next() unchanged ...
```

### 2.3 What does NOT change

- No UI, no API endpoint, no webhook
- No per-strategy kill switch — this is global by design
- No automatic reset — flipping back to False requires a human edit
- Held positions continue receiving exit checks (stop-loss, breakeven trigger,
  largest-decline flag) — this is a deliberate safety property, not an oversight

### 2.4 Testing

No known-answer test file needed — the kill switch has no math to verify.
Functional test only: set KILL_SWITCH=True, run one pipeline iteration,
confirm no new entries were attempted and the Decision Receipt contains the
KILL_SWITCH log line. Then set back to False, confirm normal operation resumes.
Include this as a manual smoke test, not an automated fixture.

---

## 3. Item 2 — Daily Operations Log

### 3.1 What it does

Writes one JSON file per pipeline run summarizing operational health. Answers:
did the run complete, how many tickers were evaluated at each stage, how many
API calls were made, how many failed or fell back to NEUTRAL, and what is the
current portfolio state.

Directly motivated by: gemini-3.6-flash's 5 RPM free-tier cap means tickers
beyond the 5th in a run will fall back to NEUTRAL with error_flag=True. Without
this log, that behavior is invisible — you would not know whether catalyst
scoring is working or silently degrading.

### 3.2 File location and naming

```
C:\Users\Asuss\Stocks\daily_ops_log\ops_YYYYMMDD.json
```

One file per calendar day. Overwrite if the pipeline re-runs the same day
(the latest run's data is the relevant one). Create the directory if it does
not exist.

### 3.3 Schema — all fields required

```python
{
    "run_date": "YYYY-MM-DD",
    "run_completed": bool,           # True if pipeline ran to completion
                                     # without unhandled exceptions
    "tickers_scanned": int,          # total tickers evaluated in next()
    "tickers_passing_hard_filter": int,
    "tickers_reaching_catalyst_check": int,
    "catalyst_api_calls_made": int,  # calls that reached score_with_model()
    "catalyst_api_errors": int,      # 429s and other model call failures
    "catalyst_fallback_to_neutral": int,  # times error_flag=True returned
    "arabfinance_fetch_errors": int, # HTTP errors from ArabFinance fetch
    "google_news_rss_errors": int,   # HTTP errors from Google News RSS
    "new_entries_signaled": int,     # buy signals generated this run
    "exit_signals_flagged": int,     # exit candidates flagged this run
    "kill_switch_active": bool,      # value of KILL_SWITCH at run time
    "positions_held": int,           # open positions at end of run
    "portfolio_equity_egp": float,   # broker.getvalue() at end of run
    "pipeline_errors": []            # list of unhandled exception strings
                                     # empty list if clean run
}
```

### 3.4 Counter wiring

These counters must be incremented in the right places:

- `tickers_scanned`: increment in `next()` for every ticker evaluated
- `tickers_passing_hard_filter`: increment when `evaluate_conditions()` returns
  all_pass=True for a ticker
- `tickers_reaching_catalyst_check`: increment just before `catalyst_check()`
  is called
- `catalyst_api_calls_made`, `catalyst_api_errors`, `catalyst_fallback_to_neutral`:
  `catalyst_check.py` already returns `error_flag` — use that. Increment
  `catalyst_api_calls_made` on every real model call attempt.
  Increment `catalyst_api_errors` on each 429 or exception.
  Increment `catalyst_fallback_to_neutral` when `error_flag=True` is returned.
- `arabfinance_fetch_errors`, `google_news_rss_errors`: already handled
  gracefully in `catalyst_check.py` — increment counters there on HTTP errors.
- `new_entries_signaled`: increment when `buy()` is called in `next()`
- `exit_signals_flagged`: increment when an exit_candidate flag is set
- `positions_held`: `len(self.broker.positions)` at end of run
- `portfolio_equity_egp`: `self.broker.getvalue()` at end of run

### 3.5 Threshold alert

If `catalyst_fallback_to_neutral > 3` on any single run:

```python
print(
    f"WARNING: {n} tickers fell back to NEUTRAL due to API rate limits today. "
    f"Consider adding inter-call sleep. "
    f"See known_gaps_and_todos in minervini_sepa_v1_strategy_config.json."
)
```

Print to console only — do not block the pipeline or raise an exception.
The warning is informational.

### 3.6 Write timing

Write the ops log at the very end of the backtrader run — in `stop()` method
of KashifStrategy, which backtrader calls once after all bars have been
processed. This guarantees the log reflects the complete run, not an
intermediate state.

```python
def stop(self):
    self._write_ops_log()
```

### 3.7 Testing

**Fixture 1 — clean run**: run a synthetic backtrader session with no errors.
Confirm ops log is written, all fields present, `run_completed=True`,
`pipeline_errors=[]`.

**Fixture 2 — rate-limit fallback detection**: inject a synthetic catalyst
result with `error_flag=True` for 4 tickers. Confirm `catalyst_fallback_to_neutral=4`
in the ops log AND the WARNING is printed to console.

**Fixture 3 — kill switch logging**: set `KILL_SWITCH=True`, run one bar.
Confirm `kill_switch_active=True` in the ops log, `new_entries_signaled=0`.

**Fixture 4 — append-only directory**: run twice on the same date. Confirm
the second run overwrites the first (latest run wins), not appends to it.

---

## 4. Deliverables checklist

- [ ] `kashif_config.py` — KILL_SWITCH flag with explanatory comments
- [ ] `kashif_strategy.py` — kill switch check at top of `next()`, exit checks
  still run when kill switch is active, ops log write in `stop()`
- [ ] `catalyst_check.py` — arabfinance and google_news_rss error counters
  wired out to the ops log (pass counter references or return them in the
  output dict)
- [ ] `daily_ops_log/` directory created, `ops_YYYYMMDD.json` written correctly
- [ ] Known-answer test file covering Fixtures 1–4 from Section 3.7
- [ ] Updated `minervini_sepa_v1_strategy_config.json` — add kill_switch and
  daily_ops_log to the config, bump version, add changelog entry

---

## Change Log

- v1 — initial version. Both items were in the original roadmap (Phase 2 and
  Phase 4) and were never built during Features 1–6. Written as a rules doc
  retroactively before handing to Claude Code — same standard as every prior
  feature.
