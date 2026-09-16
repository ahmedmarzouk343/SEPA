"""
generate_quantstats_report.py -- Feature 4 deliverable: confirms the
QuantStats HTML reporting pipeline works end-to-end against a real
KashifStrategy/MinerviniSizer Cerebro run.

Separate from test_feature4_known_answer.py on purpose (per the approved
plan's Verification step 3): the known-answer fixtures are individually too
short/sparse to produce a meaningful equity curve or a non-degenerate
QuantStats report (some fixtures never even close a trade). This script
instead runs a longer synthetic multi-ticker series (150 bars x 3 tickers,
several real round-trips per ticker) and hands the resulting daily returns
to quantstats.reports.html().

--------------------------------------------------------------------------
SCOPE BOUNDARY (same one documented in kashif_strategy.py's module
docstring, restated here because it matters for how this script drives
entries)
--------------------------------------------------------------------------
entry_timing and catalyst_check (pipeline stages 5-6) are not built yet, so
KashifStrategy.next() cannot organically qualify a real buy signal end to
end. This script's ReportDemoStrategy subclass drives entries directly
(periodic buys while flat, gated only by real_regime/real guards that ARE
built -- no_averaging_down, the real MinerviniSizer, real stop-loss/
breakeven/largest-decline management), the same "call the real production
code, bypass only the pipeline stages that don't exist yet" approach the
known-answer fixtures use. This is a demonstration of the RISK/SIZING
machinery's reporting pipeline, not a claim that the full Kashif strategy
is backtestable end-to-end yet -- it isn't, until Features 5-6 exist.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import backtrader as bt  # noqa: E402
import quantstats as qs  # noqa: E402

from kashif_sizer import MinerviniSizer  # noqa: E402
from kashif_strategy import KashifStrategy  # noqa: E402

OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feature4_quantstats_report.html")


def make_synthetic_series(n_bars, seed, base_price=100.0):
    """
    A repeating rally/pullback cycle (not pure random walk) so several real
    round-trips actually occur within n_bars -- a flat random walk risks
    zero trades ever closing, which would produce a degenerate all-zero
    returns series and defeat the point of this script.
    """
    rng = np.random.default_rng(seed)
    prices = [base_price]
    cycle_len = 20
    for i in range(1, n_bars):
        phase = (i % cycle_len) / cycle_len
        drift = 0.015 * np.sin(2 * np.pi * phase)  # oscillating trend
        noise = rng.normal(0, 0.006)
        prices.append(max(prices[-1] * (1 + drift + noise), 1.0))
    closes = np.array(prices)
    opens = np.roll(closes, 1)
    opens[0] = closes[0]
    highs = np.maximum(opens, closes) * (1 + rng.uniform(0.001, 0.01, n_bars))
    lows = np.minimum(opens, closes) * (1 - rng.uniform(0.001, 0.01, n_bars))
    volumes = rng.integers(80000, 150000, n_bars).astype(float)
    dates = pd.date_range("2023-01-01", periods=n_bars, freq="B")
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes}, index=dates
    )


class ReportDemoStrategy(KashifStrategy):
    """
    Drives periodic entries directly (bypassing the unbuilt pipeline stages
    5-6 -- see module docstring's Scope Boundary), using the REAL
    MinerviniSizer for position sizing and the REAL KashifStrategy exit
    management (stop-loss, breakeven swap, largest-decline flag, no-
    averaging-down guard, streak/defensive/reentry bookkeeping) for
    everything else.
    """
    params = (("entry_check_every", 15), ("warmup_bars", 55))

    def __init__(self):
        super().__init__()
        self.since_last_entry_check = {}

    def next(self):
        for d in self.datas:
            self.history[d].append({
                "Open": d.open[0], "High": d.high[0], "Low": d.low[0],
                "Close": d.close[0], "Volume": d.volume[0],
            })

        bar = len(self)
        if bar < self.p.warmup_bars:
            return

        for d in self.datas:
            pos = self.broker.getposition(d)
            if pos.size > 0:
                self._manage_open_position(d)
                continue

            count = self.since_last_entry_check.get(d, 0) + 1
            self.since_last_entry_check[d] = count
            if count < self.p.entry_check_every:
                continue
            self.since_last_entry_check[d] = 0

            if not self._guard_no_averaging_down(d):
                continue
            size = self.getsizing(d, isbuy=True)
            if size > 0:
                self.buy(data=d, size=size, exectype=bt.Order.Market)


def main():
    cerebro = bt.Cerebro()
    n_bars = 150
    tickers = ["ORWE", "SWDY", "COMI"]  # illustrative EGX-style tickers, synthetic prices only
    for i, ticker in enumerate(tickers):
        df = make_synthetic_series(n_bars, seed=1000 + i)
        cerebro.adddata(bt.feeds.PandasData(dataname=df, name=ticker))

    cerebro.broker.setcash(100000)
    cerebro.broker.setcommission(commission=0.0005)  # a small, realistic commission this time
    cerebro.broker.set_coc(False)
    cerebro.addstrategy(ReportDemoStrategy)
    cerebro.addsizer(MinerviniSizer)
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="time_return", timeframe=bt.TimeFrame.Days)

    print(f"Starting equity: {cerebro.broker.getvalue():,.2f}")
    results = cerebro.run()
    strat = results[0]
    print(f"Ending equity:   {cerebro.broker.getvalue():,.2f}")

    closed_trades = len(strat.recent_closed_trades)
    print(f"Closed trades recorded (trailing window, up to 20): {closed_trades}")

    time_return = strat.analyzers.time_return.get_analysis()
    returns = pd.Series(time_return).sort_index()
    returns.index = pd.to_datetime(returns.index)
    print(f"Return series length: {len(returns)} trading days")
    print(f"Non-zero return days: {int((returns != 0).sum())}")

    if returns.empty or (returns == 0).all():
        print("ERROR: returns series is empty or entirely zero -- report would be degenerate. Aborting.")
        sys.exit(1)

    qs.reports.html(
        returns,
        output=OUTPUT_PATH,
        title="Kashif Feature 4 -- Risk Rules & Position Sizing (synthetic demo)",
    )
    print(f"QuantStats HTML report written to: {OUTPUT_PATH}")
    print(f"File exists: {os.path.exists(OUTPUT_PATH)}, size: {os.path.getsize(OUTPUT_PATH):,} bytes")


if __name__ == "__main__":
    main()
