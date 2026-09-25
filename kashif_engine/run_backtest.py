"""Run one backtest end to end: prepare -> engine -> audit -> metrics.

    python -m kashif_engine.run_backtest --start 2022-01-03 --end 2024-06-28 \
        --params "{\"rs_threshold\": 80}" --run-id tune_example

Virtual money only: nothing here talks to a broker.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kashif_engine import engine, reports  # noqa: E402
from kashif_engine.auditor import audit  # noqa: E402
from kashif_engine.markets import MARKETS  # noqa: E402
from kashif_engine.strategies.base import load_strategy  # noqa: E402

DEFAULT_CONFIG = ROOT / "minervini_sepa_v1_strategy_config.json"
DATA_END = "2026-09-24"      # last complete session in the price cache (the 09-25 bar was partial)


def universe(market="US"):
    from kashif_engine.data import prices as P
    u = json.load(open(ROOT / "us_fundamentals" / "sp_universe.json"))["combined"]
    cached = set(P.cached_tickers(market))
    return sorted(t for t in u if t in cached)


def run_one(start, end, params=None, run_id=None, config=DEFAULT_CONFIG, market="US",
            tickers=None, tradable=None, capital=100_000.0, out_dir=None, do_audit=True,
            benchmarks=True, log=print, workers=8, bundle=None):
    mk = MARKETS[market]
    strat = load_strategy(config, params or {}, mk)
    uni = tickers or universe(market)
    if bundle:
        strat.use_bundle(bundle)
        uni = strat.universe
    else:
        strat.prepare(uni, start, end, log=log, workers=workers)
    if tradable is not None:        # smoke tests: RS still ranks the FULL universe
        strat.by_day = {d: g[g["ticker"].isin(tradable)] for d, g in strat.by_day.items()}
        strat._needed = [t for t in strat._needed if t in tradable]
    res = engine.run(strat, mk, start, end, capital=capital, run_id=run_id, out_dir=out_dir, log=log)
    out = {"run_id": res.run_id, "params": strat.params_dict()}
    if do_audit:
        a = audit(res.out_dir, mk)
        out["audit_passed"] = a["passed"]
        out["audit"] = {k: a[k] for k in ("cash_exact_match", "equity_exact_match", "per_trade_match",
                                          "round_trips", "problems")}
    eq_df = pd.read_csv(res.out_dir / "equity.csv", index_col=0, parse_dates=True)
    if benchmarks:
        out["metrics"] = reports.compare(eq_df, res.trades, universe=uni if tradable is None else tradable)
    else:
        out["metrics"] = {"strategy": reports.series_metrics(eq_df["equity"]) |
                          reports.trade_metrics(res.trades) | {"exposure": reports.exposure(eq_df)}}
    (res.out_dir / "metrics.json").write_text(json.dumps(out, indent=2, default=str))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", default=DATA_END)
    ap.add_argument("--params", default="{}")
    ap.add_argument("--run-id")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    a = ap.parse_args()
    out = run_one(a.start, a.end, json.loads(a.params), a.run_id, a.config)
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
