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
    uni = X.index_universe()
    # Same as run_validation2.py: rebuild the panel from the current prices
    # (load-time corrections and history breaks included) before bundling.
    from kashif_engine import panel as PANEL
    PANEL.build(uni, "US", name="US_idx")
    s = load_strategy(DEFAULT_CONFIG, X.BASE_PARAMS, US)
    s.prepare(uni, X.DEV[0], X.DEV[1], workers=8)
    assert set(s.universe) <= set(uni) and s.p["panel"] == "US_idx"
    # Freeze record (review M3/M4): the bundle names the clean commit and the
    # exact data it was built on; run_validation2 refuses other data.
    import subprocess
    from kashif_engine.data import fingerprint
    from kashif_engine.scripts.run_validation2 import dirty_code
    problems = fingerprint.store_integrity()
    if problems or dirty_code():
        sys.exit(f"REFUSED: store {problems}, uncommitted {dirty_code()}")
    prov = {"git_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                         text=True).stdout.strip(),
            "content": fingerprint.content(), "window": list(X.DEV),
            "days": [str(s.days[0].date()), str(s.days[-1].date())]}
    out = ROOT / "kashif_data" / "signals" / "bundle_exp2_dev.pkl"
    s.to_bundle(out, provenance=prov)
    print(f"bundle -> {out}: {len(s.universe)} tickers, panel {s.p['panel']}, "
          f"{len(s.by_day)} candidate days, {len(s._needed)} tradable tickers")
