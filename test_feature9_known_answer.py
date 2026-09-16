"""
test_feature9_known_answer.py — Feature 9 (Exit Strategy) known-answer fixtures.

Six fixtures from feature-09-exit-strategy-rules.md Section 8, testing:
  1. Distribution bar fires on largest decline + heavy volume
  2. No sell on large decline without volume confirmation  (CRITICAL)
  3. Stage 3 transition fires (close < SMA200 on heavy volume)
  4. Trailing stop raises after new high and eventually fires
  5. ENTERED event timing — emitted on confirmed fill, not on order submit
  6. Exit metrics populated on trade close (with SPY alpha)

---------------------------------------------------------------------------
CONSTRUCTION NOTE: Trailing-stop bug fix discovered during test design
---------------------------------------------------------------------------
_track_position_metrics() ran BEFORE _update_trailing_stop() in
_manage_open_position(), updating highest_close_since_entry to the current
close. Then _update_trailing_stop checked `close > highest`, which could
NEVER be True since highest was already >= close. Fix: _manage_open_position
now captures `prev_highest` before _track_position_metrics runs and passes
it to _update_trailing_stop, which compares `close > prev_highest`.

---------------------------------------------------------------------------
CONSTRUCTION NOTE: History buffer population
---------------------------------------------------------------------------
The test strategy overrides next() (like ExplicitEntryStrategy in
test_feature4) for deterministic entry control. Since KashifStrategy.next()
is not called, the strategy's self.history[d] deque doesn't get populated
automatically. For fixtures that depend on history (stage 3 SMA200, trailing
stop SMA50), the test strategy appends to history explicitly.

---------------------------------------------------------------------------
CONSTRUCTION NOTE: _avg_volume and the current bar
---------------------------------------------------------------------------
d.volume.get(size=50) returns the last 50 values INCLUDING the current bar.
So a distribution-bar test bar with volume=180000 contributes to its own
50-day average: avg = (49*100000 + 180000)/50 = 101600, not 100000.
All predictions below account for this.

---------------------------------------------------------------------------
CONSTRUCTION NOTE: Market-order fill timing (same as test_feature4)
---------------------------------------------------------------------------
A Market order placed in next() at bar N fills at bar N+1's open.
A Stop order at price P fills during bar processing if bar's low <= P
(or at bar's open if open < P). Stop fills happen BEFORE next() runs.

---------------------------------------------------------------------------
CONSTRUCTION NOTE: Position sizing (v0.27 parameters)
---------------------------------------------------------------------------
cash=100000, target_position_count=6, no pilot/defensive adjustments
on first entry. slot = 100000/6 = 16666.67. At entry price 100:
shares = floor(16666.67 / 100) = 166.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pytest  # noqa: E402
import pandas as pd  # noqa: E402
import backtrader as bt  # noqa: E402
from kashif_sizer import MinerviniSizer  # noqa: E402
from kashif_strategy import KashifStrategy  # noqa: E402
import kashif_strategy as _ks  # noqa: E402

TOL = 1e-6

WARMUP_55 = [{"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000} for _ in range(55)]
WARMUP_200 = [{"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000} for _ in range(200)]


def approx(a, b, tol=TOL):
    return abs(a - b) < tol


def make_data(bars, name="TEST"):
    dates = pd.date_range("2024-01-01", periods=len(bars), freq="D")
    df = pd.DataFrame(bars, index=dates)
    return bt.feeds.PandasData(dataname=df, name=name)


def run_cerebro(bars, strat_cls, cash=100000, name="TEST", **kwargs):
    cerebro = bt.Cerebro()
    cerebro.adddata(make_data(bars, name=name))
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=0.0)
    cerebro.broker.set_coc(False)
    cerebro.addstrategy(strat_cls, **kwargs)
    cerebro.addsizer(MinerviniSizer)
    results = cerebro.run()
    return results[0]


def run_cerebro_with_spy(bars, spy_bars, strat_cls, cash=100000, **kwargs):
    cerebro = bt.Cerebro()
    cerebro.adddata(make_data(bars, name="TEST"))
    cerebro.adddata(make_data(spy_bars, name="SPY"))
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=0.0)
    cerebro.broker.set_coc(False)
    cerebro.addstrategy(strat_cls, **kwargs)
    cerebro.addsizer(MinerviniSizer)
    results = cerebro.run()
    return results[0]


class F9Strategy(KashifStrategy):
    """Test harness: deterministic entry on specified bars, captures events."""
    params = (("entry_trigger_bars", ()),)

    def __init__(self):
        super().__init__()
        self.trade_log = []
        self.fill_log = []
        self.captured_events = []

    def _emit_watchlist_event(self, action, d, **kwargs):
        self.captured_events.append({
            "bar": len(self),
            "action": action,
            "position": kwargs.get("position"),
        })

    def next(self):
        bar = len(self)
        for d in self.datas:
            self.history[d].append({
                "Date": d.datetime.date(0),
                "Open": d.open[0], "High": d.high[0], "Low": d.low[0],
                "Close": d.close[0], "Volume": d.volume[0],
            })
        pos = self.broker.getposition(self.data)
        if pos.size == 0 and bar in self.p.entry_trigger_bars:
            size = self.getsizing(self.data, isbuy=True)
            if size > 0:
                self.buy(data=self.data, size=size, exectype=bt.Order.Market)
        if pos.size > 0:
            self._manage_open_position(self.data)

    def notify_order(self, order):
        super().notify_order(order)
        if order.status == order.Completed:
            self.fill_log.append({
                "bar": len(self),
                "isbuy": order.isbuy(),
                "price": order.executed.price,
                "size": abs(order.executed.size),
            })

    def notify_trade(self, trade):
        super().notify_trade(trade)
        if trade.isclosed:
            self.trade_log.append({
                "bar": len(self),
                "pnl": trade.pnl,
            })

    prenext = next


# ======================================================================
# FIXTURE 1 -- Distribution bar fires correctly
# ======================================================================
# Enter at 100 (bar 56 trigger -> bar 57 fill at open=100).
# Price jumps to 150 on fill bar, stays flat for 29 bars.
# Bar 87: 8% intraday decline (open=150, close=138) on heavy volume
# (180000 vs ~100000 avg).  Sell Market placed. Fills bar 88 open=138.
#
# Predicted:
#   exit_reason = "DISTRIBUTION_BAR"
#   fill price = 138.0  (bar 88 open)
#   PnL = (138 - 100) * 166 = 6308.0

def test_fixture1_distribution_bar():
    bars_f1 = list(WARMUP_55) + [
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 150, "low": 100, "close": 150, "volume": 100000},
    ] + [
        {"open": 150, "high": 151, "low": 149, "close": 150, "volume": 100000}
        for _ in range(29)
    ] + [
        {"open": 150, "high": 150, "low": 137, "close": 138, "volume": 180000},
        {"open": 138, "high": 139, "low": 137, "close": 138, "volume": 100000},
    ]

    strat1 = run_cerebro(bars_f1, F9Strategy, entry_trigger_bars=(56,))

    assert len(strat1.trade_log) == 1
    assert strat1.position_exit_metrics[strat1.data]["exit_reason"] == "DISTRIBUTION_BAR"
    assert abs(strat1.fill_log[1]["price"] - 138.0) < TOL
    assert abs(strat1.trade_log[0]["pnl"] - 6308.0) < TOL


# ======================================================================
# FIXTURE 2 -- No sell on large decline WITHOUT volume (CRITICAL)
# ======================================================================
# Same bars as F1 except distribution bar volume = 60000 (0.6x avg).
# avg_vol = (49*100000 + 60000)/50 = 99200.  60000 < 99200 -> no sell.
# Largest-decline tracker updates to 0.08, but position stays open.
#
# Predicted:
#   No trades closed.
#   Position still held at end.
#   largest_decline_since_entry updated to 0.08.

def test_fixture2_no_sell_without_volume():
    bars_f2 = list(WARMUP_55) + [
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 150, "low": 100, "close": 150, "volume": 100000},
    ] + [
        {"open": 150, "high": 151, "low": 149, "close": 150, "volume": 100000}
        for _ in range(29)
    ] + [
        {"open": 150, "high": 150, "low": 137, "close": 138, "volume": 60000},
        {"open": 138, "high": 139, "low": 137, "close": 138, "volume": 100000},
    ]

    strat2 = run_cerebro(bars_f2, F9Strategy, entry_trigger_bars=(56,))

    assert len(strat2.trade_log) == 0
    pos2 = strat2.broker.getposition(strat2.data)
    assert pos2.size > 0
    expected_decline = (150 - 138) / 150  # 0.08
    assert abs(strat2.largest_decline_since_entry.get(strat2.data, 0) - expected_decline) < TOL


# ======================================================================
# FIXTURE 3a -- Stage 3 transition DISABLED by default, no exit
# ======================================================================
# 200-bar warmup (close=100) so history has >= 200 entries.
# Bar 201 trigger -> bar 202 fill at open=100.
# Bar 203: open=97, close=98 -- UP bar intraday, but close=98 is below
#   SMA200 ~ 99.99, and volume=150000 (1.5x).
# With STAGE3_TRANSITION_EXIT_ENABLED defaulting to False, no exit fires.

def test_fixture3a_stage3_disabled():
    bars_f3 = list(WARMUP_200) + [
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 97, "high": 99, "low": 96, "close": 98, "volume": 150000},
        {"open": 98, "high": 99, "low": 97, "close": 98, "volume": 100000},
    ]

    assert _ks.STAGE3_TRANSITION_EXIT_ENABLED is False
    strat3a = run_cerebro(bars_f3, F9Strategy, entry_trigger_bars=(201,))
    assert len(strat3a.trade_log) == 0
    assert strat3a.broker.getposition(strat3a.data).size > 0


# ======================================================================
# FIXTURE 3b -- Stage 3 fires when flag re-enabled (heavy volume)
# ======================================================================
# Same bars as 3a. Bar 203: open=97, close=98 -- an intraday UP bar, so the
# distribution-bar check returns False (negative decline) and cannot
# pre-empt stage 3. close=98 is below SMA200 ~ 99.99 on volume 150000.
# avg_vol = (49*100000 + 150000)/50 = 101000.  150000 > 101000 -> sell.
# Sell fills bar 204 open=98.  PnL = (98 - 100) * 166 = -332.0

def test_fixture3b_stage3_enabled():
    bars_f3 = list(WARMUP_200) + [
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 97, "high": 99, "low": 96, "close": 98, "volume": 150000},
        {"open": 98, "high": 99, "low": 97, "close": 98, "volume": 100000},
    ]

    _ks.STAGE3_TRANSITION_EXIT_ENABLED = True
    try:
        strat3b = run_cerebro(bars_f3, F9Strategy, entry_trigger_bars=(201,))
        assert len(strat3b.trade_log) == 1
        assert strat3b.position_exit_metrics[strat3b.data]["exit_reason"] == "STAGE3_TRANSITION"
        assert abs(strat3b.trade_log[0]["pnl"] - (-332.0)) < TOL
    finally:
        _ks.STAGE3_TRANSITION_EXIT_ENABLED = False


# ======================================================================
# FIXTURE 3c -- Stage 3 enabled but light volume, still no exit
# ======================================================================
# avg_vol = (49*100000 + 40000)/50 = 98800.  40000 < 98800 -> no sell.

def test_fixture3c_stage3_light_volume():
    bars_f3c = list(WARMUP_200) + [
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 97, "high": 99, "low": 96, "close": 98, "volume": 40000},
        {"open": 98, "high": 99, "low": 97, "close": 98, "volume": 100000},
    ]

    _ks.STAGE3_TRANSITION_EXIT_ENABLED = True
    try:
        strat3c = run_cerebro(bars_f3c, F9Strategy, entry_trigger_bars=(201,))
        assert len(strat3c.trade_log) == 0
        assert strat3c.broker.getposition(strat3c.data).size > 0
    finally:
        _ks.STAGE3_TRANSITION_EXIT_ENABLED = False


# ======================================================================
# FIXTURE 4 -- Trailing stop raises after new high, then fires
# ======================================================================
# Enter at 100 (bar 56->57 fill).  Bar 58: close=130, breakeven fires
# (gain 30 = 3x10).  Stop moves to 100, breakeven_done=True.
# Bar 59: close=180 (new high, prev=130). sma_50 = (48*100+130+180)/50
#   = 102.2 -> new_stop = 99.13 < 100 -> no update yet.
# Bars 60-108: close=180 (not new highs, no trailing-stop check).
# Bar 109: close=181 (new high, prev=180).
#   sma_50 = (49*180 + 181)/50 = 180.02
#   new_stop = 180.02 * 0.97 = 174.6194  > 100 -> trailing stop set!
# Bar 110: open=182, low=170 -> stop at 174.6194 fires.
#   open > stop, low < stop -> fill at 174.6194.
#
# [UPDATED -- Fix 16/C10]: TRAILING_STOP_BUFFER_PCT 0.03 -> 0.05, so the
# trailing floor is sma_50 * 0.95, not * 0.97.
#
# Predicted:
#   exit_reason = "TRAILING_STOP"
#   PnL = (sma50 * 0.95 - 100) * 166

def test_fixture4_trailing_stop():
    bars_f4 = list(WARMUP_55) + [
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 131, "low": 99, "close": 130, "volume": 100000},
        {"open": 130, "high": 181, "low": 130, "close": 180, "volume": 100000},
    ] + [
        {"open": 180, "high": 181, "low": 179, "close": 180, "volume": 100000}
        for _ in range(49)
    ] + [
        {"open": 180, "high": 182, "low": 180, "close": 181, "volume": 100000},
        {"open": 182, "high": 183, "low": 170, "close": 172, "volume": 100000},
    ]

    strat4 = run_cerebro(bars_f4, F9Strategy, entry_trigger_bars=(56,))

    expected_sma50 = (49 * 180 + 181) / 50  # 180.02
    expected_trailing_stop = expected_sma50 * 0.95  # 171.019
    expected_pnl_f4 = (expected_trailing_stop - 100) * 166  # 11789.154

    assert len(strat4.trade_log) == 1
    assert strat4.position_exit_metrics[strat4.data]["exit_reason"] == "TRAILING_STOP"
    assert abs(strat4.trade_log[0]["pnl"] - expected_pnl_f4) < 0.02
    assert strat4.trade_log[0]["pnl"] > 0


# ======================================================================
# FIXTURE 5 -- ENTERED event timing
# ======================================================================
# Bar 56: trigger, buy Market placed. NO ENTERED event yet.
# Bar 57: fill at open=105. ENTERED event emitted in notify_order
#   with actual fill price 105, not signal-bar close 100.

def test_fixture5_entered_event():
    bars_f5 = list(WARMUP_55) + [
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 105, "high": 111, "low": 104, "close": 110, "volume": 100000},
        {"open": 110, "high": 111, "low": 109, "close": 110, "volume": 100000},
    ]

    strat5 = run_cerebro(bars_f5, F9Strategy, entry_trigger_bars=(56,))

    entered_events = [e for e in strat5.captured_events if e["action"] == "ENTERED"]
    pre_fill = [e for e in entered_events if e["bar"] <= 56]
    post_fill = [e for e in entered_events if e["bar"] == 57]

    assert len(pre_fill) == 0
    assert len(post_fill) == 1
    assert abs(post_fill[0]["position"]["entry_price"] - 105.0) < TOL


# ======================================================================
# FIXTURE 6 -- Exit metrics populated (with SPY alpha)
# ======================================================================
# Enter at 100 (bar 57 fill). Price peaks at 129 (bar 58, no breakeven
# since 29 < 30).  Bar 59: stop at 90 fires (open=129, low=85).
# SPY at entry (bar 57): 400.  SPY at exit (bar 59): 380.
#
# [UPDATED - Fix B + same-bar-cancel bug fix]:
#   no receipt -> NO_PIVOT_STOP_DISTANCE = 7% -> stop at 93, not 90,
#   and initial_stop_distance = 7.0 (was 10.0).
#   breakeven trigger = 100 + 4 * 7 = 128. Bar 58 closes 129 >= 128, so
#   breakeven NOW FIRES and moves the stop to entry = 100.
#   Bar 59 opens 129 with low 85 -> the 100 stop fills at exactly 100.
#   pnl = (100 - 100) * 166 = 0.0, exit_reason = BREAKEVEN_STOP.
#
# Predicted:
#   holding_days = 2
#   exit_reason = "BREAKEVEN_STOP"
#   max_unrealized_gain_pct = 0.29
#   max_drawdown_during_hold_pct = 0.0
#   stock_return_pct = 0.0     [UPDATED - FIX 2]
#   spy_return_pct = -0.05
#   alpha_vs_spy_pct = +0.05    [UPDATED - FIX 2]
#
# FIX 2: exit_price is now the ACTUAL FILL PRICE, not the bar close.
# The breakeven stop fills at exactly 100 (entry), while bar 59's CLOSE is
# 87. The old code reported stock_return_pct = (87-100)/100 = -0.13 for a
# trade whose realised pnl was 0.0 — the metric contradicted the P&L on the
# same row. With the fill price the two agree: (100-100)/100 = 0.0, and
# alpha = 0.0 - (-0.05) = +0.05. This fixture is the regression guard for
# that bug.
#   trade.pnl = 0.0

def test_fixture6_exit_metrics():
    bars_f6 = list(WARMUP_55) + [
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 130, "low": 99, "close": 129, "volume": 100000},
        {"open": 129, "high": 130, "low": 85, "close": 87, "volume": 100000},
    ]
    spy_f6 = [{"open": 400, "high": 401, "low": 399, "close": 400, "volume": 500000}
              for _ in range(len(bars_f6))]
    spy_f6[-1] = {"open": 390, "high": 391, "low": 379, "close": 380, "volume": 500000}

    strat6 = run_cerebro_with_spy(bars_f6, spy_f6, F9Strategy, entry_trigger_bars=(56,))

    assert len(strat6.trade_log) == 1
    assert len(strat6.fill_log) == 2
    assert abs(strat6.trade_log[0]["pnl"] - 0.0) < TOL

    m = strat6.position_exit_metrics.get(strat6.data, {})
    assert len(m) > 0
    assert m.get("exit_reason") == "BREAKEVEN_STOP"
    assert m.get("holding_days") == 2
    assert abs(m.get("max_unrealized_gain_pct", 0) - 0.29) < TOL
    assert abs(m.get("max_drawdown_during_hold_pct", 0) - 0.0) < TOL
    assert abs(m.get("stock_return_pct", 0) - 0.0) < TOL
    assert abs(m.get("spy_return_pct", 0) - (-0.05)) < TOL
    assert abs(m.get("alpha_vs_spy_pct", 0) - 0.05) < TOL
    # FIX 2 invariant: the reported return must agree with the realised pnl.
    assert abs(m.get("stock_return_pct", 0) - (strat6.trade_log[0]["pnl"] / (100 * 166))) < 1e-9


# ======================================================================
# FIXTURE 7 -- peak-referenced trailing floor (the TSLA/PANW case)
# ======================================================================
# Enter at 100 (bar 56 trigger -> bar 57 fill at open=100), then spike:
#   bar 58  close=130  breakeven fires (gain 30 >= 3 x 10), stop -> 100.
#           Trailing then runs in the same call:
#             peak floor = 130 * 0.85          = 110.50
#             sma_50     = (49*100 + 130)/50   = 100.60 -> * 0.95 = 95.57
#           max = 110.50 -> PEAK FLOOR WINS, stop lifts 100 -> 110.50.
#   bar 59  close=140  new high:
#             peak floor = 140 * 0.85          = 119.00
#             sma_50     = (48*100+130+140)/50 = 101.40 -> * 0.95 = 96.33
#           max = 119.00 -> stop lifts to 119.00.
#   bar 60  decay: open=138, low=115 -> the 119.00 stop fills at 119.00.
#
# Predicted: exit_reason = TRAILING_STOP, fill 119.0,
#            PnL = (119 - 100) * 166 = 3154.0

def test_fixture7_peak_floor_trailing():
    bars_f7 = list(WARMUP_55) + [
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 131, "low": 99, "close": 130, "volume": 100000},
        {"open": 130, "high": 141, "low": 129, "close": 140, "volume": 100000},
        {"open": 138, "high": 139, "low": 115, "close": 118, "volume": 100000},
    ]

    strat7 = run_cerebro(bars_f7, F9Strategy, entry_trigger_bars=(56,))

    assert len(strat7.trade_log) == 1
    assert strat7.position_exit_metrics[strat7.data]["exit_reason"] == "TRAILING_STOP"
    assert abs(strat7.fill_log[1]["price"] - 119.0) < TOL
    assert abs(strat7.trade_log[0]["pnl"] - 3154.0) < TOL
    assert strat7.trade_log[0]["pnl"] > 0
