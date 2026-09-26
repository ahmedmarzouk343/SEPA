"""Add the current S&P 500 members to the data (universe widened by RULE, not by picks).

    python kashif_engine/scripts/build_sp500_data.py prices     # Yahoo bars from 2014-06
    python kashif_engine/scripts/build_sp500_data.py events     # SEC 8-K events from 2014, merged
    python kashif_engine/scripts/build_sp500_data.py universe   # add "sp500" to us_fundamentals/sp_universe.json

Membership list: kashif_data/sp500_members.json (Wikipedia's current constituents
table). Current members only -- survivorship bias, same kind as the S&P 400/600
universe, reported with every result.
"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

SP500 = json.load(open(ROOT / "kashif_data" / "sp500_members.json"))["sp500"]
UNI = ROOT / "us_fundamentals" / "sp_universe.json"


def new_tickers():
    have = set(json.load(open(UNI))["combined"])
    return [t for t in SP500 if t not in have]


def prices():
    from kashif_engine.data import prices as P
    todo = [t for t in SP500 if not P._cache_path("US", t).exists()]
    failed = P.download(todo, start="2014-06-01")
    print(f"downloaded {len(todo) - len(failed)} of {len(todo)}; failed: {failed}")


def events():
    from kashif_engine.catalyst import edgar
    edgar.DELAY = 0.2
    ev_path = ROOT / "kashif_data" / "edgar" / "events_8k.parquet"
    old = pd.read_parquet(ev_path)
    todo = [t for t in SP500 if t not in set(old["ticker"])]
    new = edgar.events(todo, since="2014-01-01")
    both = pd.concat([old, new], ignore_index=True).drop_duplicates(["ticker", "accession"])
    old.to_parquet(ev_path.with_name("events_8k_before_sp500.parquet"))
    both.to_parquet(ev_path)
    print(f"8-K events: {len(old)} -> {len(both)} rows; tickers {old.ticker.nunique()} -> {both.ticker.nunique()}")


def universe():
    u = json.load(open(UNI))
    u["sp500"] = SP500
    # "combined" drives the fundamentals pipeline; the index universes stay separate.
    u["combined"] = sorted(set(u["combined"]) | set(SP500))
    json.dump(u, open(UNI, "w"), indent=2)
    print(f"sp_universe.json: sp500 {len(SP500)}, combined {len(u['combined'])}")


if __name__ == "__main__":
    {"prices": prices, "events": events, "universe": universe}[sys.argv[1]]()
