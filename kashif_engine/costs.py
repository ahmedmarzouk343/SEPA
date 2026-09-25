"""Per-ticker trading costs for backtrader, driven by the MarketSpec.

The broker holds SPLIT-ADJUSTED shares at split-adjusted prices (see
data/prices.py). Costs that depend on the as-traded share count -- the
per-share commission, its $1 minimum -- are computed on RAW shares:

    raw_shares = adj_shares / F,  raw_price = adj_price * F

with F the product of split ratios after the fill date. Dollar values are
identical in both units, so P&L is unchanged; only the per-share fee needs
the raw count.

Slippage is booked as a COST (its own ledger account), not by moving the
fill price: the fill stays the bar's real open / stop price, which keeps the
auditor's price checks against the tape exact.
"""
from __future__ import annotations

import math

import backtrader as bt


def cost_breakdown(market, adj_size, adj_price, split_factor, addv_prev):
    """(commission, slippage, raw_shares, raw_price) for one fill."""
    q = abs(adj_size)
    raw_shares = q / split_factor
    raw_price = adj_price * split_factor
    commission = market.commission(raw_shares, raw_price)
    value = q * adj_price
    bps = market.slippage_bps(value, addv_prev if addv_prev and math.isfinite(addv_prev) else None)
    slippage = value * bps / 1e4
    return commission, slippage, raw_shares, raw_price


class MarketCosts(bt.CommInfoBase):
    params = (
        ("stocklike", True),
        ("commtype", bt.CommInfoBase.COMM_FIXED),
        ("percabs", True),
        ("market", None),
        ("feed", None),
    )

    def _state(self):
        d = self.p.feed
        factor = float(d.split_factor[0])
        # ADDV known before the fill: the previous bar's 50-day average.
        addv_prev = float(d.addv50[-1]) if len(d) > 1 else float("nan")
        return factor, addv_prev

    def _getcommission(self, size, price, pseudoexec):
        factor, addv_prev = self._state()
        comm, slip, _, _ = cost_breakdown(self.p.market, size, price, factor, addv_prev)
        return comm + slip

    def breakdown(self, size, price):
        factor, addv_prev = self._state()
        return cost_breakdown(self.p.market, size, price, factor, addv_prev)
