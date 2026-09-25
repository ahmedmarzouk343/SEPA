"""Precompute the parameter-independent signal bundle for one window.

    python kashif_engine/scripts/build_signals.py tune
    python kashif_engine/scripts/build_signals.py holdout   # only after tuning is frozen
"""
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from kashif_engine.markets import US
from kashif_engine.run_backtest import universe, DEFAULT_CONFIG
from kashif_engine.strategies.base import load_strategy
from kashif_engine.tune import TUNE, HOLDOUT

if __name__ == "__main__":
    which = sys.argv[1]
    start, end = {"tune": TUNE, "holdout": HOLDOUT}[which]
    t0 = time.time()
    s = load_strategy(DEFAULT_CONFIG, {}, US)
    s.prepare(universe(), start, end, workers=8)
    out = ROOT / "kashif_data" / "signals" / f"bundle_{which}.pkl"
    s.to_bundle(out)
    fv = s.fund_long["fund_verdict"].value_counts().to_dict()
    print(f"{which} {start}..{end}: fundamentals verdict ticker-days {fv}")
    print(f"VCP evaluations {len(s.vcp)}, reasons: {s.vcp['reason'].value_counts().head(12).to_dict()}")
    print(f"bundle -> {out} ({time.time() - t0:.0f}s)")
