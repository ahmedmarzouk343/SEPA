"""The analyses pre-declared in PREDECLARED_HOLDOUT_ANALYSES.md, run on a
finished window. Nothing here selects or changes anything; it only reports.

    python kashif_engine/scripts/holdout_analysis.py HOLDOUT_primary HOLDOUT_with_catalyst
"""
import json
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "kashif_data" / "runs"


def lo_sharpe_se(sharpe, years):
    """Lo (2002) iid standard error of an annualised Sharpe ratio over `years`."""
    return math.sqrt((1 + sharpe ** 2 / 2) / years)


def analyse(run_id):
    d = RUNS / run_id
    m = json.loads((d / "metrics.json").read_text())
    s = m["metrics"]["strategy"]
    trades = pd.read_csv(d / "trades.csv") if (d / "trades.csv").stat().st_size > 2 else pd.DataFrame()
    run = json.loads((d / "run.json").read_text())
    u = json.load(open(ROOT / "us_fundamentals" / "sp_universe.json"))
    extras = set(u["existing"]) - set(u["sp400"]) - set(u["sp600"])
    years = (pd.Timestamp(s["end"]) - pd.Timestamp(s["start"])).days / 365.25
    se = lo_sharpe_se(s["sharpe"], years)
    out = {"run_id": run_id, "years": round(years, 2), "sharpe": s["sharpe"], "sharpe_se_lo2002": se,
           "sharpe_95ci": [s["sharpe"] - 1.96 * se, s["sharpe"] + 1.96 * se],
           "sharpe_distinguishable_from_0": abs(s["sharpe"]) > 1.96 * se,
           "audit_passed": m.get("audit_passed"), "audit_problems": m.get("audit", {}).get("problems")}
    if len(trades):
        trades["group"] = trades["ticker"].map(lambda t: "hand-picked extra" if t in extras else "sp400/sp600")
        g = trades.groupby("group").agg(trades=("net_pnl", "size"), net_pnl=("net_pnl", "sum"),
                                        win_rate=("net_pnl", lambda x: (x > 0).mean()))
        out["membership_split"] = g.round(3).to_dict(orient="index")
        out["exit_reasons"] = trades["exit_reason"].value_counts().to_dict()
        out["top5_trades"] = trades.nlargest(5, "net_pnl")[["ticker", "entry_date", "exit_date", "return_pct",
                                                            "net_pnl", "exit_reason"]].round(3).to_dict("records")
        out["share_of_net_pnl_from_top1"] = float(trades["net_pnl"].max() / trades["net_pnl"].sum()) \
            if trades["net_pnl"].sum() else None
    out["open_positions_at_end"] = [{"ticker": o["ticker"], "unrealized": round(o["shares"] * o["last_close"] - o["cost"], 2)}
                                    for o in run["open_positions"]]
    out["benchmarks"] = {k: {kk: m["metrics"][k][kk] for kk in ("total_return", "cagr", "max_drawdown", "sharpe", "sortino")}
                         for k in m["metrics"] if k != "strategy"}
    out["strategy"] = {k: s[k] for k in ("total_return", "cagr", "max_drawdown", "sharpe", "sortino", "trades",
                                         "win_rate", "avg_win_pct", "avg_loss_pct", "win_loss_ratio",
                                         "profit_factor", "exposure", "total_costs") if k in s}
    return out


if __name__ == "__main__":
    res = {r: analyse(r) for r in sys.argv[1:]}
    (ROOT / "backtest_results" / "holdout_analysis.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))
