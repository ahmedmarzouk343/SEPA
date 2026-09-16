"""
Known-answer regression test for Feature 7 (Operational Safety): the
kill switch (kashif_config.py) and the Daily Operations Log
(kashif_strategy.py's _write_ops_log()/stop()), covering all 4 fixtures
from feature-07-operational-safety-rules.md Section 3.7.

Same discipline as every prior feature: predictions independently
scratch-verified via the real code BEFORE being written into this
docstring. Wrong predictions left visible with a [CORRECTED -- ...] note
rather than silently fixed.

--------------------------------------------------------------------------
NO KNOWN-ANSWER FIXTURES FOR THE KILL SWITCH ITSELF, per spec Section 2.4:
"the kill switch has no math to verify... Include this as a manual smoke
test, not an automated fixture." Fixture 3 below tests the OPS LOG's
recording of kill_switch_active/new_entries_signaled, which does have a
checkable answer -- it does not re-litigate whether KILL_SWITCH itself
"works" beyond that.
--------------------------------------------------------------------------

--------------------------------------------------------------------------
ONE REAL BUG FOUND AND FIXED while smoke-testing _write_ops_log() before
writing these fixtures (documented in kashif_strategy.py's own inline
comment at the fix site too)
--------------------------------------------------------------------------
[CORRECTED -- logic error] Section 3.4's own literal suggestion for
positions_held, "len(self.broker.positions)", is NOT the same thing as
"open positions at end of run" (the field's own stated meaning in Section
3.3) once a strategy calls self.broker.getposition(d) broadly. Confirmed
empirically with a standalone backtrader probe: getposition() lazily
creates a Position entry (size=0) in broker.positions the FIRST TIME it is
called for a data feed, even if no trade ever happens. KashifStrategy's
next() calls getposition() for EVERY ticker EVERY bar (to decide exit vs.
entry-pipeline), so a literal len(self.broker.positions) equals the total
ticker count ever scanned, not the count actually holding a position --
confirmed by a first smoke run showing positions_held=1 on a completely
flat, trade-free 10-bar single-ticker session. Fixed to count only
nonzero-size entries.

--------------------------------------------------------------------------
P23 FIX NOTE -- KILL_SWITCH now uses live module reference
--------------------------------------------------------------------------
kashif_strategy.py now does `import kashif_config` and reads
`kashif_config.KILL_SWITCH` (P23 fix). This is a LIVE reference to
kashif_config's module attribute. Fixture 3 toggles via
`kashif_config.KILL_SWITCH = True`, which is immediately observed by
kashif_strategy.py's next() method without restart.

--------------------------------------------------------------------------
WRITTEN PREDICTIONS -- independently scratch-verified via the real code
BEFORE being written here
--------------------------------------------------------------------------

FIXTURE 1 -- clean run. A minimal, real 10-bar single-ticker backtrader
  session (flat price, no possible entry given insufficient history for
  market_regime_gate/hard_filter) run to completion via cerebro.run().
  PREDICTED: daily_ops_log/ops_<today>.json is written and contains all 14
  schema fields (run_date, run_completed, tickers_scanned,
  tickers_passing_hard_filter, tickers_reaching_catalyst_check,
  catalyst_api_calls_made, catalyst_api_errors, catalyst_fallback_to_neutral,
  arabfinance_fetch_errors, google_news_rss_errors, new_entries_signaled,
  exit_signals_flagged, kill_switch_active, positions_held,
  portfolio_equity_egp, pipeline_errors). PREDICTED: run_completed=True,
  pipeline_errors=[], tickers_scanned=10 (one increment per bar for the
  single ticker), positions_held=0 (confirmed empirically after the
  positions_held fix above), portfolio_equity_egp=100000.0 (starting cash,
  unchanged -- no trade ever executes), kill_switch_active=False.

FIXTURE 2 -- rate-limit fallback detection. A real KashifStrategy instance
  (via a minimal real Cerebro run) has _update_catalyst_counters() called
  DIRECTLY 4 times with a synthetic {"error_flag": True, "model_call_
  attempted": True, "retry_log": [...]} result each time -- the same
  direct-call-the-real-update-method precedent as Feature 4's
  _update_defensive_mode()/_update_streak_state() fixtures, needed here
  because organically reaching Stage 5 for 4 real tickers would require
  253+ bars of history, HIGH/MEDIUM disclosure priority, and real network
  calls for each.
  PREDICTED: after stop() runs, the ops log shows
  catalyst_fallback_to_neutral=4, catalyst_api_calls_made=4 (all 4 synthetic
  results had model_call_attempted=True), and the console WARNING is
  printed (4 > 3, the Section 3.5 threshold), containing the exact
  substring "4 tickers fell back to NEUTRAL".

FIXTURE 3 -- kill switch logging. kashif_strategy.KILL_SWITCH patched to
  True (see the import-binding note above), one bar run via a real,
  minimal Cerebro session.
  PREDICTED: the ops log shows kill_switch_active=True and
  new_entries_signaled=0 (no entry pipeline ever runs while the kill
  switch is active -- next() returns immediately after the exit-checks-only
  branch). PREDICTED: the persisted Decision Receipt for that bar
  (decision_receipts_20240101.jsonl -- make_flat_feed()'s default
  start="2024-01-01" makes the bar date, and therefore this filename,
  predictable) contains a ticker="ALL", stages={"kill_switch": "HALTED"},
  final_verdict="KILL_SWITCH_HALTED" record.
  [TEST-HARNESS BUG CAUGHT AND FIXED while building this fixture, not a
  kashif_strategy.py defect]: the first draft tried to read
  strat.decision_receipts directly right after next() returned -- but
  next() both appends the kill-switch receipt AND calls
  _flush_decision_receipts_for_date() (which clears decision_receipts back
  to []) within that SAME call, so the in-memory list was already empty by
  the time the test looked at it. Fixed by reading the actual persisted
  .jsonl file the flush wrote to instead -- which is also the more
  meaningful check, since that file is the real, durable artifact.

FIXTURE 4 -- overwrite, not append (Section 3.2: "Overwrite if the pipeline
  re-runs the same day"). Two SEPARATE real Cerebro sessions run back to
  back on the same calendar day (same wall-clock "today" -- _write_ops_log()
  uses datetime.now().date(), not any bar's date, so this holds regardless
  of what synthetic bar dates each session uses) with DELIBERATELY
  DIFFERENT bar counts (Run A: 10 bars: Run B: 3 bars), so
  tickers_scanned differs between them (10 vs 3) and is unambiguous
  evidence of which run's data survived.
  PREDICTED: after Run A alone, the ops log file shows tickers_scanned=10.
  PREDICTED: after Run B runs on top of it (same file path, same day),
  the ops log shows tickers_scanned=3 -- Run B's value, not 13 (which
  would indicate accidental accumulation) and not still 10 (which would
  indicate the second write silently failed). PREDICTED: the file contains
  exactly one JSON object (not two concatenated), confirming plain
  overwrite ("w" mode), not append ("a" mode).
"""

