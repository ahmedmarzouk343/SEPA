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
import re
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
CONFIG_PILOT = 0.75                # config v0.28.1 performance_scaling.reentry_from_cash ("75% pilot")

# The loosest value of each tunable that changes WHICH ticker-days are candidates.
GRID_LOOSEST = {"rs_threshold": 70, "breakout_volume": 1.2}
RS_MAX = 100                       # rs_threshold is a percentile floor: 70 (loosest precomputed) .. 100
EARLY_RS_FLOOR = 95                # experiment 3 early_path: RS percentile at or above this
# Switches that change WHICH ticker-days prepare() precomputes; a bundle records them
# and is refused by a strategy whose switches differ (defaults = experiment 2).
STRUCTURAL_DEFAULTS = {"entry_mode": "vcp", "fund_mode": "strict", "early_path": False}
_FUND_Q = re.compile(r"\bQ([1-4])=(PASS|FAIL|SKIPPED|NOT_EVALUATED)\b")


def fund_score(verdict, reason) -> int:
    """fund_mode "rank_only": how many of the four fundamentals questions passed
    (a PASS verdict = 4; SKIP / no data = 0). Used to RANK, never to veto."""
    if verdict == "PASS":
        return 4
    if not isinstance(reason, str):
        return 0
    return sum(1 for _, st in _FUND_Q.findall(reason) if st == "PASS")


