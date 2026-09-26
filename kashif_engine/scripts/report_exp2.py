"""Experiment 2 report: the pre-declared analyses, written after the one validation run.

    python kashif_engine/scripts/report_exp2.py

Reads kashif_data/experiment2/{dev_grid.csv, selection2.json, VALIDATION_LOCK,
validation2_results.json} and the two validation run folders; writes
backtest_results/experiment2/EXPERIMENT2_REPORT_DATA.json (every number the
written report quotes) and copies the run artifacts next to it. Runs nothing.
"""
import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from kashif_engine import experiment2 as X  # noqa: E402
from kashif_engine import reports  # noqa: E402

RES = ROOT / "backtest_results" / "experiment2"
RUNS = ROOT / "kashif_data" / "runs"
ARMS = ("VAL2_A_pick", "VAL2_B_exp1_frozen")
MARGIN_RATE = 0.06          # assumed yearly cost of borrowed money for the leverage arithmetic


def lo_sharpe_se(ret: pd.Series) -> float:
    """Lo (2002) iid standard error of the annualised Sharpe from daily returns."""
    sr = ret.mean() / ret.std()
    return float(math.sqrt((1 + 0.5 * sr ** 2) / len(ret)) * math.sqrt(252))


def calendar_years(eq: pd.Series, curves: dict) -> list:
    out = []
    for y in sorted(set(eq.index.year)):
        row = {"year": int(y), "strategy": float(eq[eq.index.year == y].iloc[-1] / eq[eq.index.year < y].iloc[-1] - 1)
               if (eq.index.year < y).any() else float(eq[eq.index.year == y].iloc[-1] / eq.iloc[0] - 1)}
        for name, c in curves.items():
            cy = c[c.index.year == y]
            prev = c[c.index.year < y]
            row[name] = float(cy.iloc[-1] / (prev.iloc[-1] if len(prev) else cy.iloc[0]) - 1)
        out.append(row)
    return out


def leverage_table(ret: pd.Series) -> list:
    """What a constant leverage L would have done to the same daily returns
    (daily rebalanced, borrowing cost MARGIN_RATE on the borrowed part). It
    scales risk and return together; it cannot turn a non-edge into an edge."""
    rows = []
    for L in (1.0, 1.5, 2.0, 3.0, 4.0):
        r = L * ret - (L - 1) * MARGIN_RATE / 252
        eq = (1 + r).cumprod()
        yrs = len(r) / 252
        rows.append({"leverage": L, "cagr": float(eq.iloc[-1] ** (1 / yrs) - 1),
                     "max_drawdown": float((eq / eq.cummax() - 1).min()),
                     "worst_day": float(r.min()), "ruined": bool((1 + r).min() <= 0)})
    return rows


def main():
    sel = json.loads((X.OUT / "selection2.json").read_text())
    lock = json.loads(X.LOCK.read_text())
    val = json.loads((X.OUT / "validation2_results.json").read_text())
    grid = pd.read_csv(X.OUT / "dev_grid.csv")
    data = {"selection": sel, "lock_finished_utc": lock.get("finished_utc"),
            "frozen_inputs": {k: v for k, v in lock["frozen_inputs"].items() if k != "git_status_porcelain"},
            "dev_by_variant": grid.groupby("variant").agg(runs=("sharpe", "size"), best_sharpe=("sharpe", "max"),
                                                          median_sharpe=("sharpe", "median"),
                                                          best_cagr=("cagr", "max"), median_cagr=("cagr", "median"),
                                                          errors=("error", lambda s: int(s.notna().sum())))
                                   .round(4).reset_index().to_dict("records"),
            "arms": {}}
    RES.mkdir(parents=True, exist_ok=True)
    for arm in ARMS:
        d = RUNS / arm
        eq = pd.read_csv(d / "equity.csv", index_col=0, parse_dates=True)["equity"]
        ret = eq.pct_change().dropna()
        tr = pd.read_csv(d / "trades.csv") if (d / "trades.csv").exists() else pd.DataFrame()
        b = reports.benchmark_curves(eq.index[0], eq.index[-1]).reindex(eq.index).ffill()
        curves = {c: b[c] for c in b.columns} | {
            "EW_sp400_sp600_monthly": reports.ew_index_members(eq.index[0], eq.index[-1]).reindex(eq.index).ffill()}
        exits = (tr.groupby("exit_reason").agg(n=("return_pct", "size"), mean_return=("return_pct", "mean"),
                                               mean_max_gain=("max_gain_pct", "mean"), pnl=("net_pnl", "sum"))
                 .round(4).reset_index().to_dict("records") if len(tr) else [])
        big = tr[tr["max_gain_pct"] >= 0.20] if len(tr) else tr
        data["arms"][arm] = {
            "verdict": val[arm]["verdict"], "metrics": val[arm]["metrics"], "audit_passed": val[arm].get("audit_passed"),
            "lo_sharpe_se": lo_sharpe_se(ret), "calendar_years": calendar_years(eq, curves),
            "exit_reasons": exits,
            "trades_reaching_20pct": int(len(big)),
            "their_mean_realised": float(big["return_pct"].mean()) if len(big) else None,
            "top_trades": tr.sort_values("net_pnl").tail(10)[["ticker", "entry_date", "exit_date", "return_pct",
                                                               "exit_reason"]].to_dict("records") if len(tr) else [],
            "leverage": leverage_table(ret)}
        dst = RES / arm
        dst.mkdir(exist_ok=True)
        for f in ("equity.csv", "trades.csv", "fills.csv", "audit.json", "metrics.json", "run.json"):
            if (d / f).exists():
                shutil.copy2(d / f, dst / f)
    data["A_minus_B"] = val["A_minus_B"]
    (RES / "EXPERIMENT2_REPORT_DATA.json").write_text(json.dumps(data, indent=2, default=str))
    print(json.dumps({a: {"verdict": v["verdict"], "cagr": v["metrics"]["strategy"]["cagr"],
                          "sharpe": v["metrics"]["strategy"]["sharpe"], "lo_se": v["lo_sharpe_se"]}
                      for a, v in data["arms"].items()} | {"A_minus_B": data["A_minus_B"]}, indent=2, default=str))


if __name__ == "__main__":
    main()
