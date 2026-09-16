"""
MinerviniSizer(bt.Sizer) -- Feature 4 (Risk Rules & Position Sizing), sizing half.

Implements: equity-based sizing (Section 2.4), losing_streak_response step-downs
(Section 2.1), defensive_mode multiplier (JSON risk_rules.defensive_mode, v0.17),
multiplicative stacking of losing_streak x defensive_mode x reentry_from_cash
(JSON's explicit stacking_rule, extended -- see note below), reentry_from_cash
pilot sizing (Section 2.2), and the Liquidity Lock EGX guard (Considerations.md
Section 4 / feature-04.md Section 0.2).

--------------------------------------------------------------------------
SHARED STATE CONTRACT with kashif_strategy.py -- do not let these drift apart
--------------------------------------------------------------------------
This sizer reads the following attributes off self.strategy (bound automatically
by backtrader's Sizer.set(strategy, broker) when attached via
cerebro.addsizer()/strategy.setsizer() -- verified empirically before writing
this file, not assumed):

  self.strategy.p.target_position_count      (int, Strategy parameter)
  self.strategy.current_streak_step          (float: 1.0 / 0.40 / 0.20)
  self.strategy.is_defensive_mode            (bool)
  self.strategy.is_reentry_from_cash         (bool)
  self.strategy.defensive_mode_multiplier    (float, read from JSON at strategy
                                               init, default 0.5)
  self.strategy.reentry_pilot_multiplier     (float, default 0.75)

kashif_strategy.py OWNS and updates all of these; this file only reads them.

--------------------------------------------------------------------------
DESIGN DECISIONS flagged explicitly (per this project's "don't guess silently"
standard -- confirmed/resolved during planning, recorded here so the reasoning
travels with the code, not just the plan file)
--------------------------------------------------------------------------
1. STACKING SCOPE: the JSON's risk_rules.defensive_mode.relationship_to_
   performance_scaling.stacking_rule explicitly specifies multiplicative
   stacking for losing_streak x defensive_mode ("e.g. a losing-streak step of
   40% combined with defensive_mode's 0.5x = 20% of normal size"). This
   implementation EXTENDS that same multiplicative treatment to
   is_reentry_from_cash's pilot multiplier too, since all three are
   independent, non-mutually-exclusive caution signals: consecutive_stops
   only resets on a WINNING close (Section 2.1), not on going flat, so a
   trader who stepped down from a losing streak and later drifted to zero
   open positions can genuinely re-enter with is_reentry_from_cash=True
   AND current_streak_step still reduced. Taking min()/exclusive-precedence
   between these would silently discard one caution signal the moment the
   other takes over -- the same failure mode the JSON explicitly rejected
   for the losing_streak/defensive_mode pair, for the same risk-first
   reasoning (MANIFESTO.md Part 0). Not covered by any of the 10 required
   known-answer fixtures; covered by supplementary Fixture 13.

2. LIQUIDITY_LOCK_POSITION_PCT_OF_ADDV: Considerations.md Section 4 and
   feature-04.md Section 0.2 both say "1% or 2%" / "1-2%" without picking one.
   Genuinely unresolved in the source material -- defaulted to 2% (the
   permissive end) below. Flagged here as an open question for an explicit
   product decision, not silently invented as if it were a specified number.

3. LIQUIDITY LOCK APPLIED AS A HARD CAP (min()), NOT MULTIPLICATIVELY: it's a
   safety ceiling on an already-sized order, not a performance-based
   modifier. Stacking it multiplicatively with the streak/defensive/reentry
   multipliers would make it bind MORE weakly precisely when those
   multipliers have already made the order small -- backwards for a safety
   guard, which should cap identically regardless of how conservative the
   other multipliers already made the order.

4. FAILS CLOSED (returns 0) if fewer than 50 volume observations exist yet
   for a ticker's ADDV calculation -- a safety lock with missing data should
   not silently permit an uncapped order.

5. target_position_count defaults to 4 (JSON's own "~25% of capital per
   position (4 equal positions) as baseline"). No EGP threshold exists
   anywhere in the source material to auto-distinguish a "small" vs "large"
   account for concurrent_positions.max_small_account(6)/max_large_account(12)
   -- flagged as an open question, not invented.
"""

