"""
Known-answer regression test for P19 fix: RS percentile computed per-bar
cross-sectionally, not broadcast from today's snapshot.

Proves that the same ticker (A) gets DIFFERENT RS percentile values on
different bars — impossible under the old broadcast bug, which gave every
bar the same value.

FIXTURE DESIGN: 3 tickers with diverging price paths engineered so the
cross-sectional 252-day-return ranking flips mid-run:
  - Ticker A: rises 0→130 bars, then flat → 252-day return starts high,
    then drops once the rise exits the trailing window.
  - Ticker B: flat for 200 bars, then rises → 252-day return starts low,
    then climbs.
  - Ticker C: always flat → 252-day return always 0 (anchor).

At bar 253 (first evaluable): A > B > C → A=100%, B=66.7%, C=33.3%.
At bar 268: B's late rise outpaces A's stale early rise in the 252-day
window → B > A > C → A drops to 66.7%.

PREDICTED (captured from probe run):
  - Ticker A RS at bar 253 = 100.0
  - Ticker A RS at bar 268 = 66.67 (rank flip — B overtook A)
  - bar 253 != bar 268 for the SAME ticker → P19 fix confirmed
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
import backtrader as bt
from kashif_strategy import KashifStrategy
from kashif_sizer import MinerviniSizer

N_BARS = 310


class P19ProbeStrategy(KashifStrategy):
    def __init__(self):
        super().__init__()
        self.rs_by_bar = {}

    def next(self):
        super().next()
        bar = len(self)
        today = self.datas[0].datetime.date(0)
        snapshot = self._rs_percentile_history.get(today, {})
        if snapshot:
            self.rs_by_bar[bar] = dict(snapshot)


def make_df(prices, dates):
    return pd.DataFrame({
        "open": prices, "high": [p * 1.01 for p in prices],
        "low": [p * 0.99 for p in prices], "close": prices,
        "volume": [100000] * len(prices),
    }, index=dates)


def main():
    failures = []

    def check(label, predicted, actual, tol=1e-2):
        if isinstance(predicted, bool):
            ok = predicted == actual
        elif isinstance(predicted, (int, float)):
            ok = abs(predicted - actual) < tol
        else:
            ok = predicted == actual
        status = "OK" if ok else "MISMATCH"
        print(f"  [{status}] {label}: predicted={predicted!r} actual={actual!r}")
        if not ok:
            failures.append(f"{label}: predicted {predicted!r}, got {actual!r}")

    print("=" * 70)
    print("P19 FIXTURE -- RS percentile varies per-bar (not broadcast)")
    print("=" * 70)

    dates = pd.date_range("2022-01-01", periods=N_BARS, freq="D")

    prices_a = []
    for i in range(N_BARS):
        if i < 130:
            prices_a.append(100 + i * 0.5)
        else:
            prices_a.append(165)

    prices_b = []
    for i in range(N_BARS):
        if i < 200:
            prices_b.append(100)
        else:
            prices_b.append(100 + (i - 200) * 0.8)

    prices_c = [100] * N_BARS

    cerebro = bt.Cerebro()
    cerebro.adddata(bt.feeds.PandasData(dataname=make_df(prices_a, dates), name="A"))
    cerebro.adddata(bt.feeds.PandasData(dataname=make_df(prices_b, dates), name="B"))
    cerebro.adddata(bt.feeds.PandasData(dataname=make_df(prices_c, dates), name="C"))
    cerebro.addstrategy(P19ProbeStrategy, target_position_count=4)
    cerebro.addsizer(MinerviniSizer)
    cerebro.broker.setcash(1_000_000)

    results = cerebro.run()
    strat = results[0]

    bar_nums = sorted(strat.rs_by_bar.keys())

    rs_a_253 = strat.rs_by_bar.get(253, {}).get("A")
    rs_a_268 = strat.rs_by_bar.get(268, {}).get("A")

    check("RS data exists at bar 253", True, 253 in strat.rs_by_bar)
    check("RS data exists at bar 268", True, 268 in strat.rs_by_bar)
    check("Ticker A RS at bar 253 (top rank)", 100.0, rs_a_253)
    check("Ticker A RS at bar 268 (rank dropped after B overtook)", 66.67, rs_a_268)
    check("DIFFERENT RS for same ticker on different bars (P19 fix proof)",
          True, rs_a_253 != rs_a_268)

    print()
    print("=" * 70)
    if failures:
        print(f"RESULT: MISMATCH -- {len(failures)} prediction(s) violated:")
        for f in failures:
            print(f"  - {f}")
    else:
        print("RESULT: MATCH -- every prediction confirmed exactly by the real code.")
    print("=" * 70)
    return len(failures) == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