def fund_soft_single(verdict, reason) -> bool:
    """fund_mode "soft_single": True when a fundamentals FAIL fails ONLY Q2 or ONLY Q4.

    Parses the reason kashif_engine/data/fundamentals.screen() writes, e.g.
    "Q1=PASS, Q2=FAIL, Q3=PASS, Q4=SKIPPED". A Q1 failure ("Q1 FAIL: EPS growth ..."
    or "Q1 FAIL: current EPS ... is a loss"), a Q3 failure, a double Q2+Q4 failure
    and every SKIP verdict stay vetoes (False). The other of Q2/Q4 may be PASS or
    SKIPPED, and Q3 SKIPPED counts as not failing, as it does in the screen itself.
    """
    if verdict != "FAIL" or not isinstance(reason, str):
        return False
    st = dict(_FUND_Q.findall(reason))
    if set(st) != {"1", "2", "3", "4"} or st["1"] != "PASS" or st["3"] == "FAIL":
        return False
    return [st["2"], st["4"]].count("FAIL") == 1


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
            # Experiment 2 switches. Defaults reproduce v1 exactly.
            "defensive_mode": "full",          # full | size_only | off
            "regime_min_conditions": 1,        # 1 = OR gate (config), 2 = 2-of-3, 3 = AND
            "panel": "US",                     # signal panel: "US" = 1,029 names, "US_idx" = S&P 400+600 only
            # Experiment 2 amendment 3. Defaults reproduce v1 exactly.
            #   exit_mode "run": the largest-decline-on-volume signal is an exit_candidate
            #     FLAG (config wording), not an exit; the trail is the 50-day line less
            #     the 5% buffer only (no 15% give-back), raised every bar.
            #   scaling "config": config v0.28.1 performance_scaling -- no losing-streak
            #     step-down (REMOVED there), 75% re-entry pilot.
            "exit_mode": "v1",                 # v1 | run
            "scaling": "v1",                   # v1 | config
            # Experiment 3 entry switches. Defaults reproduce the behaviour above exactly.
            #   entry_mode "high50": close > the highest close of the previous 50 sessions
            #     with volume >= breakout_volume x the 50-day average volume (the panel's
            #     vol_ratio, today included, as the VCP breakout measures it) replaces the
            #     VCP price-ready gate only; that prior 50-day high is the pivot/stop anchor.
            #   rank_by "rs": candidates ranked by RS percentile instead of VCP quality.
            #   fund_mode "soft_single": a fundamentals FAIL whose ONLY failing question is
            #     Q2 or Q4 stays eligible, ranked after every strict pass (fund_soft_single).
            #   early_path: at rs_pct >= 95, tt_1/tt_2/tt_7 (close above the 150-, 200- and
            #     50-day lines) stand in for the full trend template.
            "entry_mode": "vcp",               # vcp | high50
            "rank_by": "vcp_quality",          # vcp_quality | rs
            "fund_mode": "strict",             # strict | soft_single | rank_only
            "early_path": False,
            "catalyst_weight": 0.5,
            "catalyst_path": None,
        }
        unknown = set(params) - set(self.p)
        if params.get("defensive_mode", "full") not in ("full", "size_only", "off"):
            raise ValueError("defensive_mode must be full, size_only or off")
        if params.get("regime_min_conditions", 1) not in (1, 2, 3):
            raise ValueError("regime_min_conditions must be 1, 2 or 3")
        if params.get("exit_mode", "v1") not in ("v1", "run"):
            raise ValueError("exit_mode must be v1 or run")
        if params.get("scaling", "v1") not in ("v1", "config"):
            raise ValueError("scaling must be v1 or config")
        if params.get("entry_mode", "vcp") not in ("vcp", "high50"):
            raise ValueError("entry_mode must be vcp or high50")
        if params.get("rank_by", "vcp_quality") not in ("vcp_quality", "rs"):
            raise ValueError("rank_by must be vcp_quality or rs")
        if params.get("fund_mode", "strict") not in ("strict", "soft_single", "rank_only"):
            raise ValueError("fund_mode must be strict, soft_single or rank_only")
        if not isinstance(params.get("early_path", False), bool):
            raise ValueError("early_path must be True or False")
        if unknown:
            raise KeyError(f"unknown strategy params: {sorted(unknown)}")
        self.p.update(params)
        if not (0.0 < self.p["stop_max_pct"] <= rr["stop_loss"]["hard_max_pct"]):
            raise ValueError("stop_max_pct may be tightened, never widened past the 10% hard max")
        if self.p["rs_threshold"] < GRID_LOOSEST["rs_threshold"] or \
                self.p["breakout_volume"] < GRID_LOOSEST["breakout_volume"]:
            raise ValueError("parameter looser than the precomputed signal grid")
        if self.p["rs_threshold"] > RS_MAX:          # a floor of 95 is fine; above 100 is a typo
            raise ValueError(f"rs_threshold is a percentile floor, at most {RS_MAX}")
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
    def prepare(self, universe, start, end, log=print, workers=8, validation_token=None):
        if self.market.name == "US":        # candidates in the validation window are results too
            from kashif_engine import experiment2 as X2
            X2.assert_window_allowed(start, end, validation_token)
        self.panel = PANEL.load(self.p["panel"])
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
        self.regime_n = w["regime"].loc[days, ["ratio_favorable", "pullback_shallow", "divergence"]] \
            .astype(bool).sum(axis=1)
        tt = w["tt_core"].loc[days, tickers].fillna(False).astype(bool)
        rs = w["rs_pct"].loc[days, tickers]
        vr = w["vol_ratio"].loc[days, tickers]
        trend = tt
        if self.p["early_path"]:
            early = self._panel_col("tt_early").loc[days, tickers].fillna(False).astype(bool)
            trend = tt | (early & (rs >= EARLY_RS_FLOOR))
        fund_ok = fv[tickers] == "PASS"
        if self.p["fund_mode"] == "soft_single":
            fr = fund.pivot(index="date", columns="ticker", values="fund_reason").reindex(index=days, columns=tickers)
            soft = pd.DataFrame(np.vectorize(fund_soft_single, otypes=[bool])(fv[tickers].to_numpy(), fr.to_numpy()),
                                index=days, columns=tickers)
            fund_ok = fund_ok | soft
        elif self.p["fund_mode"] == "rank_only":
            # Minervini's own buys failed our strict screen 12 times in 15
            # (backtest_results/experiment3/minervini_check/RESULT.md): the
            # fundamentals only RANK here, they never veto.
            fund_ok = pd.DataFrame(True, index=days, columns=tickers)
        pre = trend & (rs >= GRID_LOOSEST["rs_threshold"]) & (vr >= GRID_LOOSEST["breakout_volume"]) \
            & fund_ok
        pre = pre & reg.values[:, None]
        pre_long = pre.stack()
        pre_long = pre_long[pre_long].reset_index()
        pre_long.columns = ["date", "ticker", "_"]
        log(f"  pre-filtered ticker-days for entry timing: {len(pre_long)}")
        if self.p["entry_mode"] == "vcp":
            vcp = SIG.vcp_table(pre_long[["ticker", "date"]], GRID_LOOSEST["breakout_volume"],
                                workers=workers, log=log)
        else:
            vcp = self._high50_table(pre_long[["ticker", "date"]], w, vr)
        vcp["rs_pct"] = [rs.at[d, t] for d, t in zip(vcp["date"], vcp["ticker"])]
        vcp["atr14_pct"] = [w["atr14_pct"].at[d, t] for d, t in zip(vcp["date"], vcp["ticker"])]
        if self._structural() != STRUCTURAL_DEFAULTS:
            # Which relaxed path let each row in: ranked (fund_soft) and filtered on use.
            vcp["trend_early"] = [not tt.at[d, t] for d, t in zip(vcp["date"], vcp["ticker"])]
            vcp["fund_soft"] = [fv.at[d, t] != "PASS" for d, t in zip(vcp["date"], vcp["ticker"])]
        if self.p["fund_mode"] == "rank_only":
            fr = fund.pivot(index="date", columns="ticker", values="fund_reason")
            vcp["fund_score"] = [fund_score(fv.at[d, t], fr.at[d, t] if (d in fr.index and t in fr.columns) else None)
                                 for d, t in zip(vcp["date"], vcp["ticker"])]
        self.vcp = vcp
        ready = vcp[vcp["price_ready_min"].fillna(False).astype(bool)]
        self.by_day = {d: g for d, g in ready.groupby("date")}
        self.catalyst = self._load_catalyst()
        self._needed = sorted(ready["ticker"].unique())
        log(f"  price-ready ticker-days (loosest grid): {len(ready)} across {len(self._needed)} tickers")

    def tickers_needed(self):
        return self._needed

    def _structural(self):
        return {k: self.p[k] for k in STRUCTURAL_DEFAULTS}

    def _panel_col(self, name):
        if name not in self.panel:
            raise ValueError(f"panel {self.p['panel']!r} has no {name!r} column: rebuild it with "
                             "kashif_engine.panel.build (experiment 3 switches need it)")
        return self.panel[name]

    def _high50_table(self, pre, w, vr):
        """entry_mode "high50": the entry-timing table for the pre-filtered ticker-days.

        price_ready_min = close > the highest close of the previous 50 sessions
        (panel high50_prev, the ticker's own bars); the volume multiple is the
        panel's vol_ratio, filtered per run like the VCP breakout ratio. Same
        columns as SIG.vcp_table so candidates(), feed_start() and receipts work.
        """
        hi = self._panel_col("high50_prev")
        rows = []
        for d, t in zip(pre["date"], pre["ticker"]):
            h, c = hi.at[d, t], w["Close"].at[d, t]
            ready = bool(h == h and c > h)
            rows.append({"ticker": t, "date": d,
                         "reason": "PRICE_READY" if ready else ("NO_50D_HISTORY" if h != h else "BELOW_PRIOR_50D_HIGH"),
                         "price_ready_min": ready, "pivot": float(h) if h == h else None,
                         "vcp_quality": float("nan"), "volume_ratio": float(vr.at[d, t]), "close": float(c)})
        cols = ["ticker", "date", "reason", "price_ready_min", "pivot", "vcp_quality", "volume_ratio", "close"]
        return pd.DataFrame(rows, columns=cols)

    def feed_start(self, ticker):
        """First day this ticker is price-ready under the loosest grid: no
        parameter set can buy it earlier, and every indicator the strategy
        reads comes from the precomputed panel, so earlier bars are unused."""
        if not hasattr(self, "_first_ready"):
            ready = self.vcp[self.vcp["price_ready_min"].fillna(False).astype(bool)]
            self._first_ready = ready.groupby("ticker")["date"].min().to_dict()
        return self._first_ready.get(ticker)

    # A compact, parameter-independent snapshot of prepare()'s output, so a
    # tuning worker does not reload the 1,029-ticker panel for every run.
    FEED_COLS = ("sma_50", "avgvol50", "atr14_pct", "addv50")

    def to_bundle(self, path, provenance=None):
        import pickle
        from kashif_engine.data import fingerprint
        b = {"panel": {c: self.panel[c][self._needed] for c in self.FEED_COLS}, "regime_n": self.regime_n,
             "panel_name": self.p["panel"],
             "vcp": self.vcp, "needed": self._needed, "days": self.days, "universe": self.universe,
             "market": self.market.name, "structural": self._structural(),
             # Fills come from a fresh P.load per run: a bundle built on other
             # prices, splits, breaks or store would mix two data versions.
             "data_fp": fingerprint.quick(), "provenance": provenance or {}}
        with open(path, "wb") as f:
            pickle.dump(b, f)

    def use_bundle(self, path):
        import pickle
        with open(path, "rb") as f:
            b = pickle.load(f)
        self.panel, self.vcp, self._needed = b["panel"], b["vcp"], b["needed"]
        self.days, self.universe = b["days"], b["universe"]
        self.regime_n = b.get("regime_n")
        self.bundle_provenance = b.get("provenance", {})
        if "data_fp" in b or self.p["panel"] == "US_idx":
            from kashif_engine.data import fingerprint
            now = fingerprint.quick()
            diff = {k: (b.get("data_fp", {}).get(k), v) for k, v in now.items() if b.get("data_fp", {}).get(k) != v}
            if diff:
                raise ValueError(f"bundle {path} was built on other data: {diff}")
        built = b.get("structural", STRUCTURAL_DEFAULTS)
        if built != self._structural():
            # A bundle precomputes candidates for ONE set of entry switches (review of exp. 3 switches).
            raise ValueError(f"bundle {path} was built for {built}, strategy expects {self._structural()}")
        if b.get("panel_name", "US") != self.p["panel"]:
            # A bundle built on another universe would rank, gate and trade the
            # wrong names without any error (review finding).
            raise ValueError(f"bundle {path} was built on panel {b.get('panel_name', 'US')!r}, "
                             f"strategy expects {self.p['panel']!r}")
        if self.p["panel"] == "US_idx":
            from kashif_engine.experiment2 import index_universe
            extra = set(self.universe) - set(index_universe())
            if extra:
                raise ValueError(f"bundle universe has non-index names: {sorted(extra)[:5]}")
        if self.p["regime_min_conditions"] > 1 and self.regime_n is None:
            # A pre-experiment-2 bundle has no regime counts: a stricter gate would
            # silently return no candidates at all (review finding [4]).
            raise ValueError(f"bundle {path} predates regime_n; rebuild it for regime_min_conditions > 1")
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
        k = self.p["regime_min_conditions"]
        if k > 1 and (self.regime_n is None or self.regime_n.get(ts, 0) < k):
            return []
        g = self.by_day.get(ts)
        if g is None:
            return []
        g = g[(g["volume_ratio"] >= self.p["breakout_volume"]) & (g["rs_pct"] >= self.p["rs_threshold"])]
        exp3 = self._structural() != STRUCTURAL_DEFAULTS or self.p["rank_by"] != "vcp_quality"
        if "fund_soft" in g.columns and self.p["fund_mode"] == "strict":
            g = g[~g["fund_soft"].astype(bool)]
        if "trend_early" in g.columns and not self.p["early_path"]:
            g = g[~g["trend_early"].astype(bool)]
        out = []
        for r in g.itertuples(index=False):
            cat = self._catalyst_for(r.ticker, day) if self.p["use_catalyst"] else None
            adj = 0.0
            if cat:
                adj = {"STRONG_POSITIVE": 1, "STRONG_NEGATIVE": -1}.get(cat["score"], 0) * self.p["catalyst_weight"]
            base = r.rs_pct if self.p["rank_by"] == "rs" else r.vcp_quality
            if self.p["entry_mode"] == "high50" and base != base:
                base = 0.0          # no VCP quality under high50: ties fall through to RS, then ticker
            c = {"ticker": r.ticker, "date": str(day), "pivot": r.pivot, "vcp_quality": r.vcp_quality,
                 "rs_pct": r.rs_pct, "volume_ratio": r.volume_ratio, "atr14_pct": r.atr14_pct,
                 "rank_score": base + adj, "catalyst": cat["score"] if cat else None,
                 "catalyst_detail": cat,
                 "reason": "HIGH50_BREAKOUT" if self.p["entry_mode"] == "high50" else "VCP_PIVOT_BREAKOUT",
                 "regime_state": "OPEN"}
            if exp3:        # only non-default runs carry the extra receipt fields
                c.update({"entry_mode": self.p["entry_mode"], "rank_by": self.p["rank_by"],
                          "fund_soft": bool(getattr(r, "fund_soft", False)),
                          "fund_score": int(getattr(r, "fund_score", 4)),
                          "trend_path": "early" if getattr(r, "trend_early", False) else "core"})
            out.append(c)
        # strongest first; RS then ticker break ties deterministically. Under
        # fund_mode "soft_single" every strict fundamentals pass ranks first.
        if self.p["fund_mode"] == "soft_single":
            out.sort(key=lambda c: (c["fund_soft"], -c["rank_score"], -c["rs_pct"], c["ticker"]))
        elif self.p["fund_mode"] == "rank_only":
            out.sort(key=lambda c: (-c["fund_score"], -c["rank_score"], -c["rs_pct"], c["ticker"]))
        else:
            out.sort(key=lambda c: (-c["rank_score"], -c["rs_pct"], c["ticker"]))
        return out

    def size_multiplier(self):
        cfg = self.p["scaling"] == "config"
        streak = 1.0 if cfg else self.p["streak_steps"][self.streak_idx]
        defensive = self.p["defensive_size"] if self.defensive else 1.0
        pilot = (CONFIG_PILOT if cfg else self.p["reentry_pilot"]) if self.reentry else 1.0
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
        tighten = self.defensive and self.p["defensive_mode"] == "full"
        stop_cap = min(self.p["stop_max_pct"], self.p["defensive_stop_pct"]) if tighten \
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
            "profit_target": entry * (1 + self.p["defensive_target_pct"]) if tighten else None,
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
                    if self.p["exit_mode"] == "v1":
                        return [("exit", "DISTRIBUTION_BAR")]
                    st["distribution_flags"] = st.get("distribution_flags", 0) + 1

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

        # exit_mode "run": trail the 50-day line (less the buffer) every bar.
        if self.p["exit_mode"] == "run":
            if st["breakeven_done"] and bar.sma50 == bar.sma50 and bar.sma50 > 0:
                new = bar.sma50 * (1 - TRAIL_SMA_BUFFER)
                if st.get("stop_price", 0) < new < bar.close:
                    return [("stop", new, "TRAILING_STOP")]
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
        if self.p["defensive_mode"] == "off":
            self.defensive = False
            return
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
        """Decision receipts: one row per ticker per day per stage reached.

        Stages follow the default (experiment-2) pipeline. Under the experiment-3
        entry switches a candidate admitted by early_path or fund_mode
        "soft_single" is still labelled by the strict stage it failed here;
        candidates.csv carries the switch fields (trend_path, fund_soft, entry_mode)."""
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
        if self.p["regime_min_conditions"] > 1:
            reg = self.regime_n.reindex(days).fillna(0) >= self.p["regime_min_conditions"]
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
