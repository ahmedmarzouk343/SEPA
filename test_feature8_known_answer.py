"""
test_feature8_known_answer.py — Known-answer fixtures for Feature 8 (Data Persistence Layer).

7 fixtures from feature-08-data-persistence-rules.md Section 4.
Predictions written BEFORE running code; wrong predictions stay
visible with [CORRECTED] notes.

Fixture 1: ADDED event — ticker passes hard_filter, event written, ticker_state row created
Fixture 2: STAGE_FAILED event — watchlist ticker fails a stage, event + state updated
Fixture 3: ENTERED event — buy signal fires, position fields populated, state = HELD
Fixture 4: STOP_HIT event — position stops out, exit fields + pnl populated, lifetime stats updated
Fixture 5: REMOVED event — ticker drops off watchlist, specific reason, days_on_watchlist populated
Fixture 6: Re-entry — same ticker REMOVED then re-ADDED, both cycles in JSONL
Fixture 7: Append-only integrity — two events => 2 lines in JSONL, 1 row in parquet
"""

import sys
import os
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    failures = []

    def check(label, expected, actual):
        ok = expected == actual
        status = "OK" if ok else "MISMATCH"
        print(f"  [{status}] {label}: expected={expected!r} actual={actual!r}")
        if not ok:
            failures.append(f"{label}: expected {expected!r}, got {actual!r}")

    def check_approx(label, expected, actual, tol=0.01):
        ok = abs(expected - actual) <= tol
        status = "OK" if ok else "MISMATCH"
        print(f"  [{status}] {label}: expected~={expected!r} actual={actual!r}")
        if not ok:
            failures.append(f"{label}: expected ~{expected!r}, got {actual!r}")

    import data_persistence as dp

    # ====================================================================
    # Fixture 1 — ADDED event
    # Prediction: write_event returns dict with event_id, action="ADDED",
    # ticker="COMI". ticker_state row created with status=WATCHING.
    # ====================================================================
    print("=" * 70)
    print("Fixture 1 -- ADDED event: ticker passes hard_filter first time")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as td:
        jsonl_path = Path(td) / "watchlist_history.jsonl"
        parquet_path = Path(td) / "ticker_state.parquet"

        with patch.object(dp, "WATCHLIST_HISTORY_PATH", jsonl_path), \
             patch.object(dp, "TICKER_STATE_PATH", parquet_path):

            added_event = {
                "event_id": "test-added-001",
                "pipeline_run_id": "run-001",
                "date": "2024-03-01",
                "timestamp": "2024-03-01T09:30:00+02:00",
                "ticker": "COMI",
                "action": "ADDED",
                "pipeline_state": {
                    "market_regime": {"result": "OPEN", "reason": "new high/low ratio rising"},
                    "hard_filter": {
                        "result": "PASS",
                        "conditions_passed": ["tt_1", "tt_2", "tt_3"],
                        "conditions_failed": [],
                        "reason": "All Trend Template conditions confirmed, RS percentile 87th",
                    },
                    "category_tag": {"result": "market_leader", "reason": "mid-cap leader"},
                    "fundamentals": {"result": "SKIPPED", "overall_reason": "Phase A"},
                    "catalyst": {"result": "SKIPPED", "reason": "not yet reached"},
                    "entry_timing": {"result": "SKIPPED", "reason": "not yet reached"},
                },
                "position": {
                    "entry_price": None, "entry_date": None, "shares": None,
                    "position_value_egp": None, "stop_price": None,
                    "initial_stop_distance_pct": None,
                    "portfolio_equity_at_entry": None,
                    "position_size_pct_of_portfolio": None,
                },
                "exit": {
                    "exit_price": None, "exit_date": None, "exit_reason": None,
                    "exit_description": None, "pnl_egp": None, "pnl_pct": None,
                    "holding_days": None, "portfolio_equity_at_exit": None,
                },
            }

            result = dp.write_event(added_event)
            check("F1 event_id preserved", "test-added-001", result["event_id"])
            check("F1 action is ADDED", "ADDED", result["action"])
            check("F1 ticker is COMI", "COMI", result["ticker"])

            # Verify JSONL file written
            check("F1 JSONL file exists", True, jsonl_path.exists())
            with open(jsonl_path, encoding="utf-8") as f:
                lines = f.readlines()
            check("F1 JSONL has 1 line", 1, len(lines))
            parsed = json.loads(lines[0])
            check("F1 JSONL action is ADDED", "ADDED", parsed["action"])
            check("F1 pipeline_state.hard_filter.result is PASS",
                  "PASS", parsed["pipeline_state"]["hard_filter"]["result"])

            # Create ticker_state row
            dp.update_ticker_state("COMI", {
                "current_status": "WATCHING",
                "stage_reached": "hard_filter",
                "last_updated": "2024-03-01",
            })
            state = dp.get_current_state("COMI")
            check("F1 ticker_state row exists", True, state is not None)
            check("F1 current_status is WATCHING", "WATCHING", state["current_status"])
            check("F1 stage_reached is hard_filter", "hard_filter", state["stage_reached"])

    # ====================================================================
    # Fixture 2 — STAGE_FAILED event
    # Prediction: event written with action=STAGE_FAILED, specific failure
    # reason. ticker_state updated with failure info.
    # ====================================================================
    print()
    print("=" * 70)
    print("Fixture 2 -- STAGE_FAILED event: watchlist ticker fails a stage")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as td:
        jsonl_path = Path(td) / "watchlist_history.jsonl"
        parquet_path = Path(td) / "ticker_state.parquet"

        with patch.object(dp, "WATCHLIST_HISTORY_PATH", jsonl_path), \
             patch.object(dp, "TICKER_STATE_PATH", parquet_path):

            # Setup: ticker was already on watchlist (ADDED)
            dp.update_ticker_state("COMI", {
                "current_status": "WATCHING",
                "stage_reached": "hard_filter",
            })

            stage_failed_event = {
                "event_id": "test-stagefail-001",
                "pipeline_run_id": "run-002",
                "date": "2024-03-05",
                "timestamp": "2024-03-05T09:30:00+02:00",
                "ticker": "COMI",
                "action": "STAGE_FAILED",
                "pipeline_state": {
                    "market_regime": {"result": "OPEN", "reason": "ratio favorable"},
                    "hard_filter": {
                        "result": "FAIL",
                        "reason": "tt_7 failed: RS percentile dropped to 62nd, below 70th threshold",
                    },
                    "category_tag": {"result": "SKIPPED", "reason": "blocked by hard_filter"},
                    "fundamentals": {"result": "SKIPPED", "overall_reason": "blocked"},
                    "catalyst": {"result": "SKIPPED", "reason": "blocked"},
                    "entry_timing": {"result": "SKIPPED", "reason": "blocked"},
                },
                "position": {
                    "entry_price": None, "entry_date": None, "shares": None,
                    "position_value_egp": None, "stop_price": None,
                    "initial_stop_distance_pct": None,
                    "portfolio_equity_at_entry": None,
                    "position_size_pct_of_portfolio": None,
                },
                "exit": {
                    "exit_price": None, "exit_date": None, "exit_reason": None,
                    "exit_description": None, "pnl_egp": None, "pnl_pct": None,
                    "holding_days": None, "portfolio_equity_at_exit": None,
                },
            }

            result = dp.write_event(stage_failed_event)
            check("F2 action is STAGE_FAILED", "STAGE_FAILED", result["action"])
            check("F2 hard_filter failed reason includes RS percentile",
                  True, "RS percentile" in result["pipeline_state"]["hard_filter"]["reason"])

            dp.update_ticker_state("COMI", {
                "failure_reason": "tt_7 failed: RS percentile dropped to 62nd",
                "stage_failed_at": "hard_filter",
                "last_updated": "2024-03-05",
            })
            state = dp.get_current_state("COMI")
            check("F2 failure_reason populated", True, "RS percentile" in str(state["failure_reason"]))
            check("F2 stage_failed_at is hard_filter", "hard_filter", state["stage_failed_at"])

    # ====================================================================
    # Fixture 3 — ENTERED event
    # Prediction: all position fields populated. entry_price=142.5,
    # shares=176, stop_price=128.25 (10% below entry).
    # position_value_egp = 142.5 * 176 = 25080.0
    # position_size_pct = 25080 / 108450 * 100 = 23.1%
    # ticker_state updated to HELD.
    # ====================================================================
    print()
    print("=" * 70)
    print("Fixture 3 -- ENTERED event: buy signal fires, position fields populated")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as td:
        jsonl_path = Path(td) / "watchlist_history.jsonl"
        parquet_path = Path(td) / "ticker_state.parquet"

        with patch.object(dp, "WATCHLIST_HISTORY_PATH", jsonl_path), \
             patch.object(dp, "TICKER_STATE_PATH", parquet_path):

            entered_event = {
                "event_id": "test-entered-001",
                "pipeline_run_id": "run-003",
                "date": "2024-03-15",
                "timestamp": "2024-03-15T09:30:00+02:00",
                "ticker": "COMI",
                "action": "ENTERED",
                "pipeline_state": {
                    "market_regime": {"result": "OPEN", "reason": "ratio favorable"},
                    "hard_filter": {"result": "PASS", "reason": "all TT conditions confirmed"},
                    "category_tag": {"result": "market_leader", "reason": "mid-cap leader"},
                    "fundamentals": {"result": "PASS", "overall_reason": "EPS grew 47% YoY accelerating from 31%"},
                    "catalyst": {"result": "STRONG_POSITIVE", "reason": "CBE regulatory approval"},
                    "entry_timing": {
                        "result": "PASS",
                        "reason": "3-contraction VCP, depths 18%->11%->6%, volume dried up, breakout on 1.8x volume",
                    },
                },
                "position": {
                    "entry_price": 142.5,
                    "entry_date": "2024-03-15",
                    "shares": 176,
                    "position_value_egp": 25080.0,
                    "stop_price": 128.25,
                    "initial_stop_distance_pct": 10.0,
                    "portfolio_equity_at_entry": 108450.0,
                    "position_size_pct_of_portfolio": 23.1,
                },
                "exit": {
                    "exit_price": None, "exit_date": None, "exit_reason": None,
                    "exit_description": None, "pnl_egp": None, "pnl_pct": None,
                    "holding_days": None, "portfolio_equity_at_exit": None,
                },
            }

            result = dp.write_event(entered_event)
            check("F3 action is ENTERED", "ENTERED", result["action"])
            check("F3 entry_price is 142.5", 142.5, result["position"]["entry_price"])
            check("F3 shares is 176", 176, result["position"]["shares"])
            check("F3 stop_price is 128.25", 128.25, result["position"]["stop_price"])
            # Hand-calculation: 142.5 * 176 = 25080.0
            check("F3 position_value_egp is 25080.0", 25080.0, result["position"]["position_value_egp"])
            # Hand-calculation: 25080 / 108450 * 100 = 23.12...% => 23.1 rounded
            check_approx("F3 position_size_pct is ~23.1", 23.1, result["position"]["position_size_pct_of_portfolio"])

            check("F3 entry_timing reason includes contraction depths",
                  True, "18%" in result["pipeline_state"]["entry_timing"]["reason"])
            check("F3 entry_timing reason includes volume ratio",
                  True, "1.8x" in result["pipeline_state"]["entry_timing"]["reason"])

            dp.update_ticker_state("COMI", {
                "current_status": "HELD",
                "stage_reached": "entry_timing",
                "position_entry_price": 142.5,
                "position_entry_date": "2024-03-15",
                "position_shares": 176,
                "position_current_stop": 128.25,
                "last_updated": "2024-03-15",
            })
            state = dp.get_current_state("COMI")
            check("F3 ticker_state status is HELD", "HELD", state["current_status"])
            check("F3 ticker_state entry_price is 142.5", 142.5, state["position_entry_price"])

    # ====================================================================
    # Fixture 4 — STOP_HIT event
    # Prediction: exit fields populated.
    # entry_price=142.5, exit_price=118.0, shares=176
    # pnl_egp = (118.0 - 142.5) * 176 = -4312.0
    # [CORRECTED: pnl_egp here is trade.pnl which includes commission/slippage,
    # but for this fixture we test raw calculation]
    # pnl_pct = (118.0 - 142.5) / 142.5 * 100 = -17.19%
    # total_closed_trades = 1 (first close), lifetime_pnl_egp = -4312.0
    # ====================================================================
    print()
    print("=" * 70)
    print("Fixture 4 -- STOP_HIT event: position stops out, exit fields populated")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as td:
        jsonl_path = Path(td) / "watchlist_history.jsonl"
        parquet_path = Path(td) / "ticker_state.parquet"

        with patch.object(dp, "WATCHLIST_HISTORY_PATH", jsonl_path), \
             patch.object(dp, "TICKER_STATE_PATH", parquet_path):

            # Setup: ticker is currently HELD
            dp.update_ticker_state("COMI", {
                "current_status": "HELD",
                "position_entry_price": 142.5,
                "position_shares": 176,
                "position_current_stop": 128.25,
                "total_closed_trades": 0,
                "lifetime_pnl_egp": 0.0,
            })

            stop_event = {
                "event_id": "test-stop-001",
                "pipeline_run_id": "run-004",
                "date": "2024-04-10",
                "timestamp": "2024-04-10T09:30:00+02:00",
                "ticker": "COMI",
                "action": "STOP_HIT",
                "pipeline_state": {
                    "market_regime": {"result": "OPEN", "reason": "ratio favorable"},
                    "hard_filter": {"result": "PASS", "reason": "still passing at exit"},
                    "category_tag": {"result": "market_leader", "reason": "mid-cap"},
                    "fundamentals": {"result": "PASS", "overall_reason": "still passing"},
                    "catalyst": {"result": "NEUTRAL", "reason": "no new catalyst"},
                    "entry_timing": {"result": "N/A", "reason": "position already held"},
                },
                "position": {
                    "entry_price": 142.5,
                    "entry_date": "2024-03-15",
                    "shares": 176,
                    "position_value_egp": 25080.0,
                    "stop_price": 128.25,
                    "initial_stop_distance_pct": 10.0,
                    "portfolio_equity_at_entry": 108450.0,
                    "position_size_pct_of_portfolio": 23.1,
                },
                "exit": {
                    "exit_price": 118.0,
                    "exit_date": "2024-04-10",
                    "exit_reason": "Stop-loss hit — price gapped down to 118.0 at open, below stop of 128.25",
                    "exit_description": "Stop-loss triggered on gap-down open",
                    "pnl_egp": -4312.0,
                    "pnl_pct": -17.19,
                    "holding_days": 26,
                    "portfolio_equity_at_exit": 104138.0,
                },
            }

            result = dp.write_event(stop_event)
            check("F4 action is STOP_HIT", "STOP_HIT", result["action"])
            check("F4 exit_price is 118.0", 118.0, result["exit"]["exit_price"])
            # Hand-calculation: (118.0 - 142.5) * 176 = -24.5 * 176 = -4312.0
            check("F4 pnl_egp is -4312.0", -4312.0, result["exit"]["pnl_egp"])
            check_approx("F4 pnl_pct is ~-17.19", -17.19, result["exit"]["pnl_pct"], tol=0.02)
            check("F4 exit_reason includes gap-down",
                  True, "gapped down" in result["exit"]["exit_reason"])

            dp.update_ticker_state("COMI", {
                "current_status": "REMOVED",
                "position_entry_price": None,
                "position_shares": None,
                "position_current_stop": None,
                "total_closed_trades": 1,
                "lifetime_pnl_egp": -4312.0,
                "last_updated": "2024-04-10",
            })
            state = dp.get_current_state("COMI")
            check("F4 ticker_state status is REMOVED", "REMOVED", state["current_status"])
            check("F4 total_closed_trades is 1", 1, state["total_closed_trades"])
            check("F4 lifetime_pnl_egp is -4312.0", -4312.0, state["lifetime_pnl_egp"])
            # [CORRECTED] parquet stores None as NaN for float columns — check with pd.isna
            import math
            check("F4 position_entry_price is None/NaN", True,
                  state["position_entry_price"] is None or (isinstance(state["position_entry_price"], float) and math.isnan(state["position_entry_price"])))

    # ====================================================================
    # Fixture 5 — REMOVED event
    # Prediction: removal reason is specific ("failed_hard_filter"),
    # ticker_state status=REMOVED, days_on_watchlist=45 (Mar 1 -> Apr 15).
    # ====================================================================
    print()
    print("=" * 70)
    print("Fixture 5 -- REMOVED event: ticker drops off watchlist")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as td:
        jsonl_path = Path(td) / "watchlist_history.jsonl"
        parquet_path = Path(td) / "ticker_state.parquet"

        with patch.object(dp, "WATCHLIST_HISTORY_PATH", jsonl_path), \
             patch.object(dp, "TICKER_STATE_PATH", parquet_path):

            dp.update_ticker_state("TMGH", {
                "current_status": "WATCHING",
                "stage_reached": "hard_filter",
                "days_on_watchlist": 0,
            })

            removed_event = {
                "event_id": "test-removed-001",
                "pipeline_run_id": "run-005",
                "date": "2024-04-15",
                "timestamp": "2024-04-15T09:30:00+02:00",
                "ticker": "TMGH",
                "action": "REMOVED",
                "pipeline_state": {
                    "market_regime": {"result": "OPEN", "reason": "ratio favorable"},
                    "hard_filter": {
                        "result": "FAIL",
                        "reason": "RS percentile dropped below threshold, TT conditions no longer met",
                    },
                    "category_tag": {"result": "SKIPPED", "reason": "blocked by hard_filter"},
                    "fundamentals": {"result": "SKIPPED", "overall_reason": "blocked"},
                    "catalyst": {"result": "SKIPPED", "reason": "blocked"},
                    "entry_timing": {"result": "SKIPPED", "reason": "blocked"},
                },
                "position": {
                    "entry_price": None, "entry_date": None, "shares": None,
                    "position_value_egp": None, "stop_price": None,
                    "initial_stop_distance_pct": None,
                    "portfolio_equity_at_entry": None,
                    "position_size_pct_of_portfolio": None,
                },
                "exit": {
                    "exit_price": None, "exit_date": None, "exit_reason": None,
                    "exit_description": None, "pnl_egp": None, "pnl_pct": None,
                    "holding_days": None, "portfolio_equity_at_exit": None,
                },
            }

            result = dp.write_event(removed_event)
            check("F5 action is REMOVED", "REMOVED", result["action"])
            check("F5 removal reason is specific (not generic)",
                  True, "RS percentile" in result["pipeline_state"]["hard_filter"]["reason"])

            dp.update_ticker_state("TMGH", {
                "current_status": "REMOVED",
                "days_on_watchlist": 45,
                "failure_reason": "RS percentile dropped below threshold",
                "last_updated": "2024-04-15",
            })
            state = dp.get_current_state("TMGH")
            check("F5 ticker_state status is REMOVED", "REMOVED", state["current_status"])
            check("F5 days_on_watchlist is 45", 45, state["days_on_watchlist"])

    # ====================================================================
    # Fixture 6 — Re-entry
    # Prediction: REMOVED event written first, then fresh ADDED event.
    # Both cycles visible in JSONL. ticker_state reflects NEW cycle.
    # ====================================================================
    print()
    print("=" * 70)
    print("Fixture 6 -- Re-entry: same ticker REMOVED then re-ADDED")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as td:
        jsonl_path = Path(td) / "watchlist_history.jsonl"
        parquet_path = Path(td) / "ticker_state.parquet"

        with patch.object(dp, "WATCHLIST_HISTORY_PATH", jsonl_path), \
             patch.object(dp, "TICKER_STATE_PATH", parquet_path):

            # Cycle 1: ADDED then REMOVED
            dp.write_event({
                "event_id": "reentry-added-1",
                "ticker": "SWDY", "action": "ADDED",
                "date": "2024-01-15",
                "pipeline_state": {"hard_filter": {"result": "PASS", "reason": "cycle 1"}},
            })
            dp.update_ticker_state("SWDY", {
                "current_status": "WATCHING", "last_updated": "2024-01-15",
            })

            dp.write_event({
                "event_id": "reentry-removed-1",
                "ticker": "SWDY", "action": "REMOVED",
                "date": "2024-02-20",
                "pipeline_state": {"hard_filter": {"result": "FAIL", "reason": "cycle 1 ended"}},
            })
            dp.update_ticker_state("SWDY", {
                "current_status": "REMOVED", "days_on_watchlist": 36,
                "last_updated": "2024-02-20",
            })

            # Cycle 2: re-ADDED
            dp.write_event({
                "event_id": "reentry-added-2",
                "ticker": "SWDY", "action": "ADDED",
                "date": "2024-05-01",
                "pipeline_state": {"hard_filter": {"result": "PASS", "reason": "cycle 2"}},
            })
            dp.update_ticker_state("SWDY", {
                "current_status": "WATCHING", "days_on_watchlist": 0,
                "last_updated": "2024-05-01",
            })

            # Verify JSONL shows all 3 events in order
            events = dp.query_watchlist_history({"ticker": "SWDY"})
            check("F6 total SWDY events is 3", 3, len(events))
            check("F6 event 1 is ADDED", "ADDED", events[0]["action"])
            check("F6 event 2 is REMOVED", "REMOVED", events[1]["action"])
            check("F6 event 3 is ADDED (re-entry)", "ADDED", events[2]["action"])
            check("F6 event 3 date is 2024-05-01", "2024-05-01", events[2]["date"])

            # Verify ticker_state reflects new cycle
            state = dp.get_current_state("SWDY")
            check("F6 ticker_state status is WATCHING (new cycle)", "WATCHING", state["current_status"])
            check("F6 days_on_watchlist reset to 0", 0, state["days_on_watchlist"])

            # Verify only 1 row in parquet
            import pandas as pd
            df = pd.read_parquet(parquet_path)
            swdy_rows = df[df["ticker"] == "SWDY"]
            check("F6 parquet has exactly 1 SWDY row", 1, len(swdy_rows))

    # ====================================================================
    # Fixture 7 — Append-only integrity
    # Prediction: 2 events => 2 JSONL lines (not overwritten).
    # ticker_state.parquet has 1 row (upserted, not duplicated).
    # ====================================================================
    print()
    print("=" * 70)
    print("Fixture 7 -- Append-only integrity: 2 events, 2 lines, 1 parquet row")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as td:
        jsonl_path = Path(td) / "watchlist_history.jsonl"
        parquet_path = Path(td) / "ticker_state.parquet"

        with patch.object(dp, "WATCHLIST_HISTORY_PATH", jsonl_path), \
             patch.object(dp, "TICKER_STATE_PATH", parquet_path):

            dp.write_event({
                "event_id": "integrity-1",
                "ticker": "EFIH", "action": "ADDED",
                "date": "2024-06-01",
                "pipeline_state": {"hard_filter": {"result": "PASS", "reason": "pass 1"}},
            })
            dp.update_ticker_state("EFIH", {
                "current_status": "WATCHING", "last_updated": "2024-06-01",
            })

            dp.write_event({
                "event_id": "integrity-2",
                "ticker": "EFIH", "action": "STAGE_FAILED",
                "date": "2024-06-05",
                "pipeline_state": {"hard_filter": {"result": "FAIL", "reason": "RS dropped"}},
            })
            dp.update_ticker_state("EFIH", {
                "current_status": "WATCHING",
                "failure_reason": "RS dropped",
                "last_updated": "2024-06-05",
            })

            # Verify JSONL: 2 lines, not 1
            with open(jsonl_path, encoding="utf-8") as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]
            check("F7 JSONL has 2 lines (append-only)", 2, len(lines))

            e1 = json.loads(lines[0])
            e2 = json.loads(lines[1])
            check("F7 line 1 action is ADDED", "ADDED", e1["action"])
            check("F7 line 2 action is STAGE_FAILED", "STAGE_FAILED", e2["action"])
            check("F7 event_ids are different", True, e1["event_id"] != e2["event_id"])

            # Verify parquet: 1 row
            import pandas as pd
            df = pd.read_parquet(parquet_path)
            efih_rows = df[df["ticker"] == "EFIH"]
            check("F7 parquet has exactly 1 EFIH row (upserted)", 1, len(efih_rows))
            check("F7 parquet last_updated is 2024-06-05",
                  "2024-06-05", efih_rows.iloc[0]["last_updated"])

    # ====================================================================
    # SUMMARY
    # ====================================================================
    print()
    print("=" * 70)
    if failures:
        print(f"RESULT: {len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
    else:
        print("RESULT: ALL CHECKS PASSED")
    print("=" * 70)
    return len(failures) == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
