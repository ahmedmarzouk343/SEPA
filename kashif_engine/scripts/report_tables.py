"""Markdown tables for FINAL_BACKTEST_REPORT.md, built from run outputs only."""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ROWS = [("total_return", "Total return", "pct"), ("cagr", "CAGR", "pct"), ("max_drawdown", "Max drawdown", "pct"),
        ("sharpe", "Sharpe (rf=0)", "num"), ("sortino", "Sortino", "num"), ("vol_annual", "Volatility", "pct")]
TRADE_ROWS = [("trades", "Closed trades", "int"), ("win_rate", "Win rate", "pct"),
              ("avg_win_pct", "Avg win", "pct"), ("avg_loss_pct", "Avg loss", "pct"),
              ("win_loss_ratio", "Avg win / avg loss", "num"), ("profit_factor", "Profit factor", "num"),
              ("exposure", "Exposure (avg invested)", "pct"), ("total_costs", "Costs paid ($)", "usd"),
              ("avg_bars_held", "Avg bars held", "num")]


def fmt(v, kind):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    if kind == "pct":
        return f"{v * 100:+.1f}%" if kind == "pct" else v
    if kind == "int":
        return f"{int(v)}"
    if kind == "usd":
        return f"{v:,.0f}"
    return "inf" if v == float("inf") else f"{v:.2f}"


def comparison_table(metrics: dict) -> str:
    cols = ["strategy"] + [c for c in ("MDY", "IJR", "MDY_IJR_5050", "SPY", "EW_sp400_sp600_monthly") if c in metrics]
    head = "| Metric | " + " | ".join(c.replace("_", " ") for c in cols) + " |\n|---|" + "---|" * len(cols) + "\n"
    body = ""
    for k, name, kind in ROWS:
        body += f"| {name} | " + " | ".join(fmt(metrics[c].get(k), kind) for c in cols) + " |\n"
    return head + body


def trade_table(m: dict) -> str:
    s = "| Trade statistic | Value |\n|---|---|\n"
    for k, name, kind in TRADE_ROWS:
        s += f"| {name} | {fmt(m.get(k), kind)} |\n"
    return s


if __name__ == "__main__":
    m = json.loads(Path(sys.argv[1]).read_text())["metrics"]
    print(comparison_table(m))
    print(trade_table(m["strategy"]))
