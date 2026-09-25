"""Re-collect 8-K events back to 2014 (experiment 2 amendment: same release-date method in both windows)."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from kashif_engine.catalyst import edgar
from kashif_engine.run_backtest import universe
edgar.DELAY = 0.2
df = edgar.events(universe(), since="2014-01-01")
old = ROOT / "kashif_data" / "edgar" / "events_8k.parquet"
old.rename(old.with_name("events_8k_2020start.parquet"))
df.to_parquet(old)
print(f"{len(df)} 8-K filings, {df.ticker.nunique()} tickers; item 2.02: {int(df['items'].str.contains('2.02').sum())}")
print("by year:", df['filing_date'].str[:4].value_counts().sort_index().to_dict())
