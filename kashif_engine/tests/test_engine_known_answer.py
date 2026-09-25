"""Engine known-answer test on a synthetic market.

Every expected number below is computed by hand from the synthetic tape and
the published fee formulas -- never read back from the engine.

Tape (business days d0..d89, trading starts at d60):
  AAA  flat 50.00 (open 50.00, high 50.50, low 49.50, close 50.00), volume 200k;
       dividend 0.50 on d66; on d70 it gaps DOWN: open 40.00, low 39.00,
       close 41.00 (through a 10% stop at 45.00 -> must fill at the OPEN 40.00).
  BBB  split-adjusted flat 20.00 (high 20.40, low 19.60), volume 400k;
       2-for-1 split on d67 (raw price 40 before, 20 after);
       d75: open 19.90, low 17.00 -> 10% stop at 18.00 fills AT THE STOP (intrabar).
  SPY  calendar only.
Strategy stub: candidate AAA at d61 close, BBB at d63 close, $10,000 each,
stop = entry * 0.90.
"""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kashif_engine import engine  # noqa: E402
from kashif_engine.auditor import audit  # noqa: E402
from kashif_engine.data import prices as P  # noqa: E402
from kashif_engine.markets import US  # noqa: E402
from kashif_engine.strategies.base import StrategyModule  # noqa: E402

DAYS = pd.bdate_range("2023-01-02", periods=90)
START, END = DAYS[60], DAYS[-1]


def _frame(o, h, l, c, v, div=None, spl=None):
    f = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "AdjClose": c, "Volume": v,
                      "Dividends": 0.0, "Splits": 0.0}, index=DAYS)
    f.index.name = "Date"
    for d, x in (div or {}).items():
        f.loc[DAYS[d], "Dividends"] = x
    for d, x in (spl or {}).items():
        f.loc[DAYS[d], "Splits"] = x
    return f.astype(float)


@pytest.fixture()
def market_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "CACHE_DIR", tmp_path)
    (tmp_path / "US").mkdir()
    n = len(DAYS)
    a = _frame([50.0] * n, [50.5] * n, [49.5] * n, [50.0] * n, [200_000.0] * n, div={66: 0.50})
    a.iloc[70, :4] = [40.0, 41.5, 39.0, 41.0]
    b = _frame([20.0] * n, [20.4] * n, [19.6] * n, [20.0] * n, [400_000.0] * n, spl={67: 2.0})
    b.iloc[75, :4] = [19.9, 20.0, 17.0, 17.5]
    s = _frame([400.0] * n, [401.0] * n, [399.0] * n, [400.0] * n, [1e6] * n)
    for t, f in (("AAA", a), ("BBB", b), ("SPY", s)):
        f.to_parquet(tmp_path / "US" / f"{t}.parquet")
    return tmp_path


class Stub(StrategyModule):
    name = "stub"

    def __init__(self):
        super().__init__({}, {}, US)
        cols = {}
        for t in ("AAA", "BBB"):
            f = P.load(t, "US")
            cols.setdefault("sma_50", {})[t] = f["Close"].rolling(50).mean()
            cols.setdefault("avgvol50", {})[t] = f["Volume"].rolling(50).mean()
            cols.setdefault("atr14_pct", {})[t] = pd.Series(0.01, index=f.index)
            cols.setdefault("addv50", {})[t] = (f["Close"] * f["Volume"]).rolling(50).mean()
        self.panel = {k: pd.DataFrame(v) for k, v in cols.items()}
        self.plan = {DAYS[61].date(): "AAA", DAYS[63].date(): "BBB"}

    def tickers_needed(self):
        return ["AAA", "BBB"]

    def candidates(self, ctx, day):
        t = self.plan.get(day)
        return [{"ticker": t, "reason": "STUB"}] if t else []

    def allocate(self, ctx, cands):
        return [(c, 10_000.0) for c in cands]

    def on_entry_filled(self, ctx, t, st, bar):
        st["initial_stop_pct"] = 0.10
        return [("stop", st["entry_price"] * 0.90, "STOP_LOSS")]


def _costs(adj_q, adj_p, factor, addv):
    raw_q, raw_p = adj_q / factor, adj_p * factor
    comm = min(max(1.0, 0.005 * raw_q), 0.01 * raw_q * raw_p)
    value = adj_q * adj_p
    slip = value * (5.0 + 10.0 * math.sqrt((value / addv) / 0.01)) / 1e4
    return comm, slip


