"""Did our system pick the stocks Mark Minervini publicly disclosed buying?

    python kashif_engine/scripts/compare_minervini.py

Input : backtest_results/experiment3/minervini_check/minervini_disclosed_trades.csv
        (sourced list: ticker, action, date_or_period, date_precision, category, ...)
Output: backtest_results/experiment3/minervini_check/comparison.csv and a printed summary.

For each disclosed trade (ticker, date) it records, from data we already have:
  1. could we trade it: in the S&P 400/600 index universe? in experiment 1's
     wider 1,029-name universe? price and fundamentals data?
  2. our filters on the best day within +-10 trading days of his date:
     Trend Template (panel tt_core), RS percentile (vs the index universe that
     day), fundamentals verdict (the point-in-time screen), market regime gate,
     and whether an entry signal (50-day-high breakout on >= 1.2x volume) fired;
  3. whether any of our real runs listed it as a candidate or traded it within
     +-30 calendar days: experiment 1 (tune/holdout), experiment 2 (validation
     arms, dev pick, dev V0 reference), experiment 3 (B1-B3 on both windows).
Read-only: it runs no backtest.
"""
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kashif_engine import experiment2 as X2  # noqa: E402
from kashif_engine import panel as PANEL  # noqa: E402
from kashif_engine.data import prices as P  # noqa: E402
from kashif_engine.data import fundamentals as F  # noqa: E402
from kashif_engine.markets import US  # noqa: E402

DIR = ROOT / "backtest_results" / "experiment3" / "minervini_check"
RUNS = {  # name -> folder with candidates.csv / trades.csv
    "exp1_tune_2022_24": ROOT / "backtest_results" / "TUNE_final",
    "exp1_holdout_2024_26": ROOT / "backtest_results" / "HOLDOUT_primary",
    "exp2_valA_2017_21": ROOT / "kashif_data" / "runs" / "VAL2_A_pick",
    "exp2_valB_2017_21": ROOT / "kashif_data" / "runs" / "VAL2_B_exp1_frozen",
    "exp2_dev_pick_2022_26": ROOT / "kashif_data" / "experiment2" / "runs" / "x2_V1_rs_90_bre1.2_sto0.1_max4",
    "exp2_dev_V0_2022_26": ROOT / "kashif_data" / "experiment2" / "runs" / "x2_V0_rs_70_bre1.6_sto0.1_max6",
    **{f"exp3a_{a}_2017_21": ROOT / "kashif_data" / "experiment3" / "exp3a_2017_2021" / a for a in ("B1", "B2", "B3")},
    **{f"exp3_{a}_2024_26": ROOT / "kashif_data" / "experiment3" / "insample_2024_2026" / a for a in ("B1", "B2", "B3")},
}


def his_date(row) -> pd.Timestamp:
    s = str(row["date_or_period"]).strip()
    if len(s) == 10:
        return pd.Timestamp(s)
    if "Q" in s:
        y, q = s.split("-Q") if "-Q" in s else (s[:4], s[-1])
        return pd.Timestamp(int(y), 3 * int(q) - 1, 15)          # mid-quarter
    return pd.Timestamp(s + "-15") if len(s) == 7 else pd.Timestamp(s[:4] + "-06-30")


def load_runs():
    out = {}
    for name, d in RUNS.items():
        c = pd.read_csv(d / "candidates.csv", usecols=lambda c: c in ("ticker", "date", "decision")) \
            if (d / "candidates.csv").exists() else pd.DataFrame(columns=["ticker", "date"])
        t = pd.read_csv(d / "trades.csv") if (d / "trades.csv").exists() else pd.DataFrame()
        c["date"] = pd.to_datetime(c["date"])
        if len(t):
            t["entry_date"] = pd.to_datetime(t["entry_date"])
        out[name] = (c, t)
    return out


