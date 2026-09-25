"""Re-download every cached ticker from 2014-06 (validation window needs 2017 history)."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from kashif_engine.data import prices as P
tickers = P.cached_tickers("US")
failed = P.download(tickers, "US", start="2014-06-01", end="2026-09-25", chunk=40, pause=3.0, force=True)
print("FAILED:", failed)
