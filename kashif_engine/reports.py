"""Performance metrics and benchmark comparison.

Conventions (stated, so numbers can be reproduced):
  * returns are daily, from the equity curve (dividends included);
  * CAGR uses calendar days / 365.25;
  * Sharpe = mean(daily excess) / std(daily) * sqrt(252) with rf = 0
    (no T-bill series is loaded -- this flatters every series equally);
  * max drawdown on daily closes;
  * benchmarks are total return (Yahoo AdjClose), buy-and-hold;
  * the equal-weight universe benchmark buys every CURRENT index member that
    traded on the first day in equal dollars and holds -- it inherits the same
    survivorship bias as the strategy's universe, so the gap between it and
    MDY/IJR estimates that bias.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from kashif_engine.data import prices as P


def series_metrics(eq: pd.Series) -> dict:
    eq = eq.dropna()
    r = eq.pct_change().dropna()
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1 if years > 0 else float("nan")
    dd = eq / eq.cummax() - 1
    sharpe = r.mean() / r.std() * math.sqrt(252) if r.std() > 0 else float("nan")
    dd_dev = float(np.sqrt((r.clip(upper=0) ** 2).mean()))      # downside deviation over ALL days
    sortino = r.mean() / dd_dev * math.sqrt(252) if dd_dev > 0 else float("nan")
    return {"start": str(eq.index[0].date()), "end": str(eq.index[-1].date()),
            "total_return": eq.iloc[-1] / eq.iloc[0] - 1, "cagr": cagr, "max_drawdown": dd.min(),
            "sharpe": sharpe, "sortino": sortino, "vol_annual": r.std() * math.sqrt(252),
            "calmar": cagr / abs(dd.min()) if dd.min() < 0 else float("nan")}


def trade_metrics(trades: pd.DataFrame) -> dict:
    if trades is None or len(trades) == 0:
        return {"trades": 0}
    w = trades[trades["net_pnl"] > 0]
    l = trades[trades["net_pnl"] <= 0]
    avg_w = w["return_pct"].mean() if len(w) else 0.0
    avg_l = l["return_pct"].mean() if len(l) else 0.0
    return {
        "trades": len(trades), "win_rate": len(w) / len(trades),
        "avg_win_pct": avg_w, "avg_loss_pct": avg_l,
        "win_loss_ratio": avg_w / abs(avg_l) if avg_l < 0 else float("inf"),
        "avg_win_dollars": w["net_pnl"].mean() if len(w) else 0.0,
        "avg_loss_dollars": l["net_pnl"].mean() if len(l) else 0.0,
        "win_loss_dollar_ratio": (w["net_pnl"].mean() / abs(l["net_pnl"].mean()))
        if len(l) and len(w) and l["net_pnl"].mean() < 0 else float("nan"),
        "profit_factor": w["net_pnl"].sum() / abs(l["net_pnl"].sum()) if l["net_pnl"].sum() < 0 else float("inf"),
        "net_pnl": trades["net_pnl"].sum(), "total_costs": trades["costs"].sum(),
        "avg_bars_held": trades["bars_held"].mean(),
        "avg_realized_loss_pct": avg_l,
        "exit_reasons": trades["exit_reason"].value_counts().to_dict(),
    }


def exposure(eq_df: pd.DataFrame) -> float:
    inv = (eq_df["equity"] - eq_df["cash"]) / eq_df["equity"]
    return float(inv.mean())


def benchmark_curves(start, end, market="US", universe=None, capital=100_000.0) -> pd.DataFrame:
    out = {}
    for b in ("MDY", "IJR", "SPY"):
        f = P.load(b, market)
        if f is None:
            continue
        s = f["AdjClose"].loc[start:end]
        out[b] = s / s.iloc[0] * capital
    if "MDY" in out and "IJR" in out:
        r = (out["MDY"].pct_change().fillna(0) + out["IJR"].pct_change().fillna(0)) / 2
        out["MDY_IJR_5050"] = (1 + r).cumprod() * capital
    if universe:
        out["EW_sp400_sp600_monthly"] = ew_index_members(start, end, market, capital)
    return pd.DataFrame(out)


def ew_index_members(start, end, market="US", capital=100_000.0) -> pd.Series:
    """Equal weight over CURRENT S&P 400 + S&P 600 members (not the 36
    hand-picked extras), rebalanced at each month start. The gap to MDY/IJR
    mixes survivorship with the equal-weight tilt; it is labelled that way."""
    import json
    root = Path(__file__).resolve().parents[1]
    u = json.load(open(root / "us_fundamentals" / "sp_universe.json"))
    names = sorted(set(u["sp400"]) | set(u["sp600"]))
    rets = {}
    for t in names:
        f = P.load(t, market)
        if f is not None:
            rets[t] = f["AdjClose"].loc[start:end].pct_change()
    r = pd.DataFrame(rets)
    month = r.index.to_period("M")
    out, level = [], capital
    for _, g in r.groupby(month):
        members = g.columns[g.notna().any()]
        growth = (1 + g[members].fillna(0)).cumprod().mean(axis=1)   # equal weight at month start, then drift
        out.append(level * growth)
        level = out[-1].iloc[-1]
    s = pd.concat(out)
    s.iloc[0] = capital
    return s


def compare(eq_df: pd.DataFrame, trades: pd.DataFrame, universe=None) -> dict:
    eq = eq_df["equity"]
    start, end = eq.index[0], eq.index[-1]
    bench = benchmark_curves(start, end, universe=universe).reindex(eq.index).ffill()
    res = {"strategy": series_metrics(eq) | trade_metrics(trades) | {"exposure": exposure(eq_df)}}
    for c in bench.columns:
        res[c] = series_metrics(bench[c])
    return res


def quantstats_html(eq: pd.Series, bench: pd.Series, path: Path, title: str):
    import quantstats as qs
    r = eq.pct_change().dropna()
    b = bench.reindex(eq.index).ffill().pct_change().dropna()
    r.index = pd.to_datetime(r.index)
    b.index = pd.to_datetime(b.index)
    qs.reports.html(r, benchmark=b, output=str(path), title=title, download_filename=str(path))
