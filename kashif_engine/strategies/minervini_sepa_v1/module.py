"""Minervini SEPA v1 as a pluggable strategy module.

Source of truth: minervini_sepa_v1_strategy_config.json (v0.28.1-draft) and
MANIFESTO.md. Book numbers are read from the config; the handful of
calibration constants that live only in kashif_strategy.py (approved
deviations: trailing give-back 15%, 50-day-MA buffer 5%, distribution-bar
arming after 10 bars with a 1.5x ATR floor, pivot stop 3% under the pivot
floored at 4%) are carried over with their provenance.

Pipeline per day (config pipeline_order):
  market_regime_gate -> hard_filter (Trend Template, RS across the full
  universe) -> fundamentals_screen (4 questions, point-in-time) ->
  catalyst_check (ranking input only, NEVER a gate) -> entry_timing (VCP +
  pivot breakout on volume) -> position_sizing -> risk_rules.

Deliberate differences from kashif_strategy.py, each a bug fix against the
config, not a new rule (listed again in FINAL_BACKTEST_REPORT.md):
  * fundamentals GATE entry (kashif_strategy only logged them, "Phase A");
  * a STRONG_NEGATIVE catalyst no longer blocks entry (config: never a gate);
  * breakeven at 3x the initial stop distance (config), not 4x;
  * defensive mode applies all three config adjustments (6% stop cap, 11%
    profit target, 0.5x size), not only the size multiplier;
  * the reentry-from-cash pilot is actually switched on (it was never set);
  * the losing streak counts losing trades (a profitable trailing-stop exit
    used to count as a "stop" and step size DOWN).
"""
from __future__ import annotations

import json
import math
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd

from kashif_engine import panel as PANEL
from kashif_engine.strategies.base import StrategyModule
from kashif_engine.strategies.minervini_sepa_v1 import signals as SIG

# Calibration constants carried from kashif_strategy.py (see module docstring).
PIVOT_STOP_BUFFER = 0.97
STOP_DISTANCE_MIN = 0.04
TRAIL_GIVEBACK = 0.15
TRAIL_SMA_BUFFER = 0.05
DIST_MIN_BARS = 10
DIST_ATR_MULT = 1.5
DEFENSIVE_MIN_TRADES = 10          # kashif_strategy guard, config known_gaps v0.18
CASH_HEADROOM = 0.98               # leave room for a gap-up open and costs

# The loosest value of each tunable that changes WHICH ticker-days are candidates.
GRID_LOOSEST = {"rs_threshold": 70, "breakout_volume": 1.2}


