"""Chaos test (data_mutator style) on the real engine with REAL price files,
mutated in a temporary cache:

  1. missing weeks   -- 3 weeks of bars deleted while a position is held
  2. zero volume     -- a week of zero-volume bars (entries must be refused)
  3. 10x price spike -- one bar's OHLC multiplied by 10 while held
  4. all-NaN ticker  -- a feed with no usable bars at all
  5. fundamentals    -- a store query before any release must SKIP, not guess

Pass = no crash, bad bars flagged (never traded on), ledger reconciled after
every fill, and the independent auditor still matches the ledger exactly.
"""
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kashif_engine import engine  # noqa: E402
from kashif_engine.auditor import audit  # noqa: E402
from kashif_engine.data import prices as P  # noqa: E402
from kashif_engine.markets import US  # noqa: E402
from kashif_engine.strategies.base import StrategyModule  # noqa: E402

REAL = P.CACHE_DIR
TICKERS = ["AAON", "FIX", "MLI", "EXLS", "NANX"]
START, END = "2023-01-03", "2023-12-29"


@pytest.fixture()
def chaos_dir(tmp_path, monkeypatch):
    (tmp_path / "US").mkdir()
    for t in ("SPY", "AAON", "FIX", "MLI", "EXLS"):
        shutil.copy(REAL / "US" / f"{t}.parquet", tmp_path / "US" / f"{t}.parquet")
    monkeypatch.setattr(P, "CACHE_DIR", tmp_path)
    # 1. AAON: delete three weeks of bars in March
    f = pd.read_parquet(tmp_path / "US" / "AAON.parquet")
    f = f.drop(f.loc["2023-03-06":"2023-03-24"].index)
    f.to_parquet(tmp_path / "US" / "AAON.parquet")
    # 2. FIX: zero volume for a week in February
    f = pd.read_parquet(tmp_path / "US" / "FIX.parquet")
    f.loc["2023-02-06":"2023-02-10", "Volume"] = 0.0
    f.to_parquet(tmp_path / "US" / "FIX.parquet")
    # 3. MLI: one 10x bar in May
    f = pd.read_parquet(tmp_path / "US" / "MLI.parquet")
    f.loc["2023-05-16", ["Open", "High", "Low", "Close"]] *= 10
    f.to_parquet(tmp_path / "US" / "MLI.parquet")
    # 4. NANX: a ticker whose every bar is NaN
    g = pd.read_parquet(tmp_path / "US" / "EXLS.parquet").copy()
    g[["Open", "High", "Low", "Close", "AdjClose", "Volume"]] = np.nan
    g.to_parquet(tmp_path / "US" / "NANX.parquet")
    return tmp_path


class ChaosStub(StrategyModule):
    """Buys every ticker on fixed dates (including INTO the damaged windows)."""
    name = "chaos"

    def __init__(self):
        super().__init__({}, {}, US)
        cols = {}
        for t in TICKERS:
            f = P.load(t, "US")
            cols.setdefault("sma_50", {})[t] = f["Close"].rolling(50).mean()
            cols.setdefault("avgvol50", {})[t] = f["Volume"].rolling(50).mean()
            cols.setdefault("atr14_pct", {})[t] = pd.Series(0.02, index=f.index)
            cols.setdefault("addv50", {})[t] = (f["Close"] * f["Volume"]).rolling(50).mean()
        self.panel = {k: pd.DataFrame(v) for k, v in cols.items()}
        d = lambda s: pd.Timestamp(s).date()  # noqa: E731
        self.plan = {d("2023-01-10"): ["AAON", "MLI", "NANX"], d("2023-02-07"): ["FIX"],
                     d("2023-02-15"): ["FIX", "EXLS"]}

    def tickers_needed(self):
        return TICKERS

    def candidates(self, ctx, day):
        return [{"ticker": t, "reason": "CHAOS"} for t in self.plan.get(day, [])]

    def allocate(self, ctx, cands):
        return [(c, 15_000.0) for c in cands if (ctx.addv.get(c["ticker"]) or 0) > 0]

    def on_entry_filled(self, ctx, t, st, bar):
        return [("stop", st["entry_price"] * 0.80, "STOP_LOSS")]

    def manage(self, ctx, t, st, bar):
        if bar.close > st["entry_price"] * 3:          # would fire only on a bad bar
            return [("exit", "SHOULD_NOT_HAPPEN")]
        return []


def test_chaos(chaos_dir, tmp_path):
    res = engine.run(ChaosStub(), US, START, END, out_dir=tmp_path / "run", log=lambda *a: None)
    fills = res.fills
    ev = pd.read_csv(res.out_dir / "events.csv")
    # NANX has no usable bars: never bought.
    assert "NANX" not in set(fills["ticker"])
    # FIX: the zero-volume week is suspect -> the 2023-02-07 candidate is refused; the
    # 2023-02-15 one (clean bar) is bought.
    fix_buys = fills[(fills.ticker == "FIX") & (fills.side == "BUY")]
    assert len(fix_buys) == 1 and fix_buys.iloc[0].date >= "2023-02-16"
    # MLI: the 10x bar is flagged and never triggers the strategy exit.
    assert ((ev.get("ticker") == "MLI") & (ev.get("event") == "SUSPECT_BAR_HELD")).any()
    assert "SHOULD_NOT_HAPPEN" not in set(res.trades.get("exit_reason", []))
    # AAON: 15 trading days without bars while held (> the 10-day stale limit) -> an exit is
    # queued, and it fills at the OPEN of the first real bar after the gap (2023-03-27) --
    # never on a dark day and never at a fabricated price.
    aaon = res.trades[res.trades.ticker == "AAON"]
    assert len(aaon) == 1 and aaon.iloc[0]["exit_reason"] == "STALE_FEED_EXIT"
    first_back = P.load("AAON").loc["2023-03-25":].iloc[0]
    assert aaon.iloc[0]["exit_date"] == str(first_back.name.date())
    assert aaon.iloc[0]["exit_price"] == pytest.approx(first_back["Open"])
    # Books still balance and the auditor agrees exactly -- including the tape checks.
    rep = audit(res.out_dir, US)
    assert rep["passed"], rep["problems"]


def test_fundamentals_before_first_release_skips():
    from datetime import date
    from kashif_engine.data import fundamentals as F
    s = F.screen("AAON", date(2010, 1, 4), US)
    assert s["verdict"] == "SKIP" and s["reason"] == "NO_FUNDAMENTALS"