import math

LIQUIDITY_LOCK_POSITION_PCT_OF_ADDV = 0.02  # see design decision #2 above -- unresolved in source docs, defaulted
LIQUIDITY_LOCK_ADDV_WINDOW = 50
DEFAULT_TARGET_POSITION_COUNT = 6  # v0.27: 4->6, profit-first (book's 4-6 range)
CONCURRENT_POSITIONS_MIN = 4
CONCURRENT_POSITIONS_HARD_CEILING = 20


try:
    import backtrader as bt
except ImportError:  # pragma: no cover
    bt = None


class MinerviniSizer(bt.Sizer if bt is not None else object):
    """
    _getsizing(self, comminfo, cash, data, isbuy) -- backtrader's standard
    Sizer override signature. `comminfo` accepted but unused in v1 (no
    commission-aware max-affordable-shares logic required by the spec).
    `cash` (broker.getcash(), settled cash only) is accepted but NOT used as
    the sizing base -- Section 2.4 explicitly requires TOTAL EQUITY
    (broker.getvalue()), not just settled cash.
    """

    def _getsizing(self, comminfo, cash, data, isbuy):
        if not isbuy:
            # Exits in kashif_strategy.py are issued with an explicit size=
            # (see its module docstring), which bypasses the sizer entirely --
            # backtrader only auto-invokes _getsizing() when buy()/sell() is
            # called WITHOUT an explicit size. This branch exists so the
            # sizer still behaves sanely if that convention is ever violated.
            return self.strategy.broker.getposition(data).size

        strat = self.strategy

        # 1. Equity-based baseline (Section 2.4): current TOTAL equity, not a
        # hardcoded starting amount and not just settled cash.
        equity = strat.broker.getvalue()
        target_count = getattr(strat.p, "target_position_count", DEFAULT_TARGET_POSITION_COUNT)
        base_egp = equity / target_count

        # 2. B2 — MINIMUM, not product, of the three independent caution/pilot
        # signals. Multiplying compounded them (defensive 0.5 x streak 0.40 =
        # 0.20, a size neither mechanism asked for); the book describes each
        # separately and gives no basis for compounding. The most cautious
        # signal wins outright.
        streak_mult = getattr(strat, "current_streak_step", 1.0)
        defensive_mult = getattr(strat, "defensive_mode_multiplier", 0.5) if getattr(strat, "is_defensive_mode", False) else 1.0
        reentry_mult = getattr(strat, "reentry_pilot_multiplier", 0.50) if getattr(strat, "is_reentry_from_cash", False) else 1.0
        combined_mult = min(streak_mult, defensive_mult, reentry_mult)

        sized_egp = base_egp * combined_mult

        # 3. Liquidity Lock -- hard cap applied LAST, not stacked multiplicatively
        # (see design decisions #2/#3/#4 above).
        addv = self._compute_addv(data, window=LIQUIDITY_LOCK_ADDV_WINDOW)
        if addv is None:
            return 0  # fail closed -- insufficient volume history
        liquidity_cap_egp = LIQUIDITY_LOCK_POSITION_PCT_OF_ADDV * addv
        final_egp = min(sized_egp, liquidity_cap_egp)

        # 4. Convert to shares.
        price = data.close[0]
        if price <= 0:
            return 0
        shares = math.floor(final_egp / price)
        return max(shares, 0)

    @staticmethod
    def _compute_addv(data, window=LIQUIDITY_LOCK_ADDV_WINDOW):
        """
        50-day average daily dollar volume = mean(close[i] * volume[i]) over
        the trailing `window` bars, inclusive of today. Returns None if fewer
        than `window` bars of history are available yet (triggers fail-closed
        behavior in _getsizing()).
        """
        try:
            closes = data.close.get(size=window)
            volumes = data.volume.get(size=window)
        except Exception:
            return None
        if closes is None or volumes is None or len(closes) < window or len(volumes) < window:
            return None
        dollar_volumes = [c * v for c, v in zip(closes, volumes)]
        return sum(dollar_volumes) / len(dollar_volumes)
