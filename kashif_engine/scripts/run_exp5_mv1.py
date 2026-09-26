"""Experiment 5 (MV1): momentum/volatility breakout portfolio.

Rules are frozen in backtest_results/experiment5/PREREGISTRATION.md (commit c2e5780).

    python kashif_engine/scripts/run_exp5_mv1.py prepare    # candidates + scores; cross-check; threshold T (pre-window only)
    python kashif_engine/scripts/run_exp5_mv1.py rehearse   # mechanics check on a development window (not a test)
    python kashif_engine/scripts/run_exp5_mv1.py test       # the one pre-registered run (2025-09-01..2026-09-24)
"""
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "kashif_engine" / "scripts"))
from kashif_engine import reports  # noqa: E402
from kashif_engine.data import prices as P  # noqa: E402
from kashif_engine.markets import US  # noqa: E402
import ai_judge_batches as J  # noqa: E402

MB = ROOT / "kashif_data" / "experiment2" / "model_book_dev"
OUT = ROOT / "kashif_data" / "experiment5"
RES = ROOT / "backtest_results" / "experiment5"
FRESH, WIN = 20, 250
PRE = ("2022-01-03", "2025-08-29")          # threshold T comes from here only
REHEARSAL = ("2024-09-03", "2025-08-29")    # mechanics check (development data, in-sample)
TEST = ("2025-09-01", "2026-09-24")         # the pre-registered window
CAPITAL, MAXPOS, HOLD, STOP = 100_000.0, 6, 60, 0.08
N_NULL = 500


# ------------------------------------------------------------------ candidates
def _fresh_qualified() -> pd.DataFrame:
    d = pd.read_parquet(MB / "days.parquet",
                        columns=["date", "ticker", "addv50", "liquid", "tt_ok", "rs70", "vr", "hi50_break"])
    d["q"] = d["liquid"].astype(bool) & d["tt_ok"] & d["rs70"] & (d["vr"] >= 1.2) & d["hi50_break"].astype(bool)
    cal = pd.DatetimeIndex(sorted(d["date"].unique()))
    pos = pd.Series(np.arange(len(cal)), index=cal)
    q = d[d["q"]].sort_values(["ticker", "date"]).copy()
    q["p"] = q["date"].map(pos)
    gap = q.groupby("ticker")["p"].diff()
    return q[gap.isna() | (gap > FRESH)][["date", "ticker", "addv50"]].reset_index(drop=True)


def _window_stats(df: pd.DataFrame, i: int) -> dict | None:
    if i + 1 < WIN + 49:                                   # 250 shown bars + 49 for the first 50-bar volume mean
        return None
    vol_rel = df["Volume"] / df["Volume"].rolling(50).mean()   # includes the bar itself (engine convention)
    g = pd.DataFrame({"high": df["High"], "low": df["Low"], "close": df["Close"], "vol_rel": vol_rel}).iloc[i - WIN + 1:i + 1]
    if g.isna().any().any():
        return None
    return J._stats8(g)


def score_model():
    """The experiment-4 Step-3 baseline, refitted by the same deterministic code on the
    293 Fork-4 samples dated before 2025-09-01."""
    k = J.step3_frame()
    pre = k[k.date < J.CLEAN_FROM]
    return J._logit_fit(pre[J.STATS8].to_numpy(float), pre.y.to_numpy()), k


