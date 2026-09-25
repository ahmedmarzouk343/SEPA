"""Build the US signal panel for the full universe (cached in kashif_data/panels/US)."""
import json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from kashif_engine import panel
from kashif_engine.data import prices as P

u = json.load(open(ROOT / "us_fundamentals" / "sp_universe.json"))["combined"]
cached = set(P.cached_tickers("US"))
tickers = sorted(t for t in u if t in cached)
dropped = sorted(set(u) - cached)
print(f"universe {len(u)}, with prices {len(tickers)}, dropped (no Yahoo series): {dropped}")
t0 = time.time()
w = panel.build(tickers, "US")
r = w["regime"]
print(f"built in {time.time()-t0:.0f}s; dates {r.index[0].date()}..{r.index[-1].date()}")
x = r.loc["2022-01-01":]
print("regime open share since 2022:", round(x.gate_open.mean(), 3),
      "ratio", round(x.ratio_favorable.mean(), 3), "pullback", round(x.pullback_shallow.mean(), 3),
      "divergence", round(x.divergence.mean(), 3))
