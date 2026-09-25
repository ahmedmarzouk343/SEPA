"""Market layer: everything that differs between exchanges lives here.

A strategy never hardcodes currency, settlement, fees, calendar or the rule
for when fundamentals become public. It asks the MarketSpec. Adding a market
means adding a spec (and its data loaders), not editing the engine.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable


@dataclass(frozen=True)
class MarketSpec:
    name: str
    currency: str
    settlement_days: int                      # T+N cash settlement
    yahoo_suffix: str                         # "" for US, ".CA" for EGX
    benchmarks: tuple                         # tickers used for comparison
    commission: Callable[[float, float], float]          # (shares, price) -> fee
    slippage_bps: Callable[[float, float], float]        # (order_value, addv) -> bps
    liquidity_cap_pct_addv: float             # max position as fraction of 50d avg $ volume
    # First trading-date-agnostic calendar date a fundamentals row may be used,
    # given its release date and whether the release carried an intraday time
    # that was before the close.
    fundamentals_usable_from: Callable[[date, bool], date]
    notes: tuple = field(default_factory=tuple)


# --------------------------------------------------------------------------
# United States (NYSE/Nasdaq)
# --------------------------------------------------------------------------
def _us_commission(shares: float, price: float) -> float:
    """IBKR fixed pricing: $0.005/share, $1.00 minimum, capped at 1% of value."""
    shares = abs(shares)
    if shares == 0:
        return 0.0
    fee = max(1.0, 0.005 * shares)
    return min(fee, 0.01 * shares * price)


def _us_slippage_bps(order_value: float, addv: float) -> float:
    """Half-spread plus square-root market impact.

    5 bps base + 10 bps * sqrt(participation / 1%). At 1% of average daily
    dollar volume that is 15 bps, at the 2% liquidity cap 19 bps; a thin
    name hits the same dollar order at a higher participation and pays more.
    A modelling assumption, not a measured cost -- reported as such.
    """
    if addv is None or addv <= 0 or not math.isfinite(addv):
        return 50.0  # no volume information: assume a wide 50 bps
    participation = abs(order_value) / addv
    return 5.0 + 10.0 * math.sqrt(participation / 0.01)


def _us_fundamentals_usable_from(release: date, before_close: bool) -> date:
    """SEC filings without an intraday timestamp are treated as usable the next
    day (a 10-Q filed at 17:30 is not known at that day's close). An 8-K
    accepted before 16:00 ET is usable the same day."""
    return release if before_close else release + timedelta(days=1)


US = MarketSpec(
    name="US",
    currency="USD",
    settlement_days=1,
    yahoo_suffix="",
    benchmarks=("MDY", "IJR", "SPY"),
    commission=_us_commission,
    slippage_bps=_us_slippage_bps,
    liquidity_cap_pct_addv=0.02,
    fundamentals_usable_from=_us_fundamentals_usable_from,
    notes=("T+1 settlement since 2024-05-28 (T+2 before); modelled as T+1 throughout",),
)


# --------------------------------------------------------------------------
# Egypt (EGX) -- the extension point. Settlement, fees and the FRA filing
# lag are real; a point-in-time fundamentals store does not exist yet, so the
# engine refuses to run a fundamentals-based strategy on EGX until one does.
# --------------------------------------------------------------------------
def _egx_commission(shares: float, price: float) -> float:
    return 0.005 * abs(shares) * price       # the EGX runner's 0.5% all-in fee


def _egx_slippage_bps(order_value: float, addv: float) -> float:
    if addv is None or addv <= 0:
        return 100.0
    return 10.0 + 20.0 * math.sqrt(abs(order_value) / addv / 0.01)


def _egx_fundamentals_usable_from(release: date, before_close: bool) -> date:
    # FRA deadline is 45 days after quarter end (sometimes 60); an EGX store
    # must supply the actual disclosure date. Same next-day rule meanwhile.
    return release + timedelta(days=1)


EGX = MarketSpec(
    name="EGX",
    currency="EGP",
    settlement_days=2,
    yahoo_suffix=".CA",
    benchmarks=(),
    commission=_egx_commission,
    slippage_bps=_egx_slippage_bps,
    liquidity_cap_pct_addv=0.02,
    fundamentals_usable_from=_egx_fundamentals_usable_from,
    notes=("No point-in-time EGX fundamentals store yet (see HOW_TO_EXTEND.md)",),
)

MARKETS = {"US": US, "EGX": EGX}