import io
import json
import os
import sys
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd  # noqa: E402
import backtrader as bt  # noqa: E402

import kashif_strategy  # noqa: E402
import kashif_config  # noqa: E402
from kashif_sizer import MinerviniSizer  # noqa: E402
from kashif_strategy import KashifStrategy, OPS_LOG_DIR  # noqa: E402


def make_flat_feed(n_bars, name="T", price=100.0, volume=100000.0, start="2024-01-01"):
    dates = pd.date_range(start, periods=n_bars, freq="B")
    df = pd.DataFrame({
        "open": [price] * n_bars, "high": [price * 1.01] * n_bars,
        "low": [price * 0.99] * n_bars, "close": [price] * n_bars,
        "volume": [volume] * n_bars,
    }, index=dates)
    return bt.feeds.PandasData(dataname=df, name=name)


def run_cerebro(n_bars, strategy_cls=KashifStrategy, name="T", **strat_kwargs):
    cerebro = bt.Cerebro()
    cerebro.adddata(make_flat_feed(n_bars, name=name))
    cerebro.broker.setcash(100000)
    cerebro.broker.setcommission(commission=0.0)
    cerebro.broker.set_coc(False)
    cerebro.addstrategy(strategy_cls, **strat_kwargs)
    cerebro.addsizer(MinerviniSizer)
    results = cerebro.run()
    return results[0]


def ops_log_path():
    import datetime
    today = datetime.datetime.now().date()
    return os.path.join(OPS_LOG_DIR, f"ops_{today.strftime('%Y%m%d')}.json")


def read_ops_log():
    with open(ops_log_path(), encoding="utf-8") as f:
        return json.load(f)


REQUIRED_SCHEMA_FIELDS = [
    "run_date", "run_completed", "tickers_scanned", "tickers_passing_hard_filter",
    "tickers_reaching_catalyst_check", "catalyst_api_calls_made", "catalyst_api_errors",
    "catalyst_fallback_to_neutral", "arabfinance_fetch_errors", "google_news_rss_errors",
    "new_entries_signaled", "exit_signals_flagged", "kill_switch_active", "positions_held",
    "portfolio_equity_egp", "pipeline_errors",
]


