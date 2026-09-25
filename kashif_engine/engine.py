"""Strategy-agnostic backtest engine on backtrader. Virtual money only.

The engine owns everything that is the same for every strategy: feeds,
costs, fills, settlement, the ledger, reconciliation, dividends, the kill
switch, the trade list and the equity curve. A strategy module (see
strategies/base.py) owns every trading decision and is loaded from its JSON
config's strategy_id, so a new strategy is a config + a module.

Execution model (documented, not implied):
  * decisions are made at the close of day t from data <= t;
  * entries are market orders filled at the OPEN of t+1;
  * stops are broker stop orders: filled at the stop price intrabar, or at
    the OPEN when the bar gaps through the stop (never at the stop price);
  * a stop placed after an entry fill is live from the following bar;
  * slippage and commission are costs booked by costs.MarketCosts.
"""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd

from kashif_engine.costs import MarketCosts
from kashif_engine.ledger import Ledger, LedgerDrift
from kashif_engine.killswitch import KillSwitch

ROOT = Path(__file__).resolve().parents[1]
SUSPECT_MOVE = 0.75          # |close/prev_close - 1| above this with no split = suspect bar
STALE_FEED_DAYS = 10         # a held feed dark this long gets an exit queued for its next real bar


class ClockBroker(bt.brokers.BackBroker):
    """BackBroker that never executes an order on a day its own data has no bar.

    Stock backtrader re-tests stop orders against a feed's PREVIOUS bar when the
    feed skips a day (halt, gap in the tape) and fills them on the clock day --
    a fill on a day the stock did not trade. Market orders already wait for a
    new bar. Found in a read-only review; covered by test_engine_known_answer.
    """
    clock = None

    def _try_exec(self, order):
        if self.clock is not None and len(order.data) and \
                order.data.datetime.date(0) != self.clock.datetime.date(0):
            return
        return super()._try_exec(order)


class PanelFeed(bt.feeds.PandasData):
    lines = ("split_factor", "addv50", "sma50", "avgvol50", "atr14_pct", "dividend", "suspect")
    params = (
        ("datetime", None), ("open", "Open"), ("high", "High"), ("low", "Low"),
        ("close", "Close"), ("volume", "Volume"), ("openinterest", None),
        ("split_factor", "SplitFactor"), ("addv50", "addv50"), ("sma50", "sma_50"),
        ("avgvol50", "avgvol50"), ("atr14_pct", "atr14_pct"), ("dividend", "Dividends"),
        ("suspect", "suspect"),
    )


class ArrayFeed(bt.feed.DataBase):
    """PanelFeed's twin that loads from numpy arrays.

    backtrader's PandasData reads every cell with DataFrame.iloc, which took
    ~70% of a run's wall time (profiled: 39 s of 54 s). Same columns, same
    float values and the same date2num timestamps, so fills are identical --
    verified against experiment 1's published trade list.
    """
    lines = ("split_factor", "addv50", "sma50", "avgvol50", "atr14_pct", "dividend", "suspect")
    params = (("frame", None),)
    COLS = (("open", "Open"), ("high", "High"), ("low", "Low"), ("close", "Close"), ("volume", "Volume"),
            ("split_factor", "SplitFactor"), ("addv50", "addv50"), ("sma50", "sma_50"),
            ("avgvol50", "avgvol50"), ("atr14_pct", "atr14_pct"), ("dividend", "Dividends"),
            ("suspect", "suspect"))

    def start(self):
        super().start()
        f = self.p.frame
        self._dt = [bt.date2num(ts.to_pydatetime()) for ts in f.index]
        self._arr = [(getattr(self.lines, line), f[col].to_numpy(dtype=float)) for line, col in self.COLS]
        self._i = 0

    def _load(self):
        i = self._i
        if i >= len(self._dt):
            return False
        self.lines.datetime[0] = self._dt[i]
        for line, arr in self._arr:
            line[0] = arr[i]
        self._i = i + 1
        return True


def build_feed_frame(ticker, prices_df, panel, start, end):
    """Split-adjusted OHLCV + trailing panel columns for one ticker, [start, end]."""
    f = prices_df.loc[:end].copy()
    for col in ("sma_50", "avgvol50", "atr14_pct", "addv50"):
        f[col] = panel[col][ticker].reindex(f.index)
    ret = f["Close"] / f["Close"].shift(1) - 1
    split_today = f["Splits"] > 0
    f["suspect"] = ((ret.abs() > SUSPECT_MOVE) & ~split_today) | (f["Volume"] <= 0) \
        | f[["Open", "High", "Low", "Close"]].isna().any(axis=1)
    f["suspect"] = f["suspect"].astype(float)
    f = f.loc[start:end]
    f = f.dropna(subset=["Open", "High", "Low", "Close"])
    return f


