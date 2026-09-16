"""
Diagnostic: Run a mini S&P 500 backtest with regime-gate instrumentation.
Patches _evaluate_market_regime to count how often each condition is True.
"""
import sys
from pathlib import Path

# Monkey-patch stubs BEFORE importing strategy
def _stub_catalyst_check(ticker, pipeline_run_id=None, **kwargs):
    return {
        "score": "NEUTRAL", "source": "STUB", "priority_tier": "N/A",
        "pipeline_blocks_entry": False,
        "rationale": "stub", "event_description": None,
        "disclosure_category": None, "retry_log": None,
        "error_flag": False, "model_call_attempted": False,
    }

def _stub_fetch_fundamentals(ticker, **kwargs):
    return None

import kashif_strategy
kashif_strategy.catalyst_check = _stub_catalyst_check
kashif_strategy.fetch_fundamentals = _stub_fetch_fundamentals

import collections
import backtrader as bt
import pandas as pd
import yfinance as yf
from kashif_strategy import KashifStrategy
from kashif_sizer import MinerviniSizer

WARMUP_START = "2022-08-01"
IS_END = "2025-08-26"
TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM",
           "V", "UNH", "JNJ", "WMT", "PG", "MA", "HD", "DIS", "BAC", "XOM",
           "PFE", "CSCO", "KO", "ABBV", "MRK", "PEP", "TMO", "COST", "LLY",
           "ABT", "CRM", "ACN"]

# Counters for diagnostics
diag = {
    "bars": 0,
    "ratio_true": 0,
    "pullback_true": 0,
    "divergence_true": 0,
    "gate_true": 0,
    "exceptions": 0,
    "insufficient_history": 0,
    "ratio_values": [],
    "deque_samples": [],
}

# Patch _evaluate_market_regime to collect diagnostics
_original_evaluate = KashifStrategy._evaluate_market_regime

def _instrumented_evaluate(self):
    diag["bars"] += 1
    try:
        from market_regime_gate import (
            leader_pullback_shallow, leader_divergence, market_regime_gate,
            get_leader_tickers
        )

        if self._rs_snapshot_cache is not None:
            rs_snapshot = self._rs_snapshot_cache
        else:
            rs_snapshot = self._compute_rs_snapshot()
            self._rs_snapshot_cache = rs_snapshot
        leader_tickers = get_leader_tickers(rs_snapshot) if rs_snapshot else []
        leader_prices = {d._name: pd.Series([b["Close"] for b in self.history[d]])
                          for d in self.datas if d._name in leader_tickers and len(self.history[d]) >= 20}
        universe_prices = {d._name: pd.Series([b["Close"] for b in self.history[d]])
                            for d in self.datas if len(self.history[d]) >= 40}

        if not leader_prices or not universe_prices:
            diag["insufficient_history"] += 1
            return False, {"reason": "insufficient_history"}

        pullback_pass, pullback_diag_inner = leader_pullback_shallow(leader_prices)
        if pullback_pass:
            diag["pullback_true"] += 1

        leader_hl = [self._higher_low_flag(s) for s in leader_prices.values()]
        universe_hl = [self._higher_low_flag(s) for s in universe_prices.values()]
        divergence_pass, divergence_diag_inner = leader_divergence(leader_hl, universe_hl)
        if divergence_pass:
            diag["divergence_true"] += 1

        ratio_pass = self._new_high_low_ratio_favorable_snapshot()
        if ratio_pass:
            diag["ratio_true"] += 1

        # Sample deque contents every 100 bars
        if diag["bars"] % 100 == 0:
            hl = list(self._high_low_counts)
            unique = len(set(hl))
            diag["deque_samples"].append({
                "bar": diag["bars"],
                "deque_len": len(hl),
                "unique_tuples": unique,
                "last_5": hl[-5:] if len(hl) >= 5 else hl,
            })

        gate_pass, gate_diag_inner = market_regime_gate(ratio_pass, pullback_pass, divergence_pass)
        if gate_pass:
            diag["gate_true"] += 1
        gate_diag_inner["_pullback"] = pullback_diag_inner
        gate_diag_inner["_divergence"] = divergence_diag_inner
        return gate_pass, gate_diag_inner
    except Exception as e:
        diag["exceptions"] += 1
        if diag["exceptions"] <= 3:
            print(f"  EXCEPTION in regime eval (bar {diag['bars']}): {e}")
        return False, {"reason": f"regime_evaluation_error: {e}"}

KashifStrategy._evaluate_market_regime = _instrumented_evaluate

# Download data
print(f"Downloading {len(TICKERS)} tickers...")
cerebro = bt.Cerebro()
viable = 0
for t in TICKERS:
    try:
        df = yf.download(t, start=WARMUP_START, end=IS_END, auto_adjust=True, progress=False)
        raw_df = yf.download(t, start=WARMUP_START, end=IS_END, auto_adjust=False, progress=False)
    except Exception:
        continue
    if df is None or df.empty or raw_df is None or raw_df.empty:
        continue
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if isinstance(raw_df.columns, pd.MultiIndex):
        raw_df.columns = raw_df.columns.get_level_values(0)
    df["Volume"] = raw_df["Volume"]
    if len(df) < 50:
        continue
    data = bt.feeds.PandasData(dataname=df, name=t)
    cerebro.adddata(data)
    viable += 1

print(f"Loaded: {viable} tickers")

cerebro.broker.setcash(100_000)
cerebro.broker.setcommission(commission=0.005)
cerebro.broker.set_slippage_perc(perc=0.001)
cerebro.addstrategy(KashifStrategy, target_position_count=max(4, min(viable // 10, 20)))
cerebro.addsizer(MinerviniSizer)

print("Running backtest...")
results = cerebro.run()

print(f"\n{'='*60}")
print(f"REGIME GATE DIAGNOSTIC RESULTS ({viable} tickers)")
print(f"{'='*60}")
print(f"Total bars:              {diag['bars']}")
print(f"Insufficient history:    {diag['insufficient_history']}")
print(f"Exceptions:              {diag['exceptions']}")
print(f"")
print(f"Bars ratio_pass=True:    {diag['ratio_true']}")
print(f"Bars pullback_pass=True: {diag['pullback_true']}")
print(f"Bars divergence_pass=True: {diag['divergence_true']}")
print(f"Bars gate=True (AND):    {diag['gate_true']}")

print(f"\nDeque samples:")
for s in diag["deque_samples"]:
    print(f"  Bar {s['bar']}: deque_len={s['deque_len']}, unique={s['unique_tuples']}, last_5={s['last_5']}")
