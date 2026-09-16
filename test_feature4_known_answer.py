"""
Known-answer regression test for Feature 4 (Risk Rules & Position Sizing):
kashif_strategy.py (KashifStrategy) and kashif_sizer.py (MinerviniSizer),
covering all 10 required fixtures from feature-04-risk-position-sizing-rules.md
Section 4 plus 5 supplementary fixtures (11, 12, 13, 14, 15), same pattern as
Features 2 and 3.

Imports and drives the REAL project classes through a real bt.Cerebro --
not re-typed copies of their formulas. Same discipline as every prior
feature: predictions hand-derived/independently scratch-verified BEFORE
being written into this docstring, no circular verification, wrong
predictions left visible with a [CORRECTED -- ...] note rather than
silently fixed.

Zero commission/slippage in every fixture (cerebro.broker.setcommission(
commission=0.0), set_coc(False)) -- noted here so this is never "fixed" to
realistic values later and silently breaks every exact-price prediction.

--------------------------------------------------------------------------
TWO REAL BUGS FOUND AND FIXED IN kashif_strategy.py WHILE BUILDING THIS
FILE (not caught by code review -- caught by trying to make Fixture 4's
losing-streak sequence actually progress through its step-downs)
--------------------------------------------------------------------------
1. [CORRECTED -- logic error] Corporate Action Guard's overnight-gap
   detection compared TODAY'S CLOSE against YESTERDAY'S CLOSE
   (`d.close[0] / d.close[-1] - 1`) in both _manage_open_position() and
   notify_trade(). Considerations.md Section 4's own example ("opens at
   -15% when the stop is -10%") and the spec's "overnight gap" language
   both describe the OPEN vs the PRIOR close, not close-to-close. The
   original version misclassified an ordinary large gap-down stop-out
   (e.g. the ~15-30% overnight gaps that legitimately blow through a 10%
   hard stop in a thin EGX name) as a suspected corporate action purely
   because that day's move was wide -- which silently excluded every such
   stop-out from consecutive_stops/streak tracking, so the losing-streak
   step-down logic never engaged during initial fixture construction.
   Fixed to `d.open[0] / d.close[-1] - 1` in both places.

2. [CORRECTED -- logic error] notify_order()'s "was this our tracked stop
   order?" check compared Order objects with Python `is` identity
   (`self.stop_order.get(d) is order`). Confirmed empirically (standalone
   probe) that backtrader passes a DIFFERENT Order object into every
   notify_order() callback than the one self.buy()/self.sell() originally
   returned -- id() differs on every single status transition, including
   the very first Submitted callback for a brand-new order. `order.ref`
   (a stable integer id backtrader maintains across an order's lifecycle)
   is the correct comparison. The `is` version was silently always False,
   so no stop-out was ever recognized as "our stop": consecutive_stops
   never incremented and the streak/defensive/reentry bookkeeping in
   notify_trade() never ran on a real stop-loss exit. Fixed to compare
   `.ref` instead of object identity.

Both are real defects in the delivered code, not test-harness artifacts --
documented here, in kashif_strategy.py's inline comments at the fix sites,
and reported to the user, per this project's "leave it visible, explain
root cause" standard (same discipline as Feature 3's argmax tie-breaking
fix).

--------------------------------------------------------------------------
CONSTRUCTION NOTE: 50-bar Liquidity Lock warm-up
--------------------------------------------------------------------------
MinerviniSizer._getsizing() fails closed (returns 0 shares) until 50 bars
of volume history exist for the ADDV calculation (kashif_sizer.py design
decision #4). Every fixture below that calls real getsizing()/buy() prepends
a 55-bar flat warm-up block (WARMUP, close=100/volume=100000) so entries can
actually size non-zero -- discovered during construction (the very first
draft of Fixture 4 sized every entry to 0 shares before this was added).

--------------------------------------------------------------------------
CONSTRUCTION NOTE: Market order fill timing
--------------------------------------------------------------------------
backtrader Market orders submitted during bar N's next() fill at bar N+1's
OPEN, not bar N's close. Group A fixtures below deliberately separate each
"signal" bar from its "fill" bar (and same for close signals) to keep
predicted fill prices exact and unambiguous -- confirmed empirically via
fill_log capture during construction, not assumed.

--------------------------------------------------------------------------
WRITTEN PREDICTIONS -- hand-derived / independently scratch-verified BEFORE
being written here (same "verify once via the real formulas as a scratch
calc, then have this file re-invoke the real code and confirm reproducible"
practice already used for Feature 3's plateau fixture; every number below
was captured from an actual cerebro.run() against the REAL, already-fixed
kashif_strategy.py/kashif_sizer.py before being transcribed here, not
independently hand-arithmetic'd from scratch for the multi-trade sequences
-- those are far too path-dependent on bar-by-bar order-fill timing to
safely hand-derive blind).
--------------------------------------------------------------------------

FIXTURE 1 -- stop-loss enforcement, 2 sub-cases (Group A).
  [v0.27: target_position_count 4->6, shares = floor(100000/6/100) = 166]
  Entry 100, 10% hard stop placed at 90 on fill.
  1a "non-gapped touch": next bar opens at 95 (still above 90) but low=85
     crosses through 90 intrabar. PREDICTED fill price = exactly 90.0 (a
     touch fills AT the stop price, not the open or the low) -- confirmed
     via standalone probe before this file existed. pnl = (90-100)*166
     = -1660.0. consecutive_stops becomes 1.
  1b "gapped-open": next bar opens at 82 (an 18% overnight gap -- past the
     90 stop, so it gaps through, but deliberately UNDER the 20% Corporate
     Action Guard threshold so it must NOT be flagged/excluded).
     PREDICTED fill price = the OPEN price, 82.0 (gap-through), not 90.0.
     pnl = (82-100)*166 = -2988.0. consecutive_stops becomes 1.
     flagged_for_review must stay empty (18% < 20%).

FIXTURE 2 -- breakeven stop swap (Group A).
  Entry 100, initial_stop_distance=10, stop placed at 90. Rally to
  close=130: unrealized_gain=30 >= 3*10=30 (exactly at the breakeven
  trigger) -> old stop (90) cancelled, new stop placed at entry (100).
  Price then holds at 130 for a bar (old stop @90 would not have fired
  here either way -- not a distinguishing bar on its own), then declines
  through 100 (non-gapped touch: open=105>100, low=95<100).
  PREDICTED: the NEW stop fires at exactly 100.0 (breakeven exit, pnl=0.0
  net of a 250-share position), proving the OLD stop (90) was genuinely
  replaced -- if it hadn't been, price never dropped below 90 in this
  fixture, so the position would still be open, not closed at pnl=0.
  consecutive_stops becomes 1 (the breakeven exit is itself a tracked stop
  fill, per notify_order's ref-based "was this our stop order" check).

FIXTURE 3 -- no-averaging-down guard (Group A).
  Entry 100 (position.price=100). _guard_no_averaging_down() called on two
  later bars: bar with close=95 (< position.price) -> PREDICTED blocked
  (allowed=False). bar with close=101 (>= position.price) -> PREDICTED
  allowed=True.

FIXTURE 4 -- losing-streak consecutive-stops tracking (Group A).
  [v0.27: losing-streak step-down REMOVED -- STREAK_STEPS=[1.0],
  STREAK_STEP_DOWN_TRIGGERS={}. streak_step_index always 0,
  current_streak_step always 1.0. target_position_count 4->6, so
  base_egp = equity/6. Entry sizes shrink only from equity erosion.]
  5 losing round-trips (each: flat entry bar, flat fill bar, then a 15%
  gap-down bar -- past the 10% stop but under the 20% Corp Action
  threshold), then 2 winning round-trips (rally to close=125 --
  deliberately UNDER the breakeven trigger of 130, see CONSTRUCTION NOTE
  below -- force-closed there for a real profit).
  PREDICTED trade-by-trade (consecutive_stops / streak_step_index /
  current_streak_step, all AFTER that trade's notify_trade update):
    trade 1 (loss): consecutive_stops=1, index=0, streak_step=1.0
    trade 2 (loss): consecutive_stops=2, index=0, streak_step=1.0
    trade 3 (loss): consecutive_stops=3, index=0, streak_step=1.0
    trade 4 (loss): consecutive_stops=4, index=0, streak_step=1.0
    trade 5 (loss): consecutive_stops=5, index=0, streak_step=1.0
    trade 6 (win):  consecutive_stops=0, index=0, streak_step=1.0
    trade 7 (win):  consecutive_stops=0, index=0, streak_step=1.0
  NOTE (P8 update): _update_defensive_mode() now requires >= 10 closed
  trades before activating (P8 fix). In this 7-trade fixture,
  defensive_mode NEVER activates. Sizes: 166/162/158/154/150/146/153,
  declining only from equity erosion across the 5 losses.

--------------------------------------------------------------------------
CONSTRUCTION NOTE: force-close vs. real breakeven swap can collide
--------------------------------------------------------------------------
Every Group A fixture's test harness (ExplicitEntryStrategy below) calls
the REAL _manage_open_position() every bar a position is held -- required
so Fixture 8's decline-tracking and Fixture 2's real breakeven swap both
exercise actual production code. That means if a fixture's own "rally then
force-close" bar ALSO happens to cross the real breakeven trigger
(unrealized_gain >= 3x initial_stop_distance, i.e. close>=130 for a 100
entry / 10% stop), _manage_open_position() cancels the original stop and
replaces it with a real breakeven stop on the SAME bar this fixture's own
manual cancel+close code also runs -- and since backtrader's cancel() does
not take effect until the following bar's broker processing, BOTH the
stray breakeven stop and the manual close's market order end up live at
once, and the stray stop can later fill against an already-flat position,
driving it short. This was caught empirically (an IndexError from a
missing trade close) while first building Fixture 4 with a 130 rally
target. Fixtures 4, 7, and 9 below rally to 125 instead (a real, clean
win, but deliberately kept under the 130 breakeven threshold) specifically
to avoid this collision; Fixture 2 deliberately rallies to exactly 130
because triggering the real breakeven swap IS that fixture's point, and it
never force-closes on top of it.

FIXTURE 5 -- defensive_mode trigger/revert via the real _update_defensive_mode()
  [v0.27: trigger loosened to ratio<1.5 OR rate<0.40; revert unchanged at
  ratio>=2.0 AND rate>=0.50].
  (Group B, exact formula: trigger if rolling_win_loss_ratio<1.5
  OR rolling_win_rate<0.40; revert only if BOTH >=2.0 AND >=0.50).
  History A: 10 wins @+14, 10 losses @-10 -> win_rate=10/20=0.50 (NOT <0.40,
  deliberately kept above the rate trigger), ratio=14/10=1.4 (<1.5) --
  isolates the ratio-only arm of the OR.
  PREDICTED: is_defensive_mode becomes True.
  History B: 11 wins @+20, 9 losses @-10 -> win_rate=11/20=0.55 (>=0.50),
  ratio=20/10=2.0 (>=2.0) -- BOTH conditions true.
  PREDICTED: is_defensive_mode reverts to False.
  Supplementary (AND not OR, not one of the 10 required): re-inject
  is_defensive_mode=True, then 7 wins @+25, 13 losses @-10 -> ratio=
  25/10=2.5 (>=2.0, satisfied) but win_rate=7/20=0.35 (<0.50, NOT satisfied).
  PREDICTED: stays True (does NOT revert) -- proves the revert condition is
  AND, not OR; a min()/either-condition revert would have wrongly cleared it.

FIXTURE 6 -- multiplicative stacking, THE most critical fixture (Group B).
  [v0.27: streak step-down removed (always 1.0); now tests defensive x
  reentry_pilot stacking. target_position_count 4->6, pilot 50%->75%.]
  is_defensive_mode=True, current_streak_step=1.0, is_reentry_from_cash=
  True. equity=100000 (starting cash), target_position_count=6
  -> base_egp=16667. combined_mult = 1.0 * 0.5 (defensive) * 0.75
  (reentry pilot) = 0.375 -- MULTIPLICATIVE, not min(0.5,0.75)=0.50.
  sized_egp = 16667*0.375 = 6250. close=100 -> shares=floor(6250/100)=62.
  PREDICTED: getsizing() returns 62, explicitly checked against the WRONG
  min()-based alternative (83 shares) to make the assertion unambiguous.

FIXTURE 7 -- reentry_from_cash pilot graduation (Group A, Section 2.2 exact
  rule: 75% pilot sizing, graduate to 100% after 2 consecutive winners).
  [v0.27: pilot 50%->75%, target_position_count 4->6. Entries 1-2 coincide
  at 125 shares (100000/6*0.75 = 100000/4*0.50 = 12500); entry 3 diverges.]
  is_reentry_from_cash injected True at start. 3 winning round-trips
  (entry@100, rally to close=125 -- deliberately under the breakeven
  trigger, see CONSTRUCTION NOTE above -- force-closed there).
  PREDICTED:
    entry 1: is_reentry_from_cash=True (pilot) -> 0.75x -> equity=100000,
      base=16667, sized=12500, shares=floor(12500/100)=125.
      trade 1 closes: pnl=(125-100)*125=3125.0. was_win=True,
      pilot_consecutive_winners: 0->1 (still piloting, needs 2).
    entry 2: still piloting (1 winner so far) -> 0.75x -> equity=103125,
      base=17187.5, sized=12890.625, shares=floor(12890.625/100)=128.
      trade 2 closes: pnl=(125-100)*128=3200.0. pilot_consecutive_winners:
      1->2 -> GRADUATES: is_reentry_from_cash becomes False, counter resets
      to 0.
    entry 3: no longer piloting -> 1.0x (full size) -> equity=106325,
      base=17720.83, shares=floor(17720.83/100)=177 -- PROVES graduation to
      100%, not still 75%.
      trade 3 closes: pnl=(125-100)*177=4425.0.

FIXTURE 8 -- largest-decline-since-entry flag, independent of stop status
  (Group A). Entry@100 (stop@90, never fires in this fixture). Rally to
  close=110 (new high). Then close=100 on 3x average volume (300000 vs a
  ~104000 50-day average) -- a 9.0909...% decline from the 110 high.
  PREDICTED: largest_decline_since_entry = (110-100)/110 = 0.090909...,
  exit_candidates flag becomes True.
  [Feature 9 note]: Feature 9 Rule 3 would sell on this volume-confirmed
  largest decline, but the position is only 1 bar old and the distribution
  bar rule is gated behind DISTRIBUTION_BAR_MIN_HOLDING_DAYS=10. So the
  flag-only behavior this fixture asserts is preserved: exit_candidates is
  still set (bookkeeping, not gated), but no sell fires and the position
  survives to bar 59. Feature 9's selling path is covered in
  test_feature9_known_answer.py.

FIXTURE 9 -- equity-based sizing reflects a real closed trade's P&L via
  real broker.getvalue() (Group A).
  [v0.27: target_position_count 4->6, base = equity/6.]
  Entry 1 @100: equity=100000, base=16667, shares=floor(16667/100)=166.
  PREDICTED first entry size = 166.
  Trade 1: rally to close=125 -- deliberately under the breakeven trigger,
  see CONSTRUCTION NOTE above -- force-closed there. pnl=(125-100)*166
  =4150.0.
  A settle bar brings price back down to 100 (clean baseline, isolating the
  equity effect from any price-level confound) before entry 2's signal.
  Entry 2 @ equity=104150 (100000+4150), base=17358.33, shares=
  floor(17358.33/100)=173. PREDICTED second entry size = 173, strictly
  greater than the first (166) purely because equity grew from the real
  closed trade's profit -- same price level (100) both times, so this
  isolates the equity effect.

FIXTURE 10 -- Liquidity Lock hard cap (Group B). Thin-liquidity ticker:
  close=100, volume=2000/day for 55 bars -> ADDV = 100*2000 = 200,000.
  2% cap = 4,000 EGP. Unconstrained sizing (equity/6 ~ 16,667 EGP) would be
  far larger than the cap -- engineered so the exact 1%-vs-2% choice
  (kashif_sizer.py's flagged, still-open design decision) doesn't change
  the QUALITATIVE outcome (the cap binds either way; only its exact value
  would differ, tested here at the code's actual 2% default).
  [v0.27: target_position_count 4->6, unconstrained now 166 not 250.]
  PREDICTED: getsizing() returns floor(4000/100) = 40 shares, not the
  unconstrained floor(16667/100)=166.

FIXTURE 11 (supplementary) -- Scoring Queue, 3 candidates for 4 available
  slots (Considerations.md Section 4, "Watchlist Traffic Jam"). 5 data
  feeds attached: OPEN1/OPEN2 already hold a real open position (consuming
  2 of target_position_count=6's slots -- available_slots=4), and 3 flat
  candidates A/B/C with soft_score 50/90/70 respectively.
  [v0.27: target_position_count 4->6, so 6-2=4 available slots. All 3
  candidates fit; none queued.]
  PREDICTED: ranked by soft_score descending (B=90, C=70, A=50), all 3
  get final_verdict="ENTERED" (4 slots > 3 candidates).

FIXTURE 12 (supplementary) -- Decision Receipt content correctness for a
  known hard_filter rejection. regime_open=True injected, but the ticker's
  history buffer has only 5 bars (far short of the 253-bar hard_filter
  requirement).
  PREDICTED: stages["market_regime_gate"]="PASS", stages["hard_filter"]=
  "SKIPPED: insufficient_history", final_verdict="REJECTED_AT_hard_filter",
  qualifies=False.

FIXTURE 13 (supplementary) -- streak x reentry co-occurrence, proving the
  3-way multiplicative stacking decision (kashif_sizer.py design decision
  #1) is actually implemented, not just described in a comment -- none of
  the 10 required fixtures exercises this exact combination.
  [v0.27: streak step-down removed but field still injectable; pilot
  50%->75%, target_position_count 4->6. Coincidentally still 50 shares.]
  current_streak_step=0.40 (injected), is_reentry_from_cash=True,
  is_defensive_mode=False. combined_mult = 0.40 * 1.0 * 0.75 = 0.30.
  equity=100000, base=16667, sized=5000, shares=floor(5000/100)=50.
  PREDICTED: getsizing() returns 50.

FIXTURE 14 -- N-3 fix proof: add-on buy cancels old stop, places
  consolidated stop for the full position.
  [v0.27: target_position_count 4->6. First buy 166 @ 100, add-on 160 @ 105,
  total 326.]
  First buy 166 shares @ 100, stop at 90. Price rises to 105, add-on buy
  160 shares @ 105. The old stop (90, 166 shares) must be cancelled BEFORE
  the new consolidated stop is placed -- otherwise two competing stops exist
  for different sizes. Gap-down to 80: the single consolidated stop fires
  for all 326 shares (not 166), proving the old stop was cancelled and
  replaced.
  PREDICTED: 1 cancellation, stop sell size = -326, fill at 80.0,
  PNL = -7320.0.

FIXTURE 15 -- N-4 fix proof: breakeven trigger uses blended average
  price, not original entry.
  [v0.27: target_position_count 4->6. First buy 166 @ 100, add-on 154 @ 110,
  total 320. Blended avg = 104.8125, trigger = 136.26.]
  Blended avg = 104.8125. Breakeven trigger = blended * 1.30 = 136.26.
  Old bug would trigger at 100 * 1.30 = 130. Price ramps: close=130 at
  bar 61 (old bug would fire here), close=135 at bar 62 (still below
  blended trigger), close=140 at bar 63 (above 136.26 -- breakeven
  fires HERE). Then gap through blended entry at bar 64 (open=103 <
  104.81), stop fires at 103.0 for all 320 shares. PREDICTED:
  breakeven_bar=63, stop price=103.0, PNL=-580.0.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pytest  # noqa: E402
import pandas as pd  # noqa: E402
import backtrader as bt  # noqa: E402
from kashif_sizer import MinerviniSizer  # noqa: E402
from kashif_strategy import KashifStrategy  # noqa: E402
import kashif_strategy as _ksB  # noqa: E402

TOL = 1e-6

# 55 flat, healthy-volume bars -- clears MinerviniSizer's 50-bar Liquidity
# Lock warm-up requirement (see module docstring construction note).
WARMUP = [{"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000} for _ in range(55)]


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


class ExplicitEntryStrategy(KashifStrategy):
    """
    Test-harness subclass used by every Group A fixture below: attempts an
    entry ONLY on a bar number explicitly listed in self.p.entry_trigger_bars,
    and force-closes (cancelling any live stop first) ONLY on a bar number
    listed in self.p.close_trigger_bars. This gives full deterministic
    control over exactly which bar is a signal vs. a fill -- avoiding any
    "auto re-enter the instant we go flat" cascading timing ambiguity.
    Adds no new trading logic of its own; every state mutation comes from
    the real KashifStrategy/MinerviniSizer methods it calls.
    """
    params = (("entry_trigger_bars", ()), ("close_trigger_bars", ()))

    def __init__(self):
        super().__init__()
        self.trade_log = []
        self.fill_log = []
        self.sizing_log = []

    def next(self):
        bar = len(self)
        pos = self.broker.getposition(self.data)
        if pos.size == 0 and bar in self.p.entry_trigger_bars:
            equity_before = self.broker.getvalue()
            size = self.getsizing(self.data, isbuy=True)
            self.sizing_log.append({"bar": bar, "size": size, "equity_before": equity_before})
            if size > 0:
                self.buy(data=self.data, size=size, exectype=bt.Order.Market)
        if pos.size > 0:
            self._manage_open_position(self.data)
        if pos.size > 0 and bar in self.p.close_trigger_bars:
            old_stop = self.stop_order.get(self.data)
            if old_stop is not None and old_stop.alive():
                self.cancel(old_stop)
            self.close(data=self.data)

    def notify_order(self, order):
        super().notify_order(order)
        if order.status == order.Completed:
            self.fill_log.append({"bar": len(self), "isbuy": order.isbuy(), "price": order.executed.price})

    def notify_trade(self, trade):
        super().notify_trade(trade)
        if trade.isclosed:
            self.trade_log.append({
                "bar": len(self), "pnl": trade.pnl,
                "consecutive_stops": self.consecutive_stops,
                "streak_step_index": self.streak_step_index,
                "streak_step": self.current_streak_step,
                "is_reentry_from_cash": self.is_reentry_from_cash,
                "pilot_consecutive_winners": self.pilot_consecutive_winners,
            })


class F3Strategy(ExplicitEntryStrategy):
    def __init__(self):
        super().__init__()
        self.guard_log = []

    def next(self):
        super().next()
        pos = self.broker.getposition(self.data)
        if pos.size > 0 and len(self) in (58, 59):
            allowed = self._guard_no_averaging_down(self.data)
            self.guard_log.append({"bar": len(self), "allowed": allowed})


class F5Strategy(KashifStrategy):
    def next(self):
        pass


class F6Strategy(KashifStrategy):
    def next(self):
        pass


class F7Strategy(ExplicitEntryStrategy):
    def __init__(self):
        super().__init__()
        self.is_reentry_from_cash = True


class F8Strategy(KashifStrategy):
    params = (("entry_trigger_bar", 56),)

    def __init__(self):
        super().__init__()
        self.decline_log = []
        self.entered = False

    def next(self):
        bar = len(self)
        pos = self.broker.getposition(self.data)
        if pos.size == 0 and not self.entered and bar == self.p.entry_trigger_bar:
            size = self.getsizing(self.data, isbuy=True)
            if size > 0:
                self.buy(data=self.data, size=size, exectype=bt.Order.Market)
            self.entered = True
        if pos.size > 0:
            self._manage_open_position(self.data)
            self.decline_log.append({
                "bar": bar,
                "largest_decline_since_entry": self.largest_decline_since_entry.get(self.data),
                "exit_candidate": self.exit_candidates.get(self.data),
            })


class F10Strategy(KashifStrategy):
    def next(self):
        pass


class F11Strategy(KashifStrategy):
    def __init__(self):
        super().__init__()
        self.opened = False

    def next(self):
        if not self.opened and len(self) == 56:
            for d in self.datas:
                if d._name in ("OPEN1", "OPEN2"):
                    self.buy(data=d, size=10, exectype=bt.Order.Market)
            self.opened = True


class F12Strategy(KashifStrategy):
    def next(self):
        pass


class F13Strategy(KashifStrategy):
    def next(self):
        pass


class F14Strategy(KashifStrategy):
    params = (("entry_trigger_bars", (56, 58)),)

    def __init__(self):
        super().__init__()
        self.fill_log = []
        self.cancel_log = []
        self.trade_log = []

    def next(self):
        bar = len(self)
        pos = self.broker.getposition(self.data)
        if pos.size == 0 and bar in self.p.entry_trigger_bars:
            size = self.getsizing(self.data, isbuy=True)
            if size > 0:
                self.buy(data=self.data, size=size, exectype=bt.Order.Market)
        elif pos.size > 0 and bar in self.p.entry_trigger_bars:
            if self._guard_no_averaging_down(self.data):
                size = self.getsizing(self.data, isbuy=True)
                if size > 0:
                    self.buy(data=self.data, size=size, exectype=bt.Order.Market)
        if pos.size > 0:
            self._manage_open_position(self.data)

    def notify_order(self, order):
        super().notify_order(order)
        if order.status == order.Completed:
            self.fill_log.append({
                "bar": len(self), "isbuy": order.isbuy(),
                "price": order.executed.price, "size": order.executed.size,
            })
        if order.status == order.Cancelled:
            self.cancel_log.append({"bar": len(self), "ref": order.ref})

    def notify_trade(self, trade):
        super().notify_trade(trade)
        if trade.isclosed:
            self.trade_log.append({"bar": len(self), "pnl": trade.pnl})


class F15Strategy(KashifStrategy):
    params = (("entry_trigger_bars", (56, 58)),)

    def __init__(self):
        super().__init__()
        self.fill_log = []
        self.trade_log = []
        self.breakeven_bar = None

    def next(self):
        bar = len(self)
        pos = self.broker.getposition(self.data)
        if pos.size == 0 and bar in self.p.entry_trigger_bars:
            size = self.getsizing(self.data, isbuy=True)
            if size > 0:
                self.buy(data=self.data, size=size, exectype=bt.Order.Market)
        elif pos.size > 0 and bar in self.p.entry_trigger_bars:
            if self._guard_no_averaging_down(self.data):
                size = self.getsizing(self.data, isbuy=True)
                if size > 0:
                    self.buy(data=self.data, size=size, exectype=bt.Order.Market)
        if pos.size > 0:
            prev_be = self.breakeven_done.get(self.data, False)
            self._manage_open_position(self.data)
            cur_be = self.breakeven_done.get(self.data, False)
            if cur_be and not prev_be:
                self.breakeven_bar = bar

    def notify_order(self, order):
        super().notify_order(order)
        if order.status == order.Completed:
            self.fill_log.append({
                "bar": len(self), "isbuy": order.isbuy(),
                "price": order.executed.price, "size": order.executed.size,
            })

    def notify_trade(self, trade):
        super().notify_trade(trade)
        if trade.isclosed:
            self.trade_log.append({"bar": len(self), "pnl": trade.pnl})


class F16Strategy(KashifStrategy):
    params = (("entry_trigger_bars", (56,)),)

    def __init__(self):
        super().__init__()
        self.fill_log = []
        self.trade_log = []

    def next(self):
        bar = len(self)
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
                "bar": len(self), "isbuy": order.isbuy(),
                "price": order.executed.price, "size": order.executed.size,
            })

    def notify_trade(self, trade):
        super().notify_trade(trade)
        if trade.isclosed:
            self.trade_log.append({"bar": len(self), "pnl": trade.pnl})


class F17Strategy(ExplicitEntryStrategy):
    def __init__(self):
        super().__init__()
        self.position_by_bar = []

    def next(self):
        super().next()
        bar = len(self)
        self.position_by_bar.append((bar, self.broker.getposition(self.data).size))
        # Bar 58: deliberately sell 2x the open position, forcing a short.
        if bar == 58:
            pos = self.broker.getposition(self.data)
            if pos.size > 0:
                self.sell(data=self.data, size=pos.size * 2, exectype=bt.Order.Market)


class F18Strategy(ExplicitEntryStrategy):
    """Injects a synthetic receipt carrying a pivot, as the real pipeline does."""
    params = (("pivot", None),)

    def next(self):
        bar = len(self)
        if bar == self.p.entry_trigger_bars[0]:
            self._pending_entry_receipt[self.data] = (
                {"pivot_price": self.p.pivot} if self.p.pivot else {})
        super().next()


# ============================================================
# Test functions
# ============================================================


def test_fixture1a_stop_loss_touch():
    bars1a = list(WARMUP) + [
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 95, "high": 96, "low": 85, "close": 87, "volume": 100000},
    ]
    strat1a = run_cerebro(bars1a, ExplicitEntryStrategy, entry_trigger_bars=(56,))
    # [UPDATED - Fix B]: the harness supplies no receipt, so there is no pivot
    # and the stop falls back to NO_PIVOT_STOP_DISTANCE = 7% -> 93.00, not the
    # old flat 10% -> 90.00. Bar opens 95 with low 85, so it still TOUCHES
    # (does not gap) and fills exactly at the stop: 93.0.
    # pnl = (93 - 100) * 166 = -1162.0
    assert approx(93.0, strat1a.fill_log[1]["price"])
    assert approx(-1162.0, strat1a.trade_log[0]["pnl"])
    assert strat1a.trade_log[0]["consecutive_stops"] == 1


def test_fixture1b_stop_loss_gap():
    bars1b = list(WARMUP) + [
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 82, "high": 83, "low": 80, "close": 81, "volume": 100000},
    ]
    strat1b = run_cerebro(bars1b, ExplicitEntryStrategy, entry_trigger_bars=(56,))
    assert approx(82.0, strat1b.fill_log[1]["price"])
    assert approx(-2988.0, strat1b.trade_log[0]["pnl"])
    assert strat1b.trade_log[0]["consecutive_stops"] == 1
    assert len(strat1b.flagged_for_review) == 0


def test_fixture2_breakeven_stop_swap():
    bars2 = list(WARMUP) + [
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 131, "low": 99, "close": 130, "volume": 100000},
        {"open": 130, "high": 131, "low": 129, "close": 130, "volume": 100000},
        {"open": 105, "high": 106, "low": 95, "close": 98, "volume": 100000},
    ]
    strat2 = run_cerebro(bars2, ExplicitEntryStrategy, entry_trigger_bars=(56,))
    assert approx(100.0, strat2.fill_log[1]["price"])
    assert approx(0.0, strat2.trade_log[0]["pnl"])
    assert strat2.trade_log[0]["consecutive_stops"] == 1


def test_fixture3_no_averaging_down():
    bars3 = list(WARMUP) + [
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 95, "high": 96, "low": 94, "close": 95, "volume": 100000},
        {"open": 101, "high": 102, "low": 100, "close": 101, "volume": 100000},
    ]
    strat3 = run_cerebro(bars3, F3Strategy, entry_trigger_bars=(56,))
    assert strat3.guard_log[0]["allowed"] is False
    assert strat3.guard_log[1]["allowed"] is True


def test_fixture4_losing_streak():
    bars4 = list(WARMUP)
    entry_bars4 = []
    close_bars4 = []
    for _ in range(5):
        entry_bars4.append(len(bars4) + 1)
        bars4.append({"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000})
        bars4.append({"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000})
        bars4.append({"open": 85, "high": 86, "low": 84, "close": 85, "volume": 100000})
    for _ in range(2):
        entry_bars4.append(len(bars4) + 1)
        bars4.append({"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000})
        close_bars4.append(len(bars4) + 1)
        bars4.append({"open": 100, "high": 126, "low": 99, "close": 125, "volume": 100000})
        bars4.append({"open": 125, "high": 126, "low": 124, "close": 125, "volume": 100000})

    strat4 = run_cerebro(bars4, ExplicitEntryStrategy,
                          entry_trigger_bars=tuple(entry_bars4), close_trigger_bars=tuple(close_bars4))

    # [UPDATED -- Fix 9/A6 + Fix 18/B3]: losing-streak step-down RESTORED.
    predicted_trades4 = [
        {"pnl": -2490.0, "consecutive_stops": 1, "streak_step_index": 0, "streak_step": 1.0},
        {"pnl": -2430.0, "consecutive_stops": 2, "streak_step_index": 0, "streak_step": 1.0},
        {"pnl": -2370.0, "consecutive_stops": 3, "streak_step_index": 1, "streak_step": 0.40},
        {"pnl": -915.0, "consecutive_stops": 4, "streak_step_index": 1, "streak_step": 0.40},
        {"pnl": -915.0, "consecutive_stops": 5, "streak_step_index": 2, "streak_step": 0.20},
        {"pnl": 750.0, "consecutive_stops": 0, "streak_step_index": 1, "streak_step": 0.40},
        {"pnl": 1525.0, "consecutive_stops": 0, "streak_step_index": 0, "streak_step": 1.0},
    ]
    for i, pred in enumerate(predicted_trades4):
        actual = strat4.trade_log[i]
        assert approx(pred["pnl"], actual["pnl"]), f"trade {i+1} pnl: predicted={pred['pnl']}, actual={actual['pnl']}"
        assert actual["consecutive_stops"] == pred["consecutive_stops"], f"trade {i+1} consecutive_stops: predicted={pred['consecutive_stops']}, actual={actual['consecutive_stops']}"
        assert actual["streak_step_index"] == pred["streak_step_index"], f"trade {i+1} streak_step_index: predicted={pred['streak_step_index']}, actual={actual['streak_step_index']}"
        assert approx(pred["streak_step"], actual["streak_step"]), f"trade {i+1} streak_step: predicted={pred['streak_step']}, actual={actual['streak_step']}"

    predicted_sizes4 = [166, 162, 158, 61, 61, 30, 61]  # Fix 9/A6: real step-downs
    for i, pred_size in enumerate(predicted_sizes4):
        assert strat4.sizing_log[i]["size"] == pred_size, (
            f"entry {i+1} size: predicted={pred_size}, actual={strat4.sizing_log[i]['size']}")

    assert strat4.streak_step_index == 0
    assert approx(1.0, strat4.current_streak_step)


def test_fixture5_defensive_mode():
    strat5 = run_cerebro(list(WARMUP[:5]), F5Strategy)

    # History A: ratio=1.4<1.5, win_rate=0.50 -> triggers defensive_mode
    for _ in range(10):
        strat5.recent_closed_trades.append({"pnl": 14.0, "was_win": True})
    for _ in range(10):
        strat5.recent_closed_trades.append({"pnl": -10.0, "was_win": False})
    strat5._update_defensive_mode()
    assert strat5.is_defensive_mode is True

    # History B: ratio=2.0>=2.0 AND win_rate=0.55>=0.50 -> reverts
    strat5.recent_closed_trades.clear()
    for _ in range(11):
        strat5.recent_closed_trades.append({"pnl": 20.0, "was_win": True})
    for _ in range(9):
        strat5.recent_closed_trades.append({"pnl": -10.0, "was_win": False})
    strat5._update_defensive_mode()
    assert strat5.is_defensive_mode is False

    # Supplementary: proves AND not OR on revert
    # ratio=2.5 (>=2.0, ok) but win_rate=0.35 (<0.50, NOT ok) -> stays True
    strat5.is_defensive_mode = True
    strat5.recent_closed_trades.clear()
    for _ in range(7):
        strat5.recent_closed_trades.append({"pnl": 25.0, "was_win": True})
    for _ in range(13):
        strat5.recent_closed_trades.append({"pnl": -10.0, "was_win": False})
    strat5._update_defensive_mode()
    assert strat5.is_defensive_mode is True


def test_fixture6_multiplicative_stacking():
    strat6 = run_cerebro(list(WARMUP), F6Strategy)
    strat6.is_defensive_mode = True
    strat6.current_streak_step = 1.0
    strat6.is_reentry_from_cash = True
    size6 = strat6.getsizing(strat6.data, isbuy=True)
    # [UPDATED -- Fix 17/B2 + Fix 10/A4]: stacking is now min(), not product.
    # min(0.50 defensive, 0.50 pilot) = 0.50
    # 16666.67 * 0.50 = 8333.33 -> floor(8333.33/100) = 83 shares
    assert size6 == 83
    assert size6 != 41  # explicitly NOT the old product 0.50 x 0.50 = 0.25x


def test_fixture7_pilot_graduation():
    bars7 = list(WARMUP)
    entry_bars7 = []
    close_bars7 = []
    for _ in range(3):
        entry_bars7.append(len(bars7) + 1)
        bars7.append({"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000})
        close_bars7.append(len(bars7) + 1)
        bars7.append({"open": 100, "high": 126, "low": 99, "close": 125, "volume": 100000})
        bars7.append({"open": 125, "high": 126, "low": 124, "close": 125, "volume": 100000})

    strat7 = run_cerebro(bars7, F7Strategy,
                          entry_trigger_bars=tuple(entry_bars7), close_trigger_bars=tuple(close_bars7))

    # Entry 1: piloting, 0.50x
    assert strat7.sizing_log[0]["size"] == 83
    assert approx(2075.0, strat7.trade_log[0]["pnl"])
    assert strat7.trade_log[0]["pilot_consecutive_winners"] == 1
    assert strat7.trade_log[0]["is_reentry_from_cash"] is True

    # Entry 2: still piloting, 0.50x
    assert strat7.sizing_log[1]["size"] == 85
    assert approx(2125.0, strat7.trade_log[1]["pnl"])
    assert strat7.trade_log[1]["is_reentry_from_cash"] is False  # GRADUATED
    assert strat7.trade_log[1]["pilot_consecutive_winners"] == 0  # reset

    # Entry 3: graduated, full 1.0x
    assert strat7.sizing_log[2]["size"] == 173
    assert approx(4325.0, strat7.trade_log[2]["pnl"])


def test_fixture8_decline_flag():
    bars8 = list(WARMUP) + [
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 111, "low": 99, "close": 110, "volume": 100000},
        {"open": 110, "high": 111, "low": 99, "close": 100, "volume": 300000},
        {"open": 100, "high": 101, "low": 94, "close": 95, "volume": 100000},
    ]
    strat8 = run_cerebro(bars8, F8Strategy)
    assert abs(strat8.decline_log[1]["largest_decline_since_entry"] - (110 - 100) / 110) < 1e-4
    assert strat8.decline_log[1]["exit_candidate"] is True
    assert approx(strat8.decline_log[1]["largest_decline_since_entry"],
                  strat8.decline_log[2]["largest_decline_since_entry"])
    assert strat8.decline_log[2]["exit_candidate"] is True


def test_fixture9_equity_sizing():
    bars9 = list(WARMUP)
    entry_bars9 = [len(bars9) + 1]
    bars9.append({"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000})
    close_bars9 = [len(bars9) + 1]
    bars9.append({"open": 100, "high": 126, "low": 99, "close": 125, "volume": 100000})
    bars9.append({"open": 125, "high": 126, "low": 124, "close": 125, "volume": 100000})
    bars9.append({"open": 125, "high": 125, "low": 99, "close": 100, "volume": 100000})  # settle back to 100
    entry_bars9.append(len(bars9) + 1)
    bars9.append({"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000})

    strat9 = run_cerebro(bars9, ExplicitEntryStrategy,
                          entry_trigger_bars=tuple(entry_bars9), close_trigger_bars=tuple(close_bars9))
    assert strat9.sizing_log[0]["size"] == 166
    assert approx(4150.0, strat9.trade_log[0]["pnl"])
    assert approx(104150.0, strat9.sizing_log[1]["equity_before"])
    assert strat9.sizing_log[1]["size"] == 173
    assert strat9.sizing_log[1]["size"] > strat9.sizing_log[0]["size"]


def test_fixture10_liquidity_lock():
    bars10 = [{"open": 100, "high": 101, "low": 99, "close": 100, "volume": 2000} for _ in range(55)]
    strat10 = run_cerebro(bars10, F10Strategy)
    size10 = strat10.getsizing(strat10.data, isbuy=True)
    assert size10 == 40


def test_fixture11_scoring_queue():
    bars11 = list(WARMUP) + [
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
    ]
    df11 = pd.DataFrame(bars11, index=pd.date_range("2024-01-01", periods=len(bars11), freq="D"))
    cerebro11 = bt.Cerebro()
    for nm in ("OPEN1", "OPEN2", "A", "B", "C"):
        cerebro11.adddata(bt.feeds.PandasData(dataname=df11, name=nm))
    cerebro11.broker.setcash(100000)
    cerebro11.broker.setcommission(commission=0.0)
    cerebro11.broker.set_coc(False)
    cerebro11.addstrategy(F11Strategy)
    cerebro11.addsizer(MinerviniSizer)
    strat11 = cerebro11.run()[0]

    by_name = {d._name: d for d in strat11.datas}
    candidates11 = [
        (by_name["A"], {"soft_score": 50, "final_verdict": "PENDING", "ticker": "A"}),
        (by_name["B"], {"soft_score": 90, "final_verdict": "PENDING", "ticker": "B"}),
        (by_name["C"], {"soft_score": 70, "final_verdict": "PENDING", "ticker": "C"}),
    ]
    strat11._run_scoring_queue(candidates11)
    verdicts11 = {r["ticker"]: r["final_verdict"] for _, r in candidates11}
    assert verdicts11["B"] == "ENTERED"
    assert verdicts11["C"] == "ENTERED"
    assert verdicts11["A"] == "ENTERED"


def test_fixture12_decision_receipt():
    strat12 = run_cerebro(list(WARMUP[:5]), F12Strategy)
    d12 = strat12.datas[0]
    strat12.regime_open = True
    strat12.history[d12].extend([{"Open": 100, "High": 101, "Low": 99, "Close": 100, "Volume": 100000}] * 5)
    receipt12, qualifies12 = strat12._evaluate_entry_pipeline(d12)
    assert receipt12["stages"]["market_regime_gate"] == "PASS"
    assert receipt12["stages"]["hard_filter"] == "SKIPPED: insufficient_history"
    assert receipt12["final_verdict"] == "REJECTED_AT_hard_filter"
    assert qualifies12 is False


def test_fixture13_streak_reentry():
    strat13 = run_cerebro(list(WARMUP), F13Strategy)
    strat13.current_streak_step = 0.40
    strat13.is_reentry_from_cash = True
    strat13.is_defensive_mode = False
    size13 = strat13.getsizing(strat13.data, isbuy=True)
    assert size13 == 66


def test_fixture14_addon_stop():
    bars14 = list(WARMUP) + [
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 105, "high": 106, "low": 104, "close": 105, "volume": 100000},
        {"open": 105, "high": 106, "low": 104, "close": 105, "volume": 100000},
        {"open": 80, "high": 81, "low": 78, "close": 79, "volume": 100000},
    ]
    strat14 = run_cerebro(bars14, F14Strategy)

    buys14 = [f for f in strat14.fill_log if f["isbuy"]]
    sells14 = [f for f in strat14.fill_log if not f["isbuy"]]
    total14 = sum(f["size"] for f in buys14)

    assert buys14[0]["size"] == 166
    assert approx(100.0, buys14[0]["price"])
    assert buys14[1]["size"] == 160
    assert approx(105.0, buys14[1]["price"])
    assert total14 == 326
    assert len(strat14.cancel_log) == 1
    assert sells14[0]["size"] == -total14
    assert approx(80.0, sells14[0]["price"])
    assert approx(-7320.0, strat14.trade_log[0]["pnl"])


def test_fixture15_breakeven_blended():
    bars15 = list(WARMUP) + [
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 110, "high": 111, "low": 109, "close": 110, "volume": 100000},
        {"open": 110, "high": 111, "low": 109, "close": 110, "volume": 100000},
        {"open": 120, "high": 121, "low": 119, "close": 120, "volume": 100000},
        {"open": 130, "high": 131, "low": 129, "close": 130, "volume": 100000},
        {"open": 135, "high": 136, "low": 134, "close": 135, "volume": 100000},
        {"open": 140, "high": 141, "low": 139, "close": 140, "volume": 100000},
        {"open": 103, "high": 104, "low": 95, "close": 98, "volume": 100000},
    ]
    strat15 = run_cerebro(bars15, F15Strategy)

    buys15 = [f for f in strat15.fill_log if f["isbuy"]]
    sells15 = [f for f in strat15.fill_log if not f["isbuy"]]
    total15 = sum(f["size"] for f in buys15)

    assert buys15[0]["size"] == 166
    assert approx(100.0, buys15[0]["price"])
    assert buys15[1]["size"] == 154
    assert approx(110.0, buys15[1]["price"])
    # [UPDATED - Fix B]: breakeven now fires at blended * (1 + 4 * sd_pct).
    assert strat15.breakeven_bar == 62
    assert sells15[0]["size"] == -total15
    assert approx(103.0, sells15[0]["price"])
    assert approx(-580.0, strat15.trade_log[0]["pnl"])


def test_fixture16_gap_down_stop():
    bars16 = list(WARMUP) + [
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 75, "high": 76, "low": 74, "close": 75, "volume": 100000},
    ]
    strat16 = run_cerebro(bars16, F16Strategy)

    buys16 = [f for f in strat16.fill_log if f["isbuy"]]
    sells16 = [f for f in strat16.fill_log if not f["isbuy"]]

    assert buys16[0]["size"] == 166
    assert approx(100.0, buys16[0]["price"])
    assert approx(75.0, sells16[0]["price"])
    assert approx(-4150.0, strat16.trade_log[0]["pnl"])


def test_fixture17_net_short_safety():
    bars17 = list(WARMUP) + [
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000},
    ]
    strat17 = run_cerebro(bars17, F17Strategy, entry_trigger_bars=(56,))

    sizes17 = dict(strat17.position_by_bar)
    negative_bars = [b for b, s in strat17.position_by_bar if s < 0]
    flags17 = [f for f in strat17.flagged_for_review
               if f.get("reason") == "unintended_short_position_auto_flattened"]

    assert len(flags17) == 1
    assert len(negative_bars) == 1
    assert negative_bars == [59]
    assert sizes17.get(60) == 0
    assert flags17[0]["shares"] == 166 if flags17 else False


@pytest.mark.parametrize("label,pivot,exp_stop,exp_dist,exp_be", [
    ("18a pivot=96", 96.0, 93.12, 6.88, 127.52),
    ("18b pivot=88 (capped)", 88.0, 90.00, 10.00, 140.00),
    ("18c no pivot", None, 93.00, 7.00, 128.00),
])
def test_fixture18_pivot_stop(label, pivot, exp_stop, exp_dist, exp_be):
    flat = {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100000}
    bars18 = list(WARMUP) + [dict(flat), dict(flat), dict(flat)]

    s18 = run_cerebro(bars18, F18Strategy, entry_trigger_bars=(56,), pivot=pivot)
    d18 = s18.data
    stop_order = s18.stop_order.get(d18)
    assert abs(round(stop_order.price, 4) - exp_stop) < 1e-4, (
        f"{label}: stop price predicted={exp_stop}, actual={round(stop_order.price, 4)}")
    assert abs(round(s18.initial_stop_distance[d18], 4) - exp_dist) < 1e-4, (
        f"{label}: initial_stop_distance predicted={exp_dist}, actual={round(s18.initial_stop_distance[d18], 4)}")
    be_trigger = s18.entry_price[d18] + _ksB.BREAKEVEN_TRIGGER_MULT * s18.initial_stop_distance[d18]
    assert abs(round(be_trigger, 4) - exp_be) < 1e-4, (
        f"{label}: breakeven trigger predicted={exp_be}, actual={round(be_trigger, 4)}")


def test_fixture18_pivot_stop_constants():
    assert _ksB.BREAKEVEN_TRIGGER_MULT == 4.0
    assert _ksB.STOP_DISTANCE_MIN == 0.04
    assert _ksB.STOP_DISTANCE_MAX == 0.10