@dataclass
class RunResult:
    run_id: str
    out_dir: Path
    equity: pd.Series
    trades: pd.DataFrame
    fills: pd.DataFrame
    ledger: dict
    stats: dict = field(default_factory=dict)


class EngineStrategy(bt.Strategy):
    params = (("module", None), ("market", None), ("ledger", None), ("killswitch", None),
              ("calendar", None), ("reconcile_every_trade", True))

    def __init__(self):
        self.m = self.p.module
        self.ledger: Ledger = self.p.ledger
        self.ks: KillSwitch = self.p.killswitch
        self.clock = self.datas[0]
        self.by_name = {d._name: d for d in self.datas[1:]}
        self.cal_index = {d: i for i, d in enumerate(self.p.calendar)}
        self.pos = {}                  # ticker -> position state dict (strategy-owned fields)
        self.pending_buy = {}          # ticker -> (order, candidate)
        self.pending_exit = {}         # ticker -> reason
        self.closed = []               # closed trade records
        self.equity_rows = []
        self.cash_in_flight = 0.0      # dividends queued via add_cash, not yet applied
        self.prev_size = {}
        self.events = []
        self.day = None
        self.need_reconcile = False
        self.n_reconciles = 0

    # ---------------------------------------------------------------- helpers
    def has_bar(self, d):
        return len(d) > 0 and d.datetime.date(0) == self.day

    def marks(self):
        return {t: self.by_name[t].close[0] for t in self.ledger.lots}

    def reconcile(self, why):
        self.n_reconciles += 1
        try:
            self.ledger.reconcile(_CashShim(self.broker, self.cash_in_flight), self.by_name,
                                  self.marks(), f"{self.day} {why}")
        except LedgerDrift as e:
            self.ks.trip(f"ledger drift: {e}")
            raise

    def prenext(self):
        self.next()

    # ---------------------------------------------------------------- per bar
    def next(self):
        self.day = self.clock.datetime.date(0)
        di = self.cal_index[self.day]
        self.cash_in_flight = 0.0      # broker applied last bar's additions in _get_value
        self.ledger.settle(di, self.day)
        if self.need_reconcile:       # every fill of this bar has been posted by now
            self.reconcile("after fills")
            self.need_reconcile = False

        # Dividends: entitled shares are those held at the PREVIOUS close.
        for t, prev in self.prev_size.items():
            d = self.by_name[t]
            if prev > 0 and self.has_bar(d) and d.dividend[0] > 0 and not math.isnan(d.dividend[0]):
                amt = prev * float(d.dividend[0])
                self.ledger.dividend(self.day, t, prev, float(d.dividend[0]))
                self.broker.add_cash(amt)
                self.cash_in_flight += amt

        # A market buy waits for its stock's next bar; if the feed stays dark
        # past the stale limit (delisting, long halt) the order is cancelled.
        for t, (o, c) in list(self.pending_buy.items()):
            if di - c.get("submitted_index", di) > STALE_FEED_DAYS and o.alive():
                self.cancel(o)

        halted, why = self.ks.check(self.day)

        # Held positions: stale feeds, then strategy exit management.
        ctx = self.context()
        for t in list(self.pos):
            d = self.by_name[t]
            if self.broker.getposition(d).size <= 0 or t in self.pending_exit:
                continue
            if not self.has_bar(d):
                last = d.datetime.date(0) if len(d) else None
                if last and (self.cal_index.get(self.day, 0) - self.cal_index.get(last, 0)) > STALE_FEED_DAYS:
                    # Cannot trade a stock that is not trading: the exit waits for its next
                    # real bar (ClockBroker). If the feed never returns, the position stays
                    # marked at its last close and the event is reported, never faked.
                    self.events.append({"date": str(self.day), "ticker": t, "event": "FEED_DARK_EXIT_QUEUED",
                                        "last_bar": str(last)})
                    self.exit(t, "STALE_FEED_EXIT")
                continue
            st = self.pos[t]
            if st["entry_index"] == di:
                continue    # its stop was placed this bar; backtrader cannot cancel it until next bar
            if d.suspect[0]:
                self.events.append({"date": str(self.day), "ticker": t, "event": "SUSPECT_BAR_HELD",
                                    "close": d.close[0]})
                continue
            st["bars_held"] = di - st["entry_index"]
            acts = self.m.manage(ctx, t, st, _Bar(d))
            if len(acts) > 1:
                raise RuntimeError(f"{t}: strategy returned {len(acts)} actions; one per bar allowed")
            for act in acts:
                self.apply(t, act)

        # New entries.
        if halted:
            self.events.append({"date": str(self.day), "event": "KILL_SWITCH", "reason": why})
        else:
            cands = self.m.candidates(ctx, self.day)
            fillable = []
            for c in cands:
                d = self.by_name.get(c["ticker"])
                if d is None or not self.has_bar(d) or d.suspect[0]:
                    c["decision"] = "NO_BAR_OR_SUSPECT"
                    continue
                if c["ticker"] in self.pos or c["ticker"] in self.pending_buy:
                    c["decision"] = "ALREADY_HELD"
                    continue
                fillable.append(c)
            for c, value in self.m.allocate(ctx, fillable):
                d = self.by_name[c["ticker"]]
                size = math.floor(value / d.close[0]) if d.close[0] > 0 else 0
                if size <= 0:
                    c["decision"] = "SIZE_ZERO"
                    continue
                o = self.buy(data=d, size=size, exectype=bt.Order.Market)
                c["submitted_index"] = di
                self.pending_buy[c["ticker"]] = (o, c)
                c["decision"] = "ORDER_SUBMITTED"
                c["order_value"] = size * d.close[0]
            self.m.record_candidates(self.day, cands)

        self.prev_size = {t: self.broker.getposition(self.by_name[t]).size for t in self.pos
                          if self.broker.getposition(self.by_name[t]).size > 0}
        self.equity_rows.append((self.day, self.broker.getvalue() + self.cash_in_flight,
                                 self.broker.getcash() + self.cash_in_flight,
                                 len(self.prev_size)))

    def context(self):
        return _Ctx(self)

    # ---------------------------------------------------------------- actions
    def apply(self, t, act):
        kind = act[0]
        d = self.by_name[t]
        st = self.pos[t]
        if kind == "exit":
            self.exit(t, act[1])
        elif kind == "stop":
            new_price, label = act[1], act[2]
            old = st.get("stop_order")
            if old is not None and old.alive():
                self.cancel(old)
            st["stop_order"] = self.sell(data=d, size=self.broker.getposition(d).size,
                                         exectype=bt.Order.Stop, price=new_price)
            st["stop_price"], st["stop_type"] = new_price, label
        else:
            raise ValueError(f"unknown action {act!r}")

    def exit(self, t, reason):
        d = self.by_name[t]
        st = self.pos[t]
        for k in ("stop_order", "target_order"):
            o = st.get(k)
            if o is not None and o.alive():
                self.cancel(o)
        self.pending_exit[t] = reason
        self.sell(data=d, size=self.broker.getposition(d).size, exectype=bt.Order.Market)

    # ---------------------------------------------------------------- fills
    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        # backtrader delivers notifications BEFORE next() for the bar the
        # order executed on, so self.day still holds the previous bar here.
        self.day = self.clock.datetime.date(0)
        d = order.data
        t = d._name
        if order.status in (order.Canceled, order.Margin, order.Rejected, order.Expired):
            if order.isbuy() and t in self.pending_buy and self.pending_buy[t][0].ref == order.ref:
                _, c = self.pending_buy.pop(t)
                self.events.append({"date": str(self.day), "ticker": t, "event": f"BUY_{order.getstatusname()}"})
                self.m.on_entry_failed(t, c, order.getstatusname())
            return
        if order.status != order.Completed:
            return
        ci = self.broker.getcommissioninfo(d)
        size, price = order.executed.size, order.executed.price
        comm, slip, raw_q, raw_p = ci.breakdown(size, price)
        if abs((comm + slip) - order.executed.comm) > 1e-6:
            self.ks.trip(f"cost mismatch {t}: {comm + slip} vs {order.executed.comm}")
            raise LedgerDrift(f"cost breakdown {comm + slip} != broker {order.executed.comm}")
        di = self.cal_index[self.day]
        if order.isbuy():
            _, c = self.pending_buy.pop(t, (None, {}))
            self.ledger.buy(self.day, di, t, size, price, comm, slip, raw_q, raw_p, c.get("reason", "ENTRY"))
            st = {"entry_price": price, "entry_date": self.day, "entry_index": di, "shares": size,
                  "candidate": c, "entry_comm": comm + slip, "highest_close": d.close[0]}
            self.pos[t] = st
            for act in self.m.on_entry_filled(self.context(), t, st, _Bar(d)):
                self.apply(t, act)
        else:
            q = -size
            st = self.pos.get(t, {})
            # backtrader notifies with CLONES of orders: compare refs, never identity.
            if _same(order, st.get("stop_order")):
                reason = st.get("stop_type", "STOP")
            elif _same(order, st.get("target_order")):
                reason = st.get("target_type", "TARGET")
            else:
                reason = self.pending_exit.get(t, "EXIT")
            level = st.get("stop_price") if _same(order, st.get("stop_order")) else None
            self.ledger.sell(self.day, di, t, q, price, comm, slip, raw_q, raw_p, reason, order_level=level)
            if self.broker.getposition(d).size < 0:
                self.ks.trip(f"short position opened in {t}")
                raise LedgerDrift(f"{t}: sell left a SHORT position -- long-only violated")
            for k in ("stop_order", "target_order"):
                o = st.get(k)
                if o is not None and not _same(o, order) and o.alive():
                    self.cancel(o)
            rec = {
                "ticker": t, "entry_date": str(st["entry_date"]), "exit_date": str(self.day),
                "entry_price": st["entry_price"], "exit_price": price, "shares": q,
                "gross_pnl": (price - st["entry_price"]) * q,
                "costs": st["entry_comm"] + comm + slip,
                "exit_reason": reason, "stop_type": st.get("stop_type"),
                "initial_stop_pct": st.get("initial_stop_pct"),
                "max_gain_pct": st.get("highest_close", price) / st["entry_price"] - 1,
                "bars_held": di - st["entry_index"],
                "entry_regime": st["candidate"].get("regime_state"),
                "rank_score": st["candidate"].get("rank_score"),
                "catalyst": st["candidate"].get("catalyst"),
                **{f"tag_{k}": v for k, v in st.get("tags", {}).items()},
            }
            rec["net_pnl"] = rec["gross_pnl"] - rec["costs"]
            rec["return_pct"] = rec["net_pnl"] / (st["entry_price"] * q)
            self.closed.append(rec)
            self.pos.pop(t, None)
            self.pending_exit.pop(t, None)
            self.m.on_trade_closed(rec)
        if self.p.reconcile_every_trade:
            self.need_reconcile = True