def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    c = _fresh_qualified()
    rows, cache = [], {}
    for t, g in c.groupby("ticker"):
        df = cache.setdefault(t, P.load(t))
        idx = df.index
        for r in g.itertuples():
            if r.date not in idx:
                continue
            s = _window_stats(df, idx.get_loc(r.date))
            if s is not None:
                rows.append({"date": r.date, "ticker": t, "addv50": r.addv50, **s})
    x = pd.DataFrame(rows).sort_values(["date", "ticker"]).reset_index(drop=True)
    model, k = score_model()
    x["score"] = model(x[J.STATS8].to_numpy(float))

    # Cross-check: Fork 4's 505 samples, recomputed here from raw prices, must match its windows.
    kk = k[["ticker", "date"] + J.STATS8].merge(x[["ticker", "date"] + J.STATS8], on=["ticker", "date"],
                                                suffixes=("_f4", "_me"))
    worst = max(float(np.nanmax(np.abs(kk[s + "_f4"] - kk[s + "_me"]) / (np.abs(kk[s + "_f4"]) + 1e-9)))
                for s in J.STATS8)
    print(f"cross-check vs Fork 4 windows: {len(kk)}/{len(k)} samples matched; worst relative diff {worst:.2e}")

    pre = x[(x.date >= PRE[0]) & (x.date <= PRE[1])]
    T, T33 = float(pre.score.quantile(2 / 3)), float(pre.score.quantile(1 / 3))
    json.dump({"T": T, "T33": T33, "n_pre": len(pre)}, open(OUT / "threshold.json", "w"), indent=1)
    x.to_parquet(OUT / "candidates.parquet")
    print(f"fresh qualified breakouts with a full window: {len(x)} ({x.date.min().date()}..{x.date.max().date()})")
    print(f"T (67th pct of {len(pre)} pre-window scores) = {T:.6f};  T33 = {T33:.6f}")


# ------------------------------------------------------------------ simulator
class Book:
    """Prices for the needed tickers, aligned to the trading calendar."""

    def __init__(self, tickers, cal):
        self.cal = cal
        self.o, self.h, self.l, self.c = {}, {}, {}, {}
        for t in tickers:
            df = P.load(t).reindex(cal)
            self.o[t], self.h[t], self.l[t] = df["Open"].to_numpy(), df["High"].to_numpy(), df["Low"].to_numpy()
            self.c[t] = df["Close"].ffill().to_numpy()


