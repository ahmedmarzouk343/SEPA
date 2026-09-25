"""Known answers for each Minervini SEPA v1 risk/sizing rule, one bar at a time."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kashif_engine.markets import US  # noqa: E402
from kashif_engine.strategies.minervini_sepa_v1.module import Strategy  # noqa: E402

CFG = json.loads((ROOT / "minervini_sepa_v1_strategy_config.json").read_text(encoding="utf-8"))


def strat(**p):
    return Strategy(CFG, p, US)


def bar(o, h, l, c, v=1e6, sma50=float("nan"), avgvol50=1e6):
    return NS(open=o, high=h, low=l, close=c, volume=v, sma50=sma50, avgvol50=avgvol50, atr14_pct=0.02)


def filled(s, entry=100.0, pivot=98.0, atr=0.02, defensive=False):
    s.defensive = defensive
    st = {"entry_price": entry, "candidate": {"pivot": pivot, "atr14_pct": atr, "pilot": False}}
    acts = s.on_entry_filled(None, "X", st, bar(entry, entry, entry, entry))
    st["stop_price"] = acts[0][1]
    st["bars_held"] = 0
    return st, acts


def test_stop_from_pivot_and_clamps():
    s = strat()
    st, acts = filled(s, entry=100.0, pivot=98.0)            # 98*0.97 = 95.06 -> 4.94%
    assert st["initial_stop_pct"] == pytest.approx(0.0494)
    assert acts == [("stop", pytest.approx(95.06), "STOP_LOSS")]
    st, _ = filled(strat(), entry=100.0, pivot=99.9)         # 3.1% -> floored at 4%
    assert st["initial_stop_pct"] == pytest.approx(0.04)
    st, _ = filled(strat(), entry=120.0, pivot=100.0)        # 19.2% -> capped at 10% hard max
    assert st["initial_stop_pct"] == pytest.approx(0.10)
    st, _ = filled(strat(stop_max_pct=0.07), entry=120.0, pivot=100.0)
    assert st["initial_stop_pct"] == pytest.approx(0.07)
    st, _ = filled(strat(), entry=120.0, pivot=100.0, defensive=True)   # defensive cap 6%
    assert st["initial_stop_pct"] == pytest.approx(0.06)


def test_stop_can_never_be_widened_past_ten_percent():
    with pytest.raises(ValueError):
        strat(stop_max_pct=0.12)


def test_breakeven_at_three_times_initial_risk():
    s = strat()
    st, _ = filled(s, entry=100.0, pivot=98.0)               # risk 4.94
    st["bars_held"] = 3
    assert s.manage(None, "X", st, bar(110, 114.8, 109, 114.8)) == []     # +14.8 < 14.82
    assert s.manage(None, "X", st, bar(114, 115, 113, 114.9)) == [("stop", 100.0, "BREAKEVEN_STOP")]
    assert st["breakeven_done"]


def test_trailing_stop_ratchets_on_new_closing_highs_only():
    s = strat()
    st, _ = filled(s, entry=100.0, pivot=98.0)
    st.update(breakeven_done=True, stop_price=100.0, highest_close=120.0, bars_held=20)
    # new closing high 130: max(130*0.85, sma50*0.95) = max(110.5, 104.5) = 110.5
    assert s.manage(None, "X", st, bar(125, 131, 124, 130, sma50=110.0)) == [("stop", pytest.approx(110.5), "TRAILING_STOP")]
    st["stop_price"] = 110.5
    assert s.manage(None, "X", st, bar(129, 129.5, 126, 127, sma50=111.0)) == []     # not a new high
    # sma50 floor wins when it is higher
    assert s.manage(None, "X", st, bar(130, 141, 129, 140, sma50=130.0)) == [("stop", pytest.approx(123.5), "TRAILING_STOP")]


def test_distribution_bar_needs_ten_bars_and_above_average_volume():
    s = strat()
    st, _ = filled(s, entry=100.0, pivot=98.0, atr=0.02)     # floor = 3%
    st["bars_held"] = 5
    # 5% open-to-close decline on heavy volume, but only 5 bars held -> no exit, floor rises to 5%
    assert s.manage(None, "X", st, bar(104, 104, 98.8, 98.8, v=3e6)) == []
    assert st["largest_decline"] == pytest.approx(0.05)
    st["bars_held"] = 12
    # 4% decline: not larger than 5% -> no exit
    assert s.manage(None, "X", st, bar(105, 105, 100.8, 100.8, v=3e6)) == []
    # 6% decline on LIGHT volume: new largest, but no exit
    assert s.manage(None, "X", st, bar(110, 110, 103.4, 103.4, v=0.5e6)) == []
    # 7% decline on heavy volume after 10 bars -> exit
    assert s.manage(None, "X", st, bar(110, 110, 102.3, 102.3, v=3e6)) == [("exit", "DISTRIBUTION_BAR")]


def test_defensive_profit_target():
    s = strat()
    st, _ = filled(s, entry=100.0, pivot=98.0, defensive=True)
    st["bars_held"] = 4
    assert st["profit_target"] == pytest.approx(111.0)
    assert s.manage(None, "X", st, bar(110, 111.5, 109, 111.2)) == [("exit", "DEFENSIVE_PROFIT_TARGET")]


def _closed(s, pnl, pilot=False, date="2023-01-01"):
    s.n_open += 1
    s.on_trade_closed({"net_pnl": pnl, "exit_date": date, "ticker": "X", "tag_pilot": pilot})


def test_losing_streak_steps_and_recovery():
    s = strat()
    s.n_open = 5                     # stay invested so the pilot flag is not re-armed
    s.reentry = False
    for _ in range(3):
        _closed(s, -100)
    assert s.size_multiplier() == pytest.approx(0.40)
    for _ in range(2):
        _closed(s, -100)
    assert s.size_multiplier() == pytest.approx(0.20)
    _closed(s, +300)                 # one winner steps up one level (FIX 18)
    assert s.size_multiplier() == pytest.approx(0.40)


def test_reentry_pilot_and_graduation():
    s = strat()
    assert s.reentry and s.size_multiplier() == 0.5          # starts in cash
    s.n_open = 3
    _closed(s, +100, pilot=True)
    assert s.reentry
    _closed(s, +100, pilot=True)
    assert not s.reentry and s.size_multiplier() == 1.0      # 2 pilot winners graduate
    s.n_open = 0                                              # _closed() opens then closes one position
    _closed(s, -50)                                           # book goes flat -> pilot again
    assert s.reentry


def test_defensive_mode_trigger_and_revert_with_min_trades():
    s = strat()
    s.n_open, s.reentry = 50, False
    for _ in range(9):
        _closed(s, -10)
    assert not s.defensive                                    # fewer than 10 trades: no verdict
    _closed(s, -10)
    assert s.defensive                                        # 0% win rate over 10
    for _ in range(20):
        _closed(s, +50)                                       # window refills with winners
    assert not s.defensive


def test_sizing_takes_minimum_not_product():
    s = strat()
    s.reentry, s.defensive, s.streak_idx = True, True, 1      # 0.5, 0.5, 0.40
    assert s.size_multiplier() == pytest.approx(0.40)


def test_allocate_respects_slots_liquidity_and_cash():
    s = strat(max_positions=6)
    s.reentry = False
    ctx = NS(n_open=4, equity=120_000.0, cash=50_000.0, pending_buy_value=0.0,
             addv={"A": 10e6, "B": 0.5e6, "C": 10e6})
    cands = [{"ticker": t} for t in ("A", "B", "C")]
    out = s.allocate(ctx, cands)
    assert [c["ticker"] for c, _ in out] == ["A", "B"]        # 2 free slots
    assert out[0][1] == pytest.approx(20_000.0)               # equity / 6
    assert out[1][1] == pytest.approx(10_000.0)               # 2% of 0.5M ADDV binds
    assert cands[2]["decision"] == "QUEUED_INSUFFICIENT_SLOTS"


# ---------------------------------------------------------------- experiment 2 switches
def test_defensive_off_never_engages():
    s = strat(defensive_mode="off")
    s.n_open, s.reentry = 50, False
    for _ in range(20):
        _closed(s, -10)
    assert not s.defensive and s.size_multiplier() < 1.0      # streak still steps down


def test_defensive_size_only_keeps_normal_stop_and_no_target():
    s = strat(defensive_mode="size_only")
    st, _ = filled(s, entry=120.0, pivot=100.0, defensive=True)
    assert st["initial_stop_pct"] == pytest.approx(0.10)       # not the 6% defensive cap
    assert st["profit_target"] is None                         # no 11% target
    s.reentry, s.streak_idx = False, 0
    assert s.size_multiplier() == pytest.approx(0.5)           # size still halved


def test_default_params_reproduce_v1_defensive_behaviour():
    st, _ = filled(strat(), entry=120.0, pivot=100.0, defensive=True)
    assert st["initial_stop_pct"] == pytest.approx(0.06) and st["profit_target"] == pytest.approx(133.2)


def test_stricter_regime_gate_blocks_candidates():
    import pandas as pd
    day = pd.Timestamp("2023-03-01")
    row = pd.DataFrame([{"ticker": "X", "pivot": 10.0, "vcp_quality": 1.0, "rs_pct": 90.0,
                         "volume_ratio": 2.0, "atr14_pct": 0.02}])
    for k, n_true, expect in ((1, 1, 1), (2, 1, 0), (2, 2, 1), (3, 2, 0), (3, 3, 1)):
        s = strat(regime_min_conditions=k)
        s.by_day = {day: row}
        s.regime_n = pd.Series({day: n_true})
        assert len(s.candidates(None, day.date())) == expect, (k, n_true)


def test_invalid_switch_values_rejected():
    with pytest.raises(ValueError):
        strat(defensive_mode="sometimes")
    with pytest.raises(ValueError):
        strat(regime_min_conditions=4)


def test_old_bundle_with_strict_gate_raises(tmp_path):
    import pickle
    import pandas as pd
    b = {"panel": {}, "vcp": pd.DataFrame({"ticker": [], "date": pd.to_datetime([]), "price_ready_min": []}),
         "needed": [], "days": pd.DatetimeIndex([]),
         "universe": [], "market": "US"}                       # no "regime_n": a pre-experiment-2 bundle
    path = tmp_path / "old.pkl"
    pickle.dump(b, open(path, "wb"))
    strat(regime_min_conditions=1).use_bundle(path)            # fine for the OR gate
    with pytest.raises(ValueError):
        strat(regime_min_conditions=2).use_bundle(path)


def test_stationary_bootstrap_known_answers():
    import numpy as np
    from kashif_engine.scripts.run_validation2 import stationary_bootstrap_p
    rng = np.random.default_rng(1)
    strong = rng.normal(0.002, 0.01, 1250)                      # ~3.2 annual Sharpe
    null = rng.normal(0.0, 0.01, 1250)
    assert stationary_bootstrap_p(strong, n=2000) < 0.01
    assert 0.05 < stationary_bootstrap_p(null, n=2000) < 0.95