def _same(a, b):
    return a is not None and b is not None and a.ref == b.ref


class _CashShim:
    """Broker view with dividends that add_cash() has queued but not applied."""

    def __init__(self, broker, in_flight):
        self.b, self.f = broker, in_flight

    def getcash(self):
        return self.b.getcash() + self.f

    def getvalue(self):
        return self.b.getvalue() + self.f

    def getposition(self, d):
        return self.b.getposition(d)


class _Bar:
    """Read-only view of today's bar for a strategy module."""
    __slots__ = ("open", "high", "low", "close", "volume", "sma50", "avgvol50", "atr14_pct", "date")

    def __init__(self, d):
        self.open, self.high, self.low, self.close = d.open[0], d.high[0], d.low[0], d.close[0]
        self.volume, self.sma50, self.avgvol50 = d.volume[0], d.sma50[0], d.avgvol50[0]
        self.atr14_pct = d.atr14_pct[0]
        self.date = d.datetime.date(0)


class _Ctx:
    """What a strategy module may see: portfolio state at the close of `day`."""

    def __init__(self, s: EngineStrategy):
        self.day = s.day
        self.equity = s.broker.getvalue() + s.cash_in_flight
        self.cash = s.broker.getcash() + s.cash_in_flight
        self.pending_buy_value = sum(o.created.price * o.created.size for o, _ in s.pending_buy.values())
        self.n_open = len(s.pos) + len(s.pending_buy)
        self.open_tickers = set(s.pos) | set(s.pending_buy)
        self.addv = {t: d.addv50[0] for t, d in s.by_name.items() if s.has_bar(d)}


