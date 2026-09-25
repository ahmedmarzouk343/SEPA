"""Collect every 8-K (items + acceptance time) for the universe from EDGAR."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from kashif_engine.catalyst import edgar
from kashif_engine.run_backtest import universe
edgar.DELAY = 0.2
df = edgar.events(universe(), since="2020-01-01")
out = ROOT / "kashif_data" / "edgar" / "events_8k.parquet"
df.to_parquet(out)
print(f"{len(df)} 8-K filings, {df.ticker.nunique()} tickers -> {out}")
print(df["tier"].value_counts().to_dict())
print("item 2.02 filings:", int(df["items"].str.contains("2.02").sum()))
print("code-only scores:", df["code_only_score"].value_counts().to_dict())