class Strategy(StrategyModule):
    name = "minervini_sepa_v1"

    def __init__(self, config, params, market):
        super().__init__(config, params, market)
        rr = config["risk_rules"]
        ps = config["position_sizing"]
        dm = rr["defensive_mode"]
        self.p = {
            "rs_threshold": 70,                                   # tt_9 (config)
            "breakout_volume": 1.4,                               # FIX 11 (config)
            "stop_max_pct": rr["stop_loss"]["hard_max_pct"],      # 0.10, hard ceiling
            "max_positions": ps["concurrent_positions"]["min_account"],   # 6
            "breakeven_mult": 3.0,                                # profit_protection.breakeven_trigger
            "defensive_stop_pct": dm["adjustments"]["stop_loss_pct"],
            "defensive_target_pct": dm["adjustments"]["profit_target_pct"],
            "defensive_size": dm["adjustments"]["position_size_multiplier"],
            "defensive_window": 20,
            "defensive_ratio_trigger": 1.5, "defensive_rate_trigger": 0.40,
            "defensive_ratio_revert": 2.0, "defensive_rate_revert": 0.50,
            "streak_steps": [1.0, 0.40, 0.20],                    # FIX 9
            "streak_triggers": [(3, 1), (5, 2)],
            "reentry_pilot": 0.50,                                # FIX 10
            "pilot_wins_to_graduate": 2,
            "liquidity_cap": market.liquidity_cap_pct_addv,
            "use_catalyst": False,
            "catalyst_weight": 0.5,
            "catalyst_path": None,
        }
        unknown = set(params) - set(self.p)
        if unknown:
            raise KeyError(f"unknown strategy params: {sorted(unknown)}")
        self.p.update(params)
        if not (0.0 < self.p["stop_max_pct"] <= rr["stop_loss"]["hard_max_pct"]):
            raise ValueError("stop_max_pct may be tightened, never widened past the 10% hard max")
        if self.p["rs_threshold"] < GRID_LOOSEST["rs_threshold"] or \
                self.p["breakout_volume"] < GRID_LOOSEST["breakout_volume"]:
            raise ValueError("parameter looser than the precomputed signal grid")
        # State
        self.streak_idx = 0
        self.defensive = False
        self.reentry = True            # the account starts in cash
        self.pilot_wins = 0
        self.recent = deque(maxlen=self.p["defensive_window"])
        self.n_open = 0
        self.cand_log = []
        self.state_log = []

    def params_dict(self):
        return {k: v for k, v in self.p.items() if k != "catalyst_path"} | \
               {"catalyst_path": str(self.p["catalyst_path"]) if self.p["catalyst_path"] else None}

    # ------------------------------------------------------------------ data
    def prepare(self, universe, start, end, log=print, workers=8):
        self.panel = PANEL.load(self.market.name)
        w = self.panel
        start, end = pd.Timestamp(start), pd.Timestamp(end)
        days = w["Close"].loc[start:end].index
        tickers = [t for t in universe if t in w["Close"].columns]
        self.universe = tickers
        self.days = days
        fund = SIG.fundamentals_panel(tickers, days, self.market, workers=workers, log=log)
        self.fund_long = fund
        fv = fund.pivot(index="date", columns="ticker", values="fund_verdict").reindex(days)
        self.fund_wide = fv

        reg = w["regime"].loc[days, "gate_open"].astype(bool)
        tt = w["tt_core"].loc[days, tickers].fillna(False).astype(bool)
        rs = w["rs_pct"].loc[days, tickers]
        vr = w["vol_ratio"].loc[days, tickers]
        pre = tt & (rs >= GRID_LOOSEST["rs_threshold"]) & (vr >= GRID_LOOSEST["breakout_volume"]) \
            & (fv[tickers] == "PASS")
        pre = pre & reg.values[:, None]
        pre_long = pre.stack()
        pre_long = pre_long[pre_long].reset_index()
        pre_long.columns = ["date", "ticker", "_"]
        log(f"  pre-filtered ticker-days for VCP: {len(pre_long)}")
        vcp = SIG.vcp_table(pre_long[["ticker", "date"]], GRID_LOOSEST["breakout_volume"],
                            workers=workers, log=log)
        vcp["rs_pct"] = [rs.at[d, t] for d, t in zip(vcp["date"], vcp["ticker"])]
        vcp["atr14_pct"] = [w["atr14_pct"].at[d, t] for d, t in zip(vcp["date"], vcp["ticker"])]
        self.vcp = vcp
        ready = vcp[vcp["price_ready_min"].fillna(False).astype(bool)]
        self.by_day = {d: g for d, g in ready.groupby("date")}
        self.catalyst = self._load_catalyst()
        self._needed = sorted(ready["ticker"].unique())
        log(f"  price-ready ticker-days (loosest grid): {len(ready)} across {len(self._needed)} tickers")

    def tickers_needed(self):
        return self._needed

    # A compact, parameter-independent snapshot of prepare()'s output, so a
    # tuning worker does not reload the 1,029-ticker panel for every run.
    FEED_COLS = ("sma_50", "avgvol50", "atr14_pct", "addv50")

    def to_bundle(self, path):
        import pickle
        b = {"panel": {c: self.panel[c][self._needed] for c in self.FEED_COLS},
             "vcp": self.vcp, "needed": self._needed, "days": self.days, "universe": self.universe,
             "market": self.market.name}
        with open(path, "wb") as f:
            pickle.dump(b, f)

    def use_bundle(self, path):
        import pickle
        with open(path, "rb") as f:
            b = pickle.load(f)
        self.panel, self.vcp, self._needed = b["panel"], b["vcp"], b["needed"]
        self.days, self.universe = b["days"], b["universe"]
        ready = self.vcp[self.vcp["price_ready_min"].fillna(False).astype(bool)]
        self.by_day = {d: g for d, g in ready.groupby("date")}
        self.catalyst = self._load_catalyst()
        self.lite = True

    def _load_catalyst(self):
        path = self.p.get("catalyst_path")
        if not (self.p["use_catalyst"] and path):
            return None
        cat = pd.read_parquet(path)
        cat["usable_from"] = pd.to_datetime(cat["usable_from"])
        return {t: g.sort_values("usable_from") for t, g in cat.groupby("ticker")}

    def _catalyst_for(self, ticker, day):
        """Latest scored catalyst usable at the close of `day`, within 90 days."""
        if self.catalyst is None or ticker not in self.catalyst:
            return None
        g = self.catalyst[ticker]
        g = g[(g["usable_from"] <= pd.Timestamp(day)) &
              (g["usable_from"] > pd.Timestamp(day) - pd.Timedelta(days=90)) &
              g["score"].isin(["STRONG_POSITIVE", "NEUTRAL", "STRONG_NEGATIVE"])]   # NOT_SCORED / NONE_FOUND carry no signal
        if g.empty:
            return None
        strong = g[g["score"].isin(["STRONG_POSITIVE", "STRONG_NEGATIVE"])]
        row = (strong if not strong.empty else g).iloc[-1]
        return {"score": row["score"], "date": str(row["usable_from"].date()),
                "items": row.get("items"), "source": row.get("source")}

    # ------------------------------------------------------------------ entries
    def candidates(self, ctx, day):
        ts = pd.Timestamp(day)
        g = self.by_day.get(ts)
        if g is None:
            return []
        g = g[(g["volume_ratio"] >= self.p["breakout_volume"]) & (g["rs_pct"] >= self.p["rs_threshold"])]
        out = []
        for r in g.itertuples(index=False):
            cat = self._catalyst_for(r.ticker, day) if self.p["use_catalyst"] else None
            adj = 0.0
            if cat:
                adj = {"STRONG_POSITIVE": 1, "STRONG_NEGATIVE": -1}.get(cat["score"], 0) * self.p["catalyst_weight"]
            out.append({"ticker": r.ticker, "date": str(day), "pivot": r.pivot, "vcp_quality": r.vcp_quality,
                        "rs_pct": r.rs_pct, "volume_ratio": r.volume_ratio, "atr14_pct": r.atr14_pct,
                        "rank_score": r.vcp_quality + adj, "catalyst": cat["score"] if cat else None,
                        "catalyst_detail": cat, "reason": "VCP_PIVOT_BREAKOUT",
                        "regime_state": "OPEN"})
        # strongest first; RS then ticker break ties deterministically
        out.sort(key=lambda c: (-c["rank_score"], -c["rs_pct"], c["ticker"]))
        return out

    def size_multiplier(self):
        streak = self.p["streak_steps"][self.streak_idx]
        defensive = self.p["defensive_size"] if self.defensive else 1.0
        pilot = self.p["reentry_pilot"] if self.reentry else 1.0
        return min(streak, defensive, pilot)       # FIX 17: min, not product

    def allocate(self, ctx, cands):
        slots = self.p["max_positions"] - ctx.n_open
        budget = ctx.cash - ctx.pending_buy_value
        mult = self.size_multiplier()
        out = []
        for i, c in enumerate(cands):
            if i >= slots:
                c["decision"] = "QUEUED_INSUFFICIENT_SLOTS"
                continue
            base = ctx.equity / self.p["max_positions"] * mult
            addv = ctx.addv.get(c["ticker"], float("nan"))
            if not (addv > 0):
                c["decision"] = "NO_ADDV"          # the sizer fails closed without volume history
                continue
            liq = self.p["liquidity_cap"] * addv
            value = min(base, liq, budget * CASH_HEADROOM)
            c.update({"size_mult": mult, "base_value": base, "liquidity_cap_value": liq,
                      "liquidity_bound": liq < base, "pilot": self.reentry, "defensive": self.defensive})
            if value <= 0:
                c["decision"] = "NO_CASH"
                continue
            budget -= value
            out.append((c, value))
        return out

    def on_entry_filled(self, ctx, ticker, st, bar):
        c = st["candidate"]
        entry = st["entry_price"]
        stop_cap = min(self.p["stop_max_pct"], self.p["defensive_stop_pct"]) if self.defensive \
            else self.p["stop_max_pct"]
        pivot = c.get("pivot")
        if pivot and pivot > 0:
            sd = (entry - pivot * PIVOT_STOP_BUFFER) / entry
            sd = max(STOP_DISTANCE_MIN, min(stop_cap, sd))
        else:
            sd = stop_cap
        st.update({
            "initial_stop_pct": sd, "initial_stop_dist": entry * sd, "breakeven_done": False,
            "largest_decline": max((c.get("atr14_pct") or 0.0) * DIST_ATR_MULT, 0.0),
            "pilot": bool(c.get("pilot")), "defensive_entry": self.defensive,
            "profit_target": entry * (1 + self.p["defensive_target_pct"]) if self.defensive else None,
            "highest_close": bar.close,
            "tags": {"pilot": bool(c.get("pilot")), "defensive_entry": self.defensive,
                     "size_mult": c.get("size_mult"), "liquidity_bound": c.get("liquidity_bound")},
        })
        self.n_open += 1
        return [("stop", entry * (1 - sd), "STOP_LOSS")]

    def on_entry_failed(self, ticker, c, status):
        c["decision"] = f"ORDER_{status}"

    # ------------------------------------------------------------------ exits
    def manage(self, ctx, ticker, st, bar):
        prev_high = st["highest_close"]
        st["highest_close"] = max(prev_high, bar.close)

        # Largest decline since entry on above-average volume (Feature 9 rule 3).
        if bar.open > 0:
            decline = (bar.open - bar.close) / bar.open
            if decline > 0 and decline > st["largest_decline"]:
                st["largest_decline"] = decline
                if bar.volume > bar.avgvol50 and st["bars_held"] >= DIST_MIN_BARS:
                    return [("exit", "DISTRIBUTION_BAR")]

        # Defensive-mode profit target (checked at the close, sold next open).
        if st.get("profit_target") and bar.close >= st["profit_target"]:
            return [("exit", "DEFENSIVE_PROFIT_TARGET")]

        # Breakeven: gain >= 3x the initial stop distance -> stop to entry.
        entry = st["entry_price"]
        if not st["breakeven_done"] and bar.close - entry >= self.p["breakeven_mult"] * st["initial_stop_dist"]:
            st["breakeven_done"] = True
            if entry > st.get("stop_price", 0):
                return [("stop", entry, "BREAKEVEN_STOP")]
            return []

        # Trailing stop after breakeven, ratcheted on new closing highs.
        if st["breakeven_done"] and bar.close > prev_high:
            levels = [bar.close * (1 - TRAIL_GIVEBACK)]
            if bar.sma50 == bar.sma50 and bar.sma50 > 0:     # not NaN
                levels.append(bar.sma50 * (1 - TRAIL_SMA_BUFFER))
            new = max(levels)
            if st.get("stop_price", 0) < new < bar.close:
                return [("stop", new, "TRAILING_STOP")]
        return []

    def on_trade_closed(self, rec):
        self.n_open -= 1
        win = rec["net_pnl"] > 0
        # Losing streak: consecutive LOSING trades step size down; a win steps up one level.
        if not win:
            self._losses = getattr(self, "_losses", 0) + 1
            for count, idx in self.p["streak_triggers"]:
                if self._losses >= count and idx > self.streak_idx:
                    self.streak_idx = idx
        else:
            self._losses = 0
            if self.streak_idx > 0:
                self.streak_idx -= 1                           # FIX 18
        # Reentry pilot graduates after 2 consecutive winners taken at pilot size.
        if rec.get("tag_pilot"):
            self.pilot_wins = self.pilot_wins + 1 if win else 0
            if self.pilot_wins >= self.p["pilot_wins_to_graduate"]:
                self.reentry, self.pilot_wins = False, 0
        # Defensive mode on the trailing 20 closed trades (>= 10 needed).
        self.recent.append(rec)
        self._update_defensive()
        if self.n_open == 0:
            self.reentry = True           # back in cash: the next entries are pilots
        self.state_log.append({"date": rec["exit_date"], "ticker": rec["ticker"], "win": win,
                               "streak_idx": self.streak_idx, "defensive": self.defensive,
                               "reentry": self.reentry, "pilot_wins": self.pilot_wins})

    def _update_defensive(self):
        tr = list(self.recent)
        if len(tr) < DEFENSIVE_MIN_TRADES:
            return
        wins = [t["net_pnl"] for t in tr if t["net_pnl"] > 0]
        losses = [-t["net_pnl"] for t in tr if t["net_pnl"] <= 0]
        rate = len(wins) / len(tr)
        avg_w = sum(wins) / len(wins) if wins else 0.0
        avg_l = sum(losses) / len(losses) if losses else 0.0
        ratio = avg_w / avg_l if avg_l > 0 else float("inf")
        if self.defensive:
            if ratio >= self.p["defensive_ratio_revert"] and rate >= self.p["defensive_rate_revert"]:
                self.defensive = False
        elif ratio < self.p["defensive_ratio_trigger"] or rate < self.p["defensive_rate_trigger"]:
            self.defensive = True

    # ------------------------------------------------------------------ receipts
    def record_candidates(self, day, cands):
        for c in cands:
            self.cand_log.append({k: v for k, v in c.items() if k != "catalyst_detail"} |
                                 {"catalyst_detail": json.dumps(c.get("catalyst_detail"), default=str)})

    def write_receipts(self, out_dir: Path):
        """Decision receipts: one row per ticker per day per stage reached."""
        out_dir = Path(out_dir)
        cl = pd.DataFrame(self.cand_log)
        cl.to_csv(out_dir / "candidates.csv", index=False)
        pd.DataFrame(self.state_log).to_csv(out_dir / "sizing_state.csv", index=False)
        if getattr(self, "lite", False):
            return          # tuning runs: candidate-level receipts only
        w = self.panel
        days = pd.DatetimeIndex(sorted({pd.Timestamp(d) for d in (cl["date"] if len(cl) else [])})) \
            if False else self.days
        tick = self.universe
        close = w["Close"].loc[days, tick]
        has_bar = close.notna()
        reg = w["regime"].loc[days, "gate_open"].astype(bool)
        tt = w["tt_core"].loc[days, tick].fillna(False).astype(bool)
        rs = w["rs_pct"].loc[days, tick]
        rs_ok = rs >= self.p["rs_threshold"]
        fv = self.fund_wide.reindex(index=days, columns=tick)
        vr = w["vol_ratio"].loc[days, tick]
        # stage reached, in pipeline order
        stage = pd.DataFrame("NO_BAR", index=days, columns=tick)
        stage = stage.mask(has_bar, "REJECTED_market_regime_gate")
        stage = stage.mask(has_bar & reg.values[:, None], "REJECTED_hard_filter")
        tt_pass = has_bar & reg.values[:, None] & tt & rs_ok
        stage = stage.mask(tt_pass & (fv == "SKIP"), "SKIPPED_fundamentals")
        stage = stage.mask(tt_pass & (fv == "FAIL"), "REJECTED_fundamentals")
        stage = stage.mask(tt_pass & (fv == "PASS"), "REJECTED_entry_timing")
        long = stage.stack().rename("stage").reset_index()
        long.columns = ["date", "ticker", "stage"]
        long = long[long["stage"] != "NO_BAR"]
        long["rs_pct"] = rs.stack().reindex(pd.MultiIndex.from_frame(long[["date", "ticker"]])).values
        long["tt_core_n"] = w["tt_core_n"].loc[days, tick].stack().reindex(
            pd.MultiIndex.from_frame(long[["date", "ticker"]])).values
        fl = self.fund_long.set_index(["date", "ticker"])[["fund_reason"]]
        long = long.join(fl, on=["date", "ticker"])
        v = self.vcp.set_index(["date", "ticker"])[["reason", "pivot", "vcp_quality", "volume_ratio"]]
        v.columns = ["entry_timing_reason", "pivot", "vcp_quality", "breakout_volume_ratio"]
        long = long.join(v, on=["date", "ticker"])
        # entry-timing verdict under THIS run's volume multiple
        at_et = long["stage"].eq("REJECTED_entry_timing")
        not_eval = at_et & long["entry_timing_reason"].isna()
        long.loc[not_eval, "entry_timing_reason"] = "BREAKOUT_VOLUME_BELOW_LOOSEST_MULTIPLE"
        ready = long["entry_timing_reason"].eq("PRICE_READY")
        weak = at_et & ready & (long["breakout_volume_ratio"] < self.p["breakout_volume"])
        long.loc[weak, "entry_timing_reason"] = "AWAITING_BREAKOUT_VOLUME"
        long.loc[at_et & ready & ~weak, "stage"] = "QUALIFIED"
        if len(cl):
            dec = cl.assign(date=pd.to_datetime(cl["date"])).set_index(["date", "ticker"])[["decision"]]
            long = long.join(dec, on=["date", "ticker"])
        long.to_parquet(out_dir / "decision_receipts.parquet", index=False)
