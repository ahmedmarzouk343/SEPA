"""Experiment 2 signal bundle: S&P 400+600 members only, panel US_idx.

    python kashif_engine/scripts/build_exp2_bundle.py dev          # 2022-01-03 .. 2026-09-24
The validation window is never bundled: run_validation2.py prepares it itself.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from kashif_engine import experiment2 as X
from kashif_engine.markets import US
from kashif_engine.run_backtest import DEFAULT_CONFIG
from kashif_engine.strategies.base import load_strategy

if __name__ == "__main__":
    assert sys.argv[1] == "dev", "only the development window is ever bundled"
    s = load_strategy(DEFAULT_CONFIG, X.BASE_PARAMS, US)
    uni = X.index_universe()
    s.prepare(uni, X.DEV[0], X.DEV[1], workers=8)
    assert set(s.universe) <= set(uni) and s.p["panel"] == "US_idx"
    out = ROOT / "kashif_data" / "signals" / "bundle_exp2_dev.pkl"
    s.to_bundle(out)
    print(f"bundle -> {out}: {len(s.universe)} tickers, panel {s.p['panel']}, "
          f"{len(s.by_day)} candidate days, {len(s._needed)} tradable tickers")