def main():
    trades = pd.read_csv(DIR / "minervini_disclosed_trades.csv")
    idx_uni = set(X2.index_universe())
    wide_uni = set(json.load(open(ROOT / "us_fundamentals" / "sp_universe.json"))["combined"])
    w = PANEL.load("US_idx")
    runs = load_runs()
    rows = []
    for _, r in trades.iterrows():
        t = str(r["ticker"]).upper().replace(".", "-")
        d0 = his_date(r)
        rec = {k: r[k] for k in ("ticker", "action", "date_or_period", "category", "confidence", "source_url")}
        rec |= {"in_index_universe": t in idx_uni, "in_wider_universe": t in wide_uni}
        px = P.load(t)
        rec["price_data"] = px is not None and len(px.loc[:d0]) > 0 if px is not None else False
        best = None
        if t in w["Close"].columns:
            days = w["Close"].index
            lo, hi = days.searchsorted(d0) - 10, days.searchsorted(d0) + 10
            for d in days[max(lo, 0):max(hi, 0)]:
                tt = bool(w["tt_core"].at[d, t]) if w["tt_core"].at[d, t] == w["tt_core"].at[d, t] else False
                rs = w["rs_pct"].at[d, t]
                hi50 = w["high50_prev"].at[d, t] if "high50_prev" in w else np.nan
                brk = bool(w["Close"].at[d, t] > hi50 and w["vol_ratio"].at[d, t] >= 1.2) if hi50 == hi50 else False
                reg = bool(w["regime"].loc[d].get("gate_open", True)) if "regime" in w else None
                score = tt + (rs >= 70 if rs == rs else 0) + brk
                if best is None or score > best[0]:
                    best = (score, d, tt, rs, brk, reg)
        if best:
            _, d, tt, rs, brk, reg = best
            try:
                fund = F.screen(t, d.date(), US)["verdict"]
            except Exception as e:  # noqa: BLE001
                fund = f"ERROR {type(e).__name__}"
            rec |= {"check_day": str(d.date()), "trend_template": tt, "rs_pct": round(float(rs), 1) if rs == rs else None,
                    "fundamentals": fund, "breakout_signal": brk, "regime_open": reg,
                    "passes_all": bool(tt and rs == rs and rs >= 70 and fund == "PASS" and brk)}
        else:
            rec["check_day"] = None
        hits_c, hits_t = [], []
        for name, (c, tr) in runs.items():
            cc = c[(c["ticker"] == t) & ((c["date"] - d0).abs() <= pd.Timedelta(days=30))]
            if len(cc):
                hits_c.append(f"{name}:{cc['date'].min().date()}")
            if len(tr):
                tt_ = tr[(tr["ticker"] == t) & ((tr["entry_date"] - d0).abs() <= pd.Timedelta(days=30))]
                for x in tt_.itertuples():
                    hits_t.append(f"{name}:{x.entry_date.date()}:{x.return_pct:+.0%}")
        rec |= {"our_candidate_within_30d": "; ".join(hits_c), "our_trade_within_30d": "; ".join(hits_t)}
        rows.append(rec)
    out = pd.DataFrame(rows)
    out.to_csv(DIR / "comparison.csv", index=False)
    buys = out[out["action"].isin(["BUY", "HOLD"])]
    print(f"disclosed rows: {len(out)} (buys/holds {len(buys)})")
    print(f"  in our index universe: {int(buys['in_index_universe'].sum())}; in the wider 1,029: {int(buys['in_wider_universe'].sum())}")
    tradable = buys[buys["in_index_universe"]]
    if len(tradable):
        print(f"  of those in-universe: trend template {int(tradable['trend_template'].fillna(False).sum())}, "
              f"fundamentals PASS {int((tradable['fundamentals'] == 'PASS').sum())}, breakout {int(tradable['breakout_signal'].fillna(False).sum())}, "
              f"all filters {int(tradable['passes_all'].fillna(False).sum())}, "
              f"our candidate {int((tradable['our_candidate_within_30d'] != '').sum())}, our trade {int((tradable['our_trade_within_30d'] != '').sum())}")
    print(out.to_string(index=False, max_colwidth=40))


if __name__ == "__main__":
    main()