def test_engine_known_answer(market_dir, tmp_path):
    res = engine.run(Stub(), US, START, END, capital=100_000.0, out_dir=tmp_path / "run", log=lambda *a: None)
    fills = res.fills
    assert list(fills["side"]) == ["BUY", "BUY", "SELL", "SELL"]

    # AAA: signal d61 close 50.00 -> 200 shares, filled at d62 OPEN 50.00.
    a_buy = fills.iloc[0]
    assert (a_buy.ticker, a_buy.date, a_buy.shares, a_buy.price) == ("AAA", str(DAYS[62].date()), 200, 50.0)
    c, s = _costs(200, 50.0, 1.0, 50.0 * 200_000)
    assert a_buy.commission == pytest.approx(c, abs=1e-12) and a_buy.slippage == pytest.approx(s, abs=1e-12)

    # BBB: signal d63 close 20.00 -> 500 split-adjusted shares at d64 open 20.00.
    # Before the d67 2-for-1 split that is 250 RAW shares at 40.00.
    b_buy = fills.iloc[1]
    assert (b_buy.ticker, b_buy.shares, b_buy.price) == ("BBB", 500, 20.0)
    assert (b_buy.raw_shares, b_buy.raw_price) == (250.0, 40.0)
    c, s = _costs(500, 20.0, 2.0, 20.0 * 400_000)
    assert b_buy.commission == pytest.approx(c, abs=1e-12)        # $1.25 on 250 raw shares, not $2.50
    assert b_buy.slippage == pytest.approx(s, abs=1e-12)

    # AAA gaps through its 45.00 stop on d70: fill at the OPEN 40.00, not 45.00.
    a_sell = fills.iloc[2]
    assert (a_sell.ticker, a_sell.date, a_sell.price) == ("AAA", str(DAYS[70].date()), 40.0)
    # BBB trades through its 18.00 stop intrabar on d75 (open 19.90): fill AT 18.00.
    b_sell = fills.iloc[3]
    assert (b_sell.ticker, b_sell.date, b_sell.price) == ("BBB", str(DAYS[75].date()), pytest.approx(18.0))

    # Dividend: 200 AAA shares held at the d65 close, 0.50 ex d66.
    divs = pd.read_csv(res.out_dir / "dividends.csv")
    assert len(divs) == 1 and divs.iloc[0].amount == pytest.approx(100.0)

    # Hand-computed final equity: capital - buys - costs + sells + dividend.
    exp = 100_000.0 - 200 * 50 - 500 * 20 + 200 * 40 + 500 * 18.0 + 100.0 \
        - fills["commission"].sum() - fills["slippage"].sum()
    assert res.equity.iloc[-1] == pytest.approx(exp, abs=1e-6)

    # Per-trade P&L and exit reasons.
    tr = res.trades
    assert list(tr["exit_reason"]) == ["STOP_LOSS", "STOP_LOSS"]
    assert tr.iloc[0]["gross_pnl"] == pytest.approx(200 * (40 - 50))

    # Settlement: every pending amount settled, trial balance zero, ledger == broker.
    assert res.ledger["receivable"] == pytest.approx(0) and res.ledger["payable"] == pytest.approx(0)

    # Independent auditor agrees exactly.
    rep = audit(res.out_dir, US)
    assert rep["passed"], rep["problems"]
    assert rep["cash_exact_match"] and rep["equity_exact_match"] and rep["per_trade_match"]


class StubCCC(Stub):
    def __init__(self):
        super().__init__()
        f = P.load("CCC", "US")
        for k, fn in (("sma_50", lambda x: x["Close"].rolling(50).mean()),
                      ("avgvol50", lambda x: x["Volume"].rolling(50).mean()),
                      ("atr14_pct", lambda x: pd.Series(0.01, index=x.index)),
                      ("addv50", lambda x: (x["Close"] * x["Volume"]).rolling(50).mean())):
            self.panel[k]["CCC"] = fn(f)
        self.plan = {DAYS[61].date(): "CCC"}

    def tickers_needed(self):
        return ["CCC"]


def test_stop_never_fills_on_a_day_the_stock_has_no_bar(market_dir, tmp_path):
    """Review finding: stock backtrader re-tests a stop against the PREVIOUS bar
    when the feed skips a day. CCC is bought at the d62 open (30.00) with a stop
    at 27.00; the d62 bar itself trades down to 26.00, and d63 is missing. The stop
    is live from d63: testing it against the stale d62 bar would 'fill' on a day
    CCC did not trade. From d64 CCC trades at 30 +/- 0.30, so no sale is correct."""
    n = len(DAYS)
    c = _frame([30.0] * n, [30.3] * n, [29.7] * n, [30.0] * n, [300_000.0] * n)
    c.iloc[62, 2] = 26.0
    c = c.drop(DAYS[63])
    c.to_parquet(market_dir / "US" / "CCC.parquet")
    res = engine.run(StubCCC(), US, START, END, out_dir=tmp_path / "ccc", log=lambda *a: None)
    assert list(res.fills["side"]) == ["BUY"]
    assert res.fills.iloc[0]["date"] == str(DAYS[62].date())
    rep = audit(res.out_dir, US)
    assert rep["passed"], rep["problems"]


def test_settlement_is_t_plus_one(market_dir, tmp_path):
    from kashif_engine.ledger import Ledger
    L = Ledger(capital=1000.0, settlement_days=1)
    L.buy("d0", 0, "X", 10, 50.0, 1.0, 0.5, 10, 50.0, "t")
    assert float(L.balances["cash"]) == 1000.0 and float(L.balances["payable"]) == pytest.approx(-501.5)
    L.settle(0, "d0")
    assert float(L.balances["cash"]) == 1000.0            # not yet
    L.settle(1, "d1")
    assert float(L.balances["cash"]) == pytest.approx(498.5)
    L.sell("d1", 1, "X", 10, 60.0, 1.0, 0.5, 10, 60.0, "t")
    L.settle(1, "d1")
    assert float(L.balances["cash"]) == pytest.approx(498.5)
    L.settle(2, "d2")
    assert float(L.balances["cash"]) == pytest.approx(498.5 + 598.5)
    assert L.trial_balance_ok()
    assert float(L.balances["realized_pnl"]) == pytest.approx(-100.0)   # credit balance = +100 gain


def test_kill_switch_blocks_entries(market_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("KASHIF_KILL_SWITCH", "1")
    res = engine.run(Stub(), US, START, END, capital=100_000.0, out_dir=tmp_path / "ks", log=lambda *a: None)
    assert len(res.fills) == 0
    ev = pd.read_csv(res.out_dir / "events.csv")
    assert (ev["event"] == "KILL_SWITCH").sum() == len(res.equity)
