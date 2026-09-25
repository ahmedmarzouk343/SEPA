"""Phase 1 smoke test: 20 stocks, 2022-2025, point-in-time fundamentals.

Expectation stated BEFORE running: an EPS growth/acceleration rule must flag
NVDA during 2023 (Q2 FY2024 EPS +854% YoY, released 2023-08-23).
"""
import json, sys
from datetime import date
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from kashif_engine.data import fundamentals as F
from kashif_engine.markets import US

u = set(json.load(open(ROOT / "us_fundamentals" / "sp_universe.json"))["combined"])
WANT = ["NVDA", "AAPL", "SMCI", "CELH", "ELF", "ANF", "AAON", "ACMR", "MLI", "CRVL", "TTEK", "EXLS",
        "PANW", "WMT", "GME", "NLY", "POWL", "PIPR", "FIX", "DECK", "AMZN", "GOOGL", "CRM", "BURL"]
tickers = [t for t in WANT if t in u][:20]
days = pd.bdate_range("2022-01-03", "2025-12-31")
rows = []
for t in tickers:
    v = F.daily_verdicts(t, days, US)
    c = v["fund_verdict"].value_counts()
    skip_reasons = v.loc[v.fund_verdict == "SKIP", "fund_reason"].value_counts().head(2).to_dict()
    rows.append({"ticker": t, "PASS_days": int(c.get("PASS", 0)), "FAIL_days": int(c.get("FAIL", 0)),
                 "SKIP_days": int(c.get("SKIP", 0)), "top_skip_reasons": skip_reasons})
print(pd.DataFrame(rows).to_string(index=False))

print("\nNVDA timeline (first trading day after each usable release):")
v = F.daily_verdicts("NVDA", days, US)
chg = v[(v["fund_quarter"] != v["fund_quarter"].shift())]
for d, r in chg.loc[:"2024-06-30"].iterrows():
    s = F.screen("NVDA", d.date(), US)
    det = s.get("detail", {})
    q = {k: det.get(k, {}).get("status") for k in ("q1", "q2", "q3", "q4")} if det else {}
    g = r["eps_growth"]
    print(f"  {d.date()}  {r['fund_quarter']:8s} eps_yoy={'' if pd.isna(g) else f'{g:+.0%}':>7s}  "
          f"{s['verdict']:4s} {q}  {s['reason'][:60]}")
flag = [d for d in pd.bdate_range("2023-01-01", "2023-12-31")
        if (lambda s: s.get("detail", {}).get("q1", {}).get("status") == "PASS"
            and s["detail"]["q2"]["status"] == "PASS")(F.screen("NVDA", d.date(), US))]
print(f"\nNVDA 2023 days where EPS growth (Q1) AND acceleration (Q2) both pass: {len(flag)}"
      f" (first {flag[0].date() if flag else None})")
assert flag, "SMOKE FAIL: NVDA never flagged by growth+acceleration in 2023"
print("SMOKE PASS: growth/acceleration flags NVDA in 2023")