def run(module, market, start, end, capital=100_000.0, out_dir=None, run_id=None,
        reconcile_every_trade=True, log=print) -> RunResult:
    """Run one backtest. `module` is an already-prepared strategy module."""
    from kashif_engine.data import prices as P
    t0 = time.time()
    run_id = run_id or f"{module.name}_{int(time.time())}"
    out_dir = Path(out_dir or ROOT / "kashif_data" / "runs" / run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    start, end = pd.Timestamp(start), pd.Timestamp(end)

    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=True)
    cerebro.broker = ClockBroker()
    cerebro.broker.setcash(capital)
    cerebro.broker.set_checksubmit(True)
    cerebro.broker.set_coc(False)

    clock_df = P.load(market.benchmarks[-1] if market.benchmarks else module.tickers_needed()[0], market.name)
    clock_df = clock_df.loc[start:end]
    calendar = [d.date() for d in clock_df.index]
    clock_feed = clock_df[["Open", "High", "Low", "Close", "Volume"]].copy()
    for c in ("SplitFactor", "addv50", "sma_50", "avgvol50", "atr14_pct", "Dividends", "suspect"):
        clock_feed[c] = 0.0
    clock_feed["SplitFactor"] = 1.0
    clock_data = ArrayFeed(frame=clock_feed)
    cerebro.adddata(clock_data, name="__CLOCK__")
    cerebro.broker.clock = clock_data

    panel = module.panel
    n_feeds = 0
    for t in module.tickers_needed():
        pdf = P.load(t, market.name)
        if pdf is None:
            continue
        fs = module.feed_start(t)
        f = build_feed_frame(t, pdf, panel, max(start, pd.Timestamp(fs)) if fs is not None else start, end)
        if f.empty:
            continue
        data = ArrayFeed(frame=f)
        cerebro.adddata(data, name=t)
        cerebro.broker.addcommissioninfo(MarketCosts(market=market, feed=data), name=t)
        n_feeds += 1

    ledger = Ledger(capital=capital, settlement_days=market.settlement_days)
    ks = KillSwitch(run_id=run_id)
    cerebro.addstrategy(EngineStrategy, module=module, market=market, ledger=ledger, killswitch=ks,
                        calendar=calendar, reconcile_every_trade=reconcile_every_trade)
    log(f"[{run_id}] {n_feeds} feeds, {calendar[0]}..{calendar[-1]}, capital {capital:,.0f}")
    strat = cerebro.run()[0]

    # Final reconciliation on the last bar's marks.
    strat.reconcile("final")
    strat.need_reconcile = False
    eq = pd.DataFrame(strat.equity_rows, columns=["date", "equity", "cash", "n_positions"]).set_index("date")
    eq.index = pd.to_datetime(eq.index)
    trades = pd.DataFrame(strat.closed)
    fills = pd.DataFrame(ledger.fills)
    open_pos = [{"ticker": t, "shares": float(lot.shares), "cost": float(lot.cost),
                 "last_close": strat.by_name[t].close[0], "last_date": str(strat.by_name[t].datetime.date(0))}
                for t, lot in ledger.lots.items()]
    res = RunResult(run_id, out_dir, eq["equity"], trades, fills, ledger.summary())
    # Persist everything the auditor and the report need.
    eq.to_csv(out_dir / "equity.csv")
    trades.to_csv(out_dir / "trades.csv", index=False)
    fills.to_csv(out_dir / "fills.csv", index=False)
    pd.DataFrame(ledger.dividends_log).to_csv(out_dir / "dividends.csv", index=False)
    pd.DataFrame(strat.events).to_csv(out_dir / "events.csv", index=False)
    json.dump({"run_id": run_id, "capital": capital, "start": str(calendar[0]), "end": str(calendar[-1]),
               "ledger_balances": ledger.summary(), "open_positions": open_pos,
               "final_equity_broker": strat.broker.getvalue(),
               "final_equity_ledger": float(ledger.equity(strat.marks())),
               "kill_switch": ks.state(), "params": module.params_dict(),
               "n_feeds": n_feeds, "n_reconciliations": strat.n_reconciles,
               "seconds": round(time.time() - t0, 1)},
              open(out_dir / "run.json", "w"), indent=2, default=str)
    with open(out_dir / "journal.jsonl", "w") as fh:
        for j in ledger.journal:
            fh.write(json.dumps(j) + "\n")
    module.write_receipts(out_dir)
    log(f"[{run_id}] done in {time.time() - t0:.0f}s: {len(trades)} closed trades, "
        f"final equity {strat.broker.getvalue():,.2f}")
    return res
