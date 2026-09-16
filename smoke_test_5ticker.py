"""
5-ticker smoke test — verifies Fixes 1-4 against live data.

  Fix 1  catalyst_check() returns a real score, no NoneType crash
  Fix 2  evaluate_fundamentals() is the ONLY fundamentals path (composite gone)
  Fix 3  regime gate reason names which condition actually fired
  Fix 4  return metrics are fractions everywhere
"""
import sys
import catalyst_check as cc
import fundamentals_screen as fs
from fundamentals_fetcher import fetch_fundamentals

TICKERS = ["AAPL", "MSFT", "GOOGL", "JPM", "XOM"]
failures = []


def check(label, ok, detail=""):
    print(f"  [{'OK' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


print("=" * 72)
print("FIX 1 — catalyst_check() returns a real score without erroring")
print("=" * 72)
for tk in TICKERS:
    try:
        r = cc.catalyst_check(tk, log_track_record=False)
        score = r.get("score")
        check(f"{tk} catalyst_check", score in ("NEUTRAL", "STRONG_NEGATIVE"),
              f"score={score} source={r.get('source')} tier={r.get('priority_tier')}")
    except Exception as e:
        check(f"{tk} catalyst_check", False, f"{type(e).__name__}: {e}")

print()
print("  Fix 1 root cause regression guard:")
from kashif_strategy import KashifStrategy
# The exact shape that used to crash: retry_log present but None.
try:
    KashifStrategy._update_catalyst_counters(
        type("S", (), {"_catalyst_api_calls_made": 0, "_catalyst_api_errors": 0,
                       "_catalyst_fallback_to_neutral": 0})(),
        {"model_call_attempted": False, "retry_log": None, "error_flag": False},
    )
    check("retry_log=None no longer raises", True)
except Exception as e:
    check("retry_log=None no longer raises", False, f"{type(e).__name__}: {e}")

print()
print("=" * 72)
print("FIX 2 — evaluate_fundamentals() is the only fundamentals path")
print("=" * 72)
check("compute_composite is GONE from fundamentals_screen",
      not hasattr(fs, "compute_composite"))
for dead in ("BASE_WEIGHTS", "PASS_THRESHOLD", "compute_peg_modifier",
             "compute_deceleration_penalty", "renormalize_weights",
             "score_earnings_growth", "score_code_33"):
    check(f"{dead} removed", not hasattr(fs, dead))

for tk in TICKERS:
    fd = fetch_fundamentals(tk, suffix="")
    if fd is None:
        check(f"{tk} fundamentals fetch", False, "no data")
        continue
    res = fs.evaluate_fundamentals(fd)
    has_all_q = all(k in res for k in ("q1", "q2", "q3", "q4"))
    no_composite = "composite" not in res
    check(f"{tk} 4-question result only", has_all_q and no_composite,
          f"pass={res['pass']} | {res['overall_reason']}")
    print(f"          eps_q={fd.get('eps_yoy_growth_by_quarter')}")
    print(f"          annual={fd.get('annual_eps_by_year')}")

print()
print("=" * 72)
print("FIX 3 — regime reason names the condition that fired")
print("=" * 72)


class _FakeStrat:
    _build_regime_reason = KashifStrategy._build_regime_reason


def regime_reason(ratio, pullback, divergence):
    s = _FakeStrat()
    s.regime_open = ratio or pullback or divergence
    s.regime_diag = {
        "new_high_low_ratio_favorable": ratio,
        "leader_pullback_shallow": pullback,
        "leader_divergence": divergence,
        "_pullback": {"avg_pullback_depth": 0.032, "avg_days_since_local_high": 6, "n_leaders": 51},
        "_divergence": {"leader_pct_higher_low": 0.49, "universe_pct_higher_low": 0.35},
    }
    return s._build_regime_reason()["reason"]


r_pullback_only = regime_reason(False, True, False)
print(f"  pullback-only OPEN:\n    {r_pullback_only}")
check("names pullback_shallow as fired", "pullback_shallow fired" in r_pullback_only)
check("does NOT claim all three confirmed",
      "all three regime conditions confirmed" not in r_pullback_only)
check("lists the non-firing conditions", "NOT fired" in r_pullback_only)

r_all = regime_reason(True, True, True)
print(f"  all-three OPEN:\n    {r_all}")
check("all-three names all three as fired",
      all(c in r_all for c in ("new_high_low_ratio", "pullback_shallow", "leader_divergence")))
check("all-three has no 'NOT fired' clause", "NOT fired" not in r_all)

print()
print("=" * 72)
print("FIX 4 — return metrics are fractions everywhere")
print("=" * 72)
import inspect
src = inspect.getsource(KashifStrategy.notify_trade)
check("no x100 on stock_return_pct in the event writer",
      "round(stock_return_pct * 100" not in src)
check("no x100 on spy_return_pct in the event writer",
      "round(spy_return_pct * 100" not in src)
check("no x100 on alpha_pct in the event writer",
      "round(alpha_pct * 100" not in src)
check("no x100 on max_gain_pct in the event writer",
      "round(max_gain_pct * 100" not in src)

from independent_auditor import validate_metric_units
bad = validate_metric_units([{
    "ticker": "T", "date": "2025-01-01",
    "stock_return_pct": -8.35, "spy_return_pct": None,
    "max_unrealized_gain_pct": None, "max_drawdown_during_hold_pct": None,
    "alpha_vs_spy_pct": None,
}])
check("auditor flags a percentage-scaled value", len(bad) == 1,
      bad[0]["issue"] if bad else "")
good = validate_metric_units([{
    "ticker": "T", "date": "2025-01-01",
    "stock_return_pct": -0.0835, "spy_return_pct": 0.0021,
    "max_unrealized_gain_pct": 0.29, "max_drawdown_during_hold_pct": -0.05,
    "alpha_vs_spy_pct": -0.0856,
}])
check("auditor accepts fraction-scaled values", len(good) == 0)

print()
print("=" * 72)
if failures:
    print(f"SMOKE TEST FAILED — {len(failures)} check(s):")
    for f in failures:
        print(f"  - {f}")
else:
    print("SMOKE TEST PASSED — Fixes 1-4 confirmed on live data")
print("=" * 72)
sys.exit(len(failures))