def main():
    failures = []

    def check(label, predicted, actual):
        ok = predicted == actual
        status = "OK" if ok else "MISMATCH"
        print(f"  [{status}] {label}: predicted={predicted!r} actual={actual!r}")
        if not ok:
            failures.append(f"{label}: predicted {predicted!r}, got {actual!r}")

    # ============================================================
    print("=" * 70)
    print("FIXTURE 1 -- clean run")
    print("=" * 70)
    run_cerebro(10, name="F1")
    check("1 ops log file exists", True, os.path.exists(ops_log_path()))
    ops1 = read_ops_log()
    check("1 all schema fields present", True, all(f in ops1 for f in REQUIRED_SCHEMA_FIELDS))
    check("1 run_completed", True, ops1["run_completed"])
    check("1 pipeline_errors", [], ops1["pipeline_errors"])
    check("1 tickers_scanned", 10, ops1["tickers_scanned"])
    check("1 positions_held", 0, ops1["positions_held"])
    check("1 portfolio_equity_egp", 100000.0, ops1["portfolio_equity_egp"])
    check("1 kill_switch_active", False, ops1["kill_switch_active"])

    # ============================================================
    print()
    print("=" * 70)
    print("FIXTURE 2 -- rate-limit fallback detection")
    print("=" * 70)

    class F2Strategy(KashifStrategy):
        def next(self):
            super().next()
            if len(self) == 1:  # inject once, on the first bar
                for _ in range(4):
                    self._update_catalyst_counters(
                        {"error_flag": True, "model_call_attempted": True,
                         "retry_log": [{"attempt": 1, "outcome": "rate_limited"},
                                       {"attempt": 2, "outcome": "rate_limited"},
                                       {"attempt": 3, "outcome": "rate_limited"},
                                       {"attempt": 4, "outcome": "error"}]}
                    )

    captured = io.StringIO()
    with redirect_stdout(captured):
        run_cerebro(3, strategy_cls=F2Strategy, name="F2")
    console_output = captured.getvalue()

    ops2 = read_ops_log()
    check("2 catalyst_fallback_to_neutral", 4, ops2["catalyst_fallback_to_neutral"])
    check("2 catalyst_api_calls_made", 4, ops2["catalyst_api_calls_made"])
    check("2 WARNING printed", True, "WARNING" in console_output)
    check("2 WARNING mentions '4 tickers fell back to NEUTRAL'", True,
          "4 tickers fell back to NEUTRAL" in console_output)

    # ============================================================
    print()
    print("=" * 70)
    print("FIXTURE 3 -- kill switch logging")
    print("=" * 70)
    original_kill_switch = kashif_config.KILL_SWITCH
    kashif_config.KILL_SWITCH = True

    # The kill-switch receipt is appended to self.decision_receipts and then
    # IMMEDIATELY flushed (and the in-memory list cleared) by the same
    # next() call, via _flush_decision_receipts_for_date() -- so the real,
    # persisted artifact to check is the decision_receipts_<bar_date>.jsonl
    # file it was flushed to, not the (already-empty) in-memory list
    # afterward. make_flat_feed()'s default start="2024-01-01" makes the
    # first bar's date -- and therefore this file's name -- predictable.
    # P21 fix: receipts now write to RECEIPTS_DIR (project dir / decision_receipts/)
    from kashif_strategy import RECEIPTS_DIR
    receipts_dir = RECEIPTS_DIR
    receipts_path = receipts_dir / "decision_receipts_20240101.jsonl"
    if receipts_path.exists():
        receipts_path.unlink()

    try:
        run_cerebro(1, strategy_cls=KashifStrategy, name="F3")
    finally:
        kashif_config.KILL_SWITCH = original_kill_switch

    ops3 = read_ops_log()
    check("3 kill_switch_active", True, ops3["kill_switch_active"])
    check("3 new_entries_signaled", 0, ops3["new_entries_signaled"])

    with open(receipts_path, encoding="utf-8") as f:
        flushed_receipts = [json.loads(line) for line in f if line.strip()]
    kill_receipts = [r for r in flushed_receipts if r.get("final_verdict") == "KILL_SWITCH_HALTED"]
    check("3 kill switch receipt recorded", 1, len(kill_receipts))
    check("3 kill switch receipt ticker", "ALL", kill_receipts[0]["ticker"] if kill_receipts else None)
    check("3 kill switch receipt stages", {"kill_switch": "HALTED"}, kill_receipts[0]["stages"] if kill_receipts else None)
    receipts_path.unlink()

    # ============================================================
    print()
    print("=" * 70)
    print("FIXTURE 4 -- overwrite, not append")
    print("=" * 70)
    run_cerebro(10, name="F4A")
    ops4a = read_ops_log()
    check("4 Run A tickers_scanned", 10, ops4a["tickers_scanned"])

    run_cerebro(3, name="F4B")
    with open(ops_log_path(), encoding="utf-8") as f:
        raw_text = f.read()
    ops4b = json.loads(raw_text)
    check("4 Run B tickers_scanned (overwrote Run A, not 10 or 13)", 3, ops4b["tickers_scanned"])
    check("4 file is exactly one JSON object (no concatenation)", 1, raw_text.count('"run_date"'))

    # ============================================================
    print()
    print("=" * 70)
    if failures:
        print(f"RESULT: MISMATCH -- {len(failures)} prediction(s) violated:")
        for f in failures:
            print(f"  - {f}")
    else:
        print("RESULT: MATCH -- every prediction confirmed exactly by the real code.")
    print("=" * 70)
    return len(failures) == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
