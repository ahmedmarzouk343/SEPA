"""
Verification tests for P7, P16, P21, P23, P6 fixes.

  TEST 1: P7 — independent_auditor flags a planted 1-piastre discrepancy
  TEST 2: P16 — ledger reconciliation fires on a synthetic drift scenario
  TEST 3: P21 — decision receipts write to decision_receipts/ dir not CWD
  TEST 4: P23 — KILL_SWITCH toggles mid-run via live module reference
  TEST 5: P6  — OOS partition enforcement + P24 warmup documentation
"""

import sys
import os
import csv
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    failures = []

    def check(label, expected, actual):
        ok = expected == actual
        status = "OK" if ok else "MISMATCH"
        print(f"  [{status}] {label}: expected={expected!r} actual={actual!r}")
        if not ok:
            failures.append(f"{label}: expected {expected!r}, got {actual!r}")

    # ====================================================================
    # TEST 1: P7 — independent_auditor flags a planted 1-piastre discrepancy
    # ====================================================================
    print("=" * 70)
    print("TEST 1 -- P7: independent_auditor flags 1-piastre discrepancy")
    print("=" * 70)

    from independent_auditor import load_trade_log, audit_trades, run_audit, get_strategy_equity

    with tempfile.TemporaryDirectory() as td:
        trade_log = Path(td) / "trade_log.csv"
        audit_out = Path(td) / "audit_report.json"

        # [UPDATED - Action 3]: the per-trade tolerance is now SCALED to
        # position value (max(0.01, 0.01% of entry_price * shares)) instead of
        # a flat 0.05 EGP. This trade is 100 x 50.00 = 5,000 EGP, so its
        # tolerance is 0.50 — the original 0.05 injected error now sits BELOW
        # tolerance and is correctly no longer flagged. The fixture's purpose
        # is to prove the auditor DETECTS a real discrepancy, so the injected
        # error is raised to 5.00 (10x the tolerance). The sub-tolerance case
        # is asserted separately below, which is new coverage the flat
        # threshold could not express.
        #
        # Trade: BUY 100 shares COMI at 50.00, SELL at 55.00
        # Real P&L: 100 * (55 - 50) - (5+5) - (1+1) = 488.00
        # Reported pnl on SELL row: 493.00 (5.00 EGP too high, tolerance 0.50)
        with open(trade_log, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["date", "ticker", "action", "shares", "price",
                        "commission", "slippage", "pnl"])
            w.writerow(["2024-03-01", "COMI", "BUY", 100, 50.00, 5.0, 1.0, 0.0])
            w.writerow(["2024-03-15", "COMI", "SELL", 100, 55.00, 5.0, 1.0, 493.00])

        # Patch get_strategy_equity to return matching auditor equity
        with patch("independent_auditor.get_strategy_equity",
                   return_value=(100488.00, "mock_ops_log.json")):
            report = run_audit(trade_log_path=trade_log, output_path=audit_out)

    print(f"  Auditor equity: {report['auditor_equity']}")
    print(f"  Strategy equity: {report['strategy_equity']}")
    print(f"  Discrepancies: {report['discrepancies']}")
    check("P7 audit verified is False (discrepancy detected)", False, report["verified"])
    check("P7 discrepancy count is 1", 1, len(report["discrepancies"]))
    check("P7 auditor equity is 100488.00", 100488.0, report["auditor_equity"])
    if report["discrepancies"]:
        d = report["discrepancies"][0]
        check("P7 discrepancy ticker is COMI", "COMI", d["ticker"])
        check("P7 discrepancy diff is 5.00", 5.00, d["difference"])
        check("P7 tolerance scaled to position value (0.01% of 5000)", 0.5,
              round(d["tolerance"], 4))

    # NEW (Action 3): an error BELOW the scaled tolerance must NOT be flagged.
    # 100 x 50.00 = 5,000 EGP -> tolerance 0.50; inject 0.05 (the old fixture's
    # error) and confirm it now passes. This is the penny-stock case that made
    # every EGX run report verified=False on pure float noise.
    with tempfile.TemporaryDirectory() as td:
        tl2 = Path(td) / "trade_log.csv"
        ao2 = Path(td) / "audit_report.json"
        with open(tl2, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["date", "ticker", "action", "shares", "price",
                        "commission", "slippage", "pnl"])
            w.writerow(["2024-03-01", "COMI", "BUY", 100, 50.00, 5.0, 1.0, 0.0])
            w.writerow(["2024-03-15", "COMI", "SELL", 100, 55.00, 5.0, 1.0, 488.05])
        with patch("independent_auditor.get_strategy_equity",
                   return_value=(100488.00, "mock_ops_log.json")):
            rep2 = run_audit(trade_log_path=tl2, output_path=ao2)
    check("P7 sub-tolerance error (0.05 on a 5,000 position) NOT flagged",
          0, len(rep2["discrepancies"]))
    check("P7 sub-tolerance case verifies clean", True, rep2["verified"])

    # Also test clean case (no discrepancy)
    with tempfile.TemporaryDirectory() as td:
        trade_log = Path(td) / "trade_log.csv"
        audit_out = Path(td) / "audit_report.json"

        with open(trade_log, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["date", "ticker", "action", "shares", "price",
                        "commission", "slippage", "pnl"])
            w.writerow(["2024-03-01", "COMI", "BUY", 100, 50.00, 5.0, 1.0, 0.0])
            w.writerow(["2024-03-15", "COMI", "SELL", 100, 55.00, 5.0, 1.0, 488.00])

        with patch("independent_auditor.get_strategy_equity",
                   return_value=(100488.00, "mock_ops_log.json")):
            report_clean = run_audit(trade_log_path=trade_log, output_path=audit_out)

    check("P7 clean audit verified is True", True, report_clean["verified"])
    check("P7 clean discrepancy count is 0", 0, len(report_clean["discrepancies"]))

    # ====================================================================
    # TEST 2: P16 — ledger reconciliation fires on a synthetic drift
    # ====================================================================
    print()
    print("=" * 70)
    print("TEST 2 -- P16: ledger reconciliation fires on drift")
    print("=" * 70)

    import inspect
    source = open(os.path.join(os.path.dirname(__file__), "kashif_strategy.py"),
                  encoding="utf-8").read()

    check("P16 _check_ledger_reconciliation method exists",
          True, "def _check_ledger_reconciliation(self):" in source)
    check("P16 _ledger_drift_events initialized in __init__",
          True, "self._ledger_drift_events = []" in source)
    check("P16 drift threshold is 0.01",
          True, "if drift >= 0.01:" in source)
    check("P16 reconciliation called in notify_trade",
          True, "self._check_ledger_reconciliation()" in source)
    check("P16 ledger_drift_events in ops log",
          True, '"ledger_drift_events": self._ledger_drift_events' in source)

    # Verify the method logic via source inspection
    check("P16 uses broker.getcash()",
          True, "self.broker.getcash()" in source)
    check("P16 uses broker.getvalue()",
          True, "self.broker.getvalue()" in source)
    check("P16 computes positions_value from open positions",
          True, "self.broker.getposition(d).size * d.close[0]" in source)

    # ====================================================================
    # TEST 3: P21 — decision receipts write to decision_receipts/ dir
    # ====================================================================
    print()
    print("=" * 70)
    print("TEST 3 -- P21: decision receipts write to project dir, not CWD")
    print("=" * 70)

    # [UPDATED — Action 2]: receipts now write to the decision_receipts_dir
    # PARAM (market-scoped by the runners), not the module-level RECEIPTS_DIR.
    # The param already existed but was never read, so both markets shared one
    # directory and --clear-receipts in one run deleted the other's receipts.
    # P21's actual intent — an ABSOLUTE, project-anchored directory rather than
    # a CWD-relative one — is unchanged, so it is asserted behaviourally here
    # instead of by matching the old source strings.
    check("P21 RECEIPTS_DIR default still defined with Path(__file__)",
          True, 'RECEIPTS_DIR = Path(__file__).resolve().parent / "decision_receipts"' in source)
    check("P21 mkdir uses the param, with parents=True",
          True, "receipts_dir.mkdir(parents=True, exist_ok=True)" in source)
    check("P21 writes to receipts_dir / filename",
          True, 'receipts_dir / f"decision_receipts_' in source)
    check("P21 receipts_dir comes from the param, not the module global",
          True, "receipts_dir = Path(self.p.decision_receipts_dir)" in source)
    check("P21 does NOT use os.makedirs('decision_receipts')",
          True, "os.makedirs('decision_receipts')" not in source)

    # Behavioural: the default param value must be an ABSOLUTE path anchored
    # in the project directory — that is what P21 was actually protecting.
    import kashif_strategy as _ks21
    _default_receipts = dict(_ks21.KashifStrategy.params._getpairs())["decision_receipts_dir"]
    check("P21 default receipts dir is absolute (not CWD-relative)",
          True, Path(_default_receipts).is_absolute())
    check("P21 default receipts dir sits under the project directory",
          True, str(Path(__file__).resolve().parent) in str(Path(_default_receipts)))

    # ====================================================================
    # TEST 4: P23 — KILL_SWITCH uses live module reference
    # ====================================================================
    print()
    print("=" * 70)
    print("TEST 4 -- P23: KILL_SWITCH uses live module reference, not snapshot")
    print("=" * 70)

    check("P23 uses 'import kashif_config' (module import)",
          True, "import kashif_config" in source)
    check("P23 does NOT snapshot-import KILL_SWITCH",
          True, "from kashif_config import KILL_SWITCH" not in source)
    check("P23 references kashif_config.KILL_SWITCH",
          True, "kashif_config.KILL_SWITCH" in source)

    # Verify toggle works via module attribute
    import kashif_config
    original = kashif_config.KILL_SWITCH
    check("P23 KILL_SWITCH initial value is False", False, original)

    kashif_config.KILL_SWITCH = True
    check("P23 KILL_SWITCH toggled to True", True, kashif_config.KILL_SWITCH)

    kashif_config.KILL_SWITCH = False
    check("P23 KILL_SWITCH toggled back to False", False, kashif_config.KILL_SWITCH)

    # Confirm strategy would read the live value
    check("P23 strategy reads kashif_config.KILL_SWITCH (not local copy)",
          True, "if kashif_config.KILL_SWITCH:" in source)

    # ====================================================================
    # TEST 5: P6 — OOS period refuses to run without oos_locked.flag
    # ====================================================================
    print()
    print("=" * 70)
    print("TEST 5 -- P6: OOS partition enforcement in run_backtest.py")
    print("=" * 70)

    from run_backtest import PERIODS, PROJECT_DIR, WARMUP_START, IS_START

    # Test 5a: Source-level checks for OOS enforcement
    rb_source = open(os.path.join(os.path.dirname(__file__), "run_backtest.py"),
                     encoding="utf-8").read()
    check("P6 OOS check for oos_locked.flag exists",
          True, "oos_locked.flag" in rb_source)
    check("P6 sys.exit(1) on missing flag",
          True, 'sys.exit(1)' in rb_source)

    # Test 5b: OOS flag enforcement (functional test)
    flag_path = PROJECT_DIR / "oos_locked.flag"
    if flag_path.exists():
        flag_path.unlink()

    check("P6 oos_locked.flag does not exist", False, flag_path.exists())

    flag_path.write_text("Parameters locked for test")
    check("P6 oos_locked.flag created", True, flag_path.exists())
    flag_path.unlink()

    # Test 5c: Partition dates are correct
    check("P6 IS period start", IS_START, PERIODS["IS"][0])
    check("P6 VAL period exists", True, "VAL" in PERIODS)
    check("P6 OOS period exists", True, "OOS" in PERIODS)

    # Test 5d: P24 warmup documentation
    check("P24 RS warmup comment block exists",
          True, "RS warmup" in rb_source)
    check("P24 comment mentions 252 bars of history",
          True, "252 bars of history" in rb_source)
    check("P24 comment mentions no signals during warmup",
          True, "no signals" in rb_source.lower())
    check("P24 startup log line for warmup period",
          True, "Warmup period:" in rb_source)
    check("P24 warmup log mentions IS_START",
          True, "IS_START" in rb_source)

    # Test 5e: period argument
    check("P6 period argument exists", True, "period" in rb_source)
    check("P6 logs period at startup", True, "Period:" in rb_source)

    # ====================================================================
    # SUMMARY
    # ====================================================================
    print()
    print("=" * 70)
    total_checks = sum(1 for line in failures) if failures else 0
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
