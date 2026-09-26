"""The contract between the engine and a strategy module.

A strategy is a JSON config plus a module that subclasses StrategyModule. The
engine never looks inside: it asks for candidates, hands out fills, and
applies the one action per held position per bar that manage() returns.

Actions returned by on_entry_filled() / manage():
    ("stop", price, label)   replace the position's protective stop
    ("exit", reason)         sell everything at the next open
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path


class StrategyModule:
    name = "base"

    def __init__(self, config: dict, params: dict, market):
        self.config, self.params, self.market = config, params, market
        self.panel = None

    # --- data -------------------------------------------------------------
    def prepare(self, universe, start, end, log=print, validation_token=None):
        """Precompute whatever the strategy needs; must be lookahead-safe."""
        raise NotImplementedError

    def tickers_needed(self) -> list:
        raise NotImplementedError

    def feed_start(self, ticker):
        """Earliest date this ticker could ever be traded (None = run start).
        Bars before it are never used, so the engine may skip loading them."""
        return None

    # --- decisions --------------------------------------------------------
    def candidates(self, ctx, day) -> list:
        """Ranked entry candidates for the close of `day` (dicts with 'ticker')."""
        raise NotImplementedError

    def allocate(self, ctx, candidates) -> list:
        """[(candidate, dollar_value)] to buy at the next open."""
        raise NotImplementedError

    def on_entry_filled(self, ctx, ticker, state, bar) -> list:
        return []

    def on_entry_failed(self, ticker, candidate, status):
        pass

    def manage(self, ctx, ticker, state, bar) -> list:
        return []

    def on_trade_closed(self, record):
        pass

    # --- bookkeeping ------------------------------------------------------
    def record_candidates(self, day, candidates):
        pass

    def write_receipts(self, out_dir: Path):
        pass

    def params_dict(self) -> dict:
        return dict(self.params)


def load_strategy(config_path, params=None, market=None) -> StrategyModule:
    """Config JSON -> module instance, by the config's strategy_id."""
    cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
    sid = cfg["strategy_id"]
    mod = importlib.import_module(f"kashif_engine.strategies.{sid}.module")
    return mod.Strategy(cfg, params or {}, market)