def simulate(cands: pd.DataFrame, book: Book, prio: np.ndarray, stop: float | None = None):
    """cands: eligible signals (date, ticker, addv50); prio: higher = bought first."""
    cal = book.cal
    by_day = {}
    for (d, t, a), p in zip(cands[["date", "ticker", "addv50"]].itertuples(index=False), prio):
        by_day.setdefault(d, []).append((p, t, a))
    cash, pos, trades, curve = CAPITAL, {}, [], []
    prev_eq = CAPITAL
    last = len(cal) - 1
    for i, day in enumerate(cal):
        if i > 0:                                                    # entries at today's open
            for p, t, a in sorted(by_day.get(cal[i - 1], []), reverse=True):
                if len(pos) >= MAXPOS:
                    break
                o = book.o[t][i]
                if t in pos or not np.isfinite(o) or o <= 0:
                    continue
                budget = min(cash, prev_eq / MAXPOS)
                fill = o * (1 + US.slippage_bps(budget, a) / 1e4)
                n = int(budget // fill)
                while n > 0 and n * fill + US.commission(n, fill) > cash:
                    n -= 1
                if n <= 0:
                    continue
                cost = n * fill + US.commission(n, fill)
                cash -= cost
                pos[t] = {"n": n, "fill": fill, "cost": cost, "i": i, "addv": a,
                          "stop": fill * (1 - stop) if stop else None, "entry": day}
        for t in list(pos):                                          # stops, time exits, final close
            p = pos[t]
            px, why = None, None
            lo, op, cl = book.l[t][i], book.o[t][i], book.c[t][i]
            if p["stop"] is not None and np.isfinite(lo) and lo <= p["stop"]:
                px, why = (min(op, p["stop"]) if np.isfinite(op) else p["stop"]), "stop"
            elif i >= p["i"] + HOLD - 1 and np.isfinite(book.o[t][i]):
                px, why = cl, "time"
            elif i == last:
                px, why = cl, "window_end"
            if px is not None:
                fill = px * (1 - US.slippage_bps(p["n"] * px, p["addv"]) / 1e4)
                proceeds = p["n"] * fill - US.commission(p["n"], fill)
                cash += proceeds
                trades.append({"ticker": t, "entry": p["entry"], "exit": day, "reason": why,
                               "ret": proceeds / p["cost"] - 1})
                del pos[t]
        eq = cash + sum(p["n"] * book.c[t][i] for t, p in pos.items())
        curve.append((day, eq, cash))
        prev_eq = eq
    eq = pd.DataFrame(curve, columns=["date", "equity", "cash"]).set_index("date")
    return eq, pd.DataFrame(trades)


def metrics(eq: pd.DataFrame, tr: pd.DataFrame) -> dict:
    e = eq["equity"]
    return {"total_return": float(e.iloc[-1] / CAPITAL - 1),
            "max_drawdown": float((e / e.cummax() - 1).min()),
            "trades": int(len(tr)),
            "win_rate": float((tr.ret > 0).mean()) if len(tr) else float("nan"),
            "mean_trade": float(tr.ret.mean()) if len(tr) else float("nan"),
            "exposure": float(((eq.equity - eq.cash) / eq.equity).mean())}


def run(window, label, null=True):
    x = pd.read_parquet(OUT / "candidates.parquet")
    th = json.load(open(OUT / "threshold.json"))
    cal = P.load("MDY").loc[window[0]:window[1]].index
    w = x[(x.date >= cal[0]) & (x.date <= cal[-1])].reset_index(drop=True)
    book = Book(sorted(w.ticker.unique()), cal)
    top, bot = w[w.score >= th["T"]], w[w.score <= th["T33"]]
    out = {"window": [str(cal[0].date()), str(cal[-1].date())], "signals_all": len(w),
           "signals_top": len(top), "T": th["T"], "git_head": _git_head()}
    eq, tr = simulate(top, book, top.score.to_numpy())
    out["primary"] = metrics(eq, tr)
    eq_s, tr_s = simulate(top, book, top.score.to_numpy(), stop=STOP)
    out["variant_stop8"] = metrics(eq_s, tr_s)
    eq_b, tr_b = simulate(bot, book, bot.score.to_numpy())
    out["bottom_third"] = metrics(eq_b, tr_b)
    bm = reports.benchmark_curves(cal[0], cal[-1], universe=True)
    out["MDY_IJR_5050"] = float(bm["MDY_IJR_5050"].iloc[-1] / bm["MDY_IJR_5050"].iloc[0] - 1)
    out["EW_sp400_sp600"] = float(bm["EW_sp400_sp600_monthly"].iloc[-1] / bm["EW_sp400_sp600_monthly"].iloc[0] - 1)
    if null:
        nulls = []
        for seed in range(N_NULL):
            e_n, t_n = simulate(w, book, np.random.default_rng(seed).random(len(w)))
            nulls.append(metrics(e_n, t_n)["total_return"])
        nulls = np.array(nulls)
        out["null_median"] = float(np.median(nulls))
        out["null_p10_p90"] = [float(np.percentile(nulls, 10)), float(np.percentile(nulls, 90))]
        out["primary_pct_rank_in_null"] = float((nulls < out["primary"]["total_return"]).mean())
        out["verdict"] = ("PASS (worth a clean test; weak evidence on this window)"
                          if out["primary"]["total_return"] > out["MDY_IJR_5050"]
                          and out["primary"]["total_return"] > out["null_median"] else "FAIL (idea dropped)")
    RES.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(RES / f"{label}.json", "w"), indent=1)
    eq.join(bm[["MDY_IJR_5050"]]).to_csv(OUT / f"{label}_equity.csv")
    tr.to_csv(OUT / f"{label}_trades.csv", index=False)
    print(json.dumps(out, indent=1))


def _git_head():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True).stdout.strip()
    except OSError:
        return "?"


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "prepare":
        prepare()
    elif mode == "rehearse":
        run(REHEARSAL, "rehearsal_2024_09_2025_08", null=False)
    elif mode == "test":
        if (RES / "test_2025_09_2026_09.json").exists():
            sys.exit("The pre-registered test already ran once; it is not re-run.")
        run(TEST, "test_2025_09_2026_09")
