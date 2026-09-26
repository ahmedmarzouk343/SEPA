"""Build kashif_data/experiment4/modelbook_eval/{windows.parquet, key.csv}.

Signal-level evaluation set from the model book (kashif_data/experiment2/model_book_dev).

Qualified breakout (both classes), on a liquid day (raw close >= $10, 50-day $ volume >= $5M):
  Trend Template tt_1..tt_8b (panel tt_core) AND RS percentile >= 70 (panel rs_pct)
  AND close > the prior 50-day closing high AND volume >= 1.2x its 50-day average,
  AND "fresh": no other qualified day for that ticker in the previous 20 trading days.
  (No VCP detector, no fundamentals, no regime gate: the chart judge is meant to replace the base reading.)
WINNER: for each model-book episode, the first fresh qualified day in its catchable window
  E = [L, last day with >= +50% left] whose forward 126-day max close is >= +50%.
NON_WINNER: fresh qualified days with a full 126-day forward horizon whose forward 126-day
  max close is < +50%. 3 per winner, drawn (seed 41, without replacement) on the winner's
  date; if fewer than needed, from the nearest dates within +/-5 trading days (offset kept).
Both classes need a full 126-day forward horizon (signal date <= about 2026-03-25).
Window: the 250 bars ending on the signal day (inclusive). OHLC / first close of the window * 100;
  volume / its trailing 50-bar mean (including that bar, like the engine). No tickers, no dates.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\Asuss\Stocks")
sys.path.insert(0, str(ROOT))
from kashif_engine.data import prices as P  # noqa: E402

MB = ROOT / "kashif_data/experiment2/model_book_dev"
OUT = ROOT / "kashif_data/experiment4/modelbook_eval"
SEED, N_CTRL, MAX_OFF, FRESH, WIN = 41, 3, 5, 20, 250


def main():
    d = pd.read_parquet(MB / "days.parquet")
    d["q"] = d["liquid"].astype(bool) & d["tt_ok"] & d["rs70"] & (d["vr"] >= 1.2) & d["hi50_break"].astype(bool)
    cal = pd.DatetimeIndex(sorted(d["date"].unique()))
    pos = pd.Series(np.arange(len(cal)), index=cal)
    q = d[d["q"]].sort_values(["ticker", "date"]).copy()
    q["p"] = q["date"].map(pos)
    q["gap"] = q.groupby("ticker")["p"].diff()
    q["fresh"] = q["gap"].isna() | (q["gap"] > FRESH)
    qf = q[q["fresh"]]
    counts = {"qualified_days": len(q), "fresh_qualified_days": len(qf)}

    ep = pd.read_csv(MB / "winners.csv", parse_dates=["L_date", "last50_date"])
    win, no_day, no_horizon = [], 0, 0
    for e in ep.itertuples():
        x = qf[(qf["ticker"] == e.ticker) & (qf["date"] >= e.L_date) & (qf["date"] <= e.last50_date)
               & (qf["fwd_max126"] >= 0.5)]
        if x.empty:
            no_day += 1
            continue
        r = x.iloc[0]
        if r["fwd_days"] < 126:
            no_horizon += 1
            continue
        win.append({"ticker": e.ticker, "date": r["date"], "episode_id": e.episode_id})
    win = pd.DataFrame(win).sort_values(["date", "ticker"]).reset_index(drop=True)
    counts.update({"episodes": len(ep), "episodes_no_qualifying_day": no_day,
                   "episodes_after_horizon_cutoff": no_horizon, "winners_selected": len(win)})

    pool = qf[(qf["fwd_days"] >= 126) & (qf["fwd_max126"] < 0.5)][["ticker", "date"]]
    pool = pool.assign(p=pool["date"].map(pos))
    rng = np.random.default_rng(SEED)
    used, ctrl, short = set(), [], 0
    for w in win.itertuples():
        wp = pos[w.date]
        got = []
        for off in [0] + [s * k for k in range(1, MAX_OFF + 1) for s in (-1, 1)]:
            if len(got) >= N_CTRL:
                break
            c = pool[(pool["p"] == wp + off)]
            c = c[[(t, dt) not in used for t, dt in zip(c["ticker"], c["date"])]]
            if c.empty:
                continue
            take = rng.choice(len(c), size=min(N_CTRL - len(got), len(c)), replace=False)
            for i in sorted(take):
                row = c.iloc[i]
                used.add((row["ticker"], row["date"]))
                got.append({"ticker": row["ticker"], "date": row["date"], "episode_id": None,
                            "matched_to": w.ticker + "_" + w.date.strftime("%Y%m%d"), "date_offset": off})
        short += N_CTRL - len(got)
        ctrl.extend(got)
    ctrl = pd.DataFrame(ctrl)
    counts["control_shortfall"] = short
    win["matched_to"] = win["ticker"] + "_" + win["date"].dt.strftime("%Y%m%d")
    win["date_offset"] = 0
    s = pd.concat([win.assign(label="WINNER"), ctrl.assign(label="NON_WINNER")], ignore_index=True)

    # history check: 250 bars + 49 earlier bars for the first bar's 50-bar volume mean.
    # A winner without it is dropped together with its matched controls.
    cache = {t: P.load(t)[["Open", "High", "Low", "Close", "Volume"]] for t in s["ticker"].unique()}
    ok = np.array([cache[r.ticker].index.get_loc(r.date) + 1 >= WIN + 49 for r in s.itertuples()])
    bad_groups = set(s.loc[~ok & (s["label"] == "WINNER"), "matched_to"])
    counts["dropped_short_history_winners"] = len(bad_groups)
    counts["dropped_short_history_controls"] = int((~ok & (s["label"] == "NON_WINNER")).sum())
    s = s[ok & ~s["matched_to"].isin(bad_groups)]

    # windows + forward returns from prices
    feats = d.set_index(["ticker", "date"])
    wins, keys = [], []
    for r in s.itertuples():
        df = cache[r.ticker]
        i = df.index.get_loc(r.date)
        va = df["Volume"].rolling(50).mean()
        w = df.iloc[i - WIN + 1:i + 1]
        base = w["Close"].iloc[0]
        wins.append(pd.DataFrame({"bar": np.arange(WIN), "open": w["Open"] / base * 100,
                                  "high": w["High"] / base * 100, "low": w["Low"] / base * 100,
                                  "close": w["Close"] / base * 100,
                                  "vol_rel": (w["Volume"] / va.iloc[i - WIN + 1:i + 1]).to_numpy()})
                    .assign(_row=r.Index))
        c = df["Close"]
        f = feats.loc[(r.ticker, r.date)]
        keys.append({"_row": r.Index, "ticker": r.ticker, "date": r.date.date(), "label": r.label,
                     "episode_id": r.episode_id, "matched_to": r.matched_to, "date_offset": r.date_offset,
                     "fwd_ret20": c.iloc[i + 20] / c.iloc[i] - 1, "fwd_ret60": c.iloc[i + 60] / c.iloc[i] - 1,
                     "fwd_ret126": c.iloc[i + 126] / c.iloc[i] - 1, "fwd_max126": f["fwd_max126"],
                     "rs_pct": f["rs_pct"], "vol_ratio": f["vr"], "dist_52wh": f["dist_52wh"],
                     "raw_close": f["raw_close"], "addv50": f["addv50"], "fund_verdict": f["fund_verdict"],
                     "vcp_ready_x1_2": bool(f["vcp12"]), "regime_open": bool(f["regime_or"])})
    key = pd.DataFrame(keys)
    # anonymous ids in random order (so row order carries no label or date information)
    perm = np.random.default_rng(SEED).permutation(len(key))
    key["sample_id"] = [f"S{k:04d}" for k in perm]
    idmap = dict(zip(key["_row"], key["sample_id"]))
    win_df = pd.concat(wins, ignore_index=True)
    win_df.insert(0, "sample_id", win_df.pop("_row").map(idmap))
    win_df = win_df.sort_values(["sample_id", "bar"]).reset_index(drop=True)
    for col in ("open", "high", "low", "close", "vol_rel"):
        win_df[col] = win_df[col].astype("float32")
    key = key.drop(columns="_row").sort_values("sample_id")
    key = key[["sample_id"] + [c for c in key.columns if c != "sample_id"]]

    OUT.mkdir(parents=True, exist_ok=True)
    win_df.to_parquet(OUT / "windows.parquet", index=False)
    key.to_csv(OUT / "key.csv", index=False)
    print(counts)                      # also recorded in README.md
    print(key["label"].value_counts().to_string())


if __name__ == "__main__":
    main()
