"""Quick diagnostic: would our filters have passed Minervini's disclosed stocks that
were OUTSIDE our old universe, on his dates? (Filters only -- not whether the
system would have chosen them among everything else; that is the full run.)

    python kashif_engine/scripts/minervini_quick_check.py

Uses a separate price folder and a temporary fundamentals store, so the real
data (being rebuilt concurrently) is untouched. SEC requests are throttled.
Output: backtest_results/experiment3/minervini_check/quick_check.csv
"""
import functools
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "us_fundamentals"))

from kashif_engine import panel as PANEL  # noqa: E402
from kashif_engine.data import prices as P  # noqa: E402

DIR = ROOT / "backtest_results" / "experiment3" / "minervini_check"
SCRATCH = Path(r"C:\Users\Asuss\AppData\Local\Temp\claude\C--Users-Asuss-Stocks"
               r"\075aac59-699e-4e45-89a0-4a34fe5578e8\scratchpad\quick_check")
ETF = {"XLE", "IBIT", "IWM", "IWN", "SPY", "DIA"}


def main():
    c = pd.read_csv(DIR / "comparison.csv")
    rows = c[c["action"].isin(["BUY", "HOLD"]) & ~c["ticker"].isin(ETF) & ~c["in_index_universe"]].copy()
    tickers = sorted(set(rows["ticker"].str.upper().str.replace(".", "-", regex=False)))
    print(f"{len(rows)} rows, {len(tickers)} tickers outside the old universe")

    # 1. prices: the main cache has the S&P 500 now; the rest go to a scratch cache.
    main_cache = P.CACHE_DIR
    missing = [t for t in tickers if not (main_cache / "US" / f"{t}.parquet").exists()]
    P.CACHE_DIR = SCRATCH / "prices"
    P.download(missing, start="2014-06-01", log=lambda *a: None)
    P.CACHE_DIR = main_cache

    def load(t):
        f = P.load(t)
        if f is None:
            P.CACHE_DIR = SCRATCH / "prices"
            f = P.load(t)
            P.CACHE_DIR = main_cache
        return f

    # 2. RS percentile vs the S&P 1500 cross-section: 252-day return rank.
    u = json.load(open(ROOT / "us_fundamentals" / "sp_universe.json"))
    ref = sorted(set(u["sp400"]) | set(u["sp600"]) | set(u.get("sp500", [])))
    closes = {}
    for t in ref:
        f = P.load(t)
        if f is not None and len(f):
            closes[t] = f["Close"]
    wide = pd.DataFrame(closes)
    ret252 = wide / wide.shift(252) - 1

    # 3. fundamentals: run the pipeline for these tickers into a temporary store.
    import merged_pipeline as MP
    import fundamentals_store as FS
    MP.SEC_DELAY = 0.4                                   # the main rebuild is using SEC too
    custom, et = MP.load_cached()
    frows = []
    for t in tickers:
        try:
            q, a, sh = MP.fetch_sec_full(t)
            MP.derive_q4(q, a, sh, t)
            r, _ = MP.reconcile_ticker(t, q, a, sh, custom, et)
            frows += r
        except Exception as e:  # noqa: BLE001
            print(f"  {t}: fundamentals ERROR {type(e).__name__}")
    MP.sanity_check(frows)
    fdf = pd.DataFrame(frows)
    store = SCRATCH / "store"
    if len(fdf):
        cols = ["ticker", "fiscal_quarter", "quarter_end_date", "revenue", "net_income", "eps",
                "earnings_release_date", "eps_conf"]
        out = fdf[[c_ for c_ in cols if c_ in fdf.columns]].copy()
        for c_ in ("quarter_end_date", "earnings_release_date"):
            out[c_] = pd.to_datetime(out[c_], errors="coerce")
        out = out.dropna(subset=["earnings_release_date"])
        import shutil
        shutil.rmtree(store, ignore_errors=True)
        out.to_parquet(store, partition_cols=["ticker"])
    from kashif_engine.data import fundamentals as F
    from kashif_engine.markets import US
    F.get_known_fundamentals = functools.partial(FS.get_known_fundamentals, parquet_root=store)
    F.get_known_history = functools.partial(FS.get_known_history, parquet_root=store)

    # 4. per disclosed row: best day within +-10 trading days of his date.
    res = []
    for r in rows.itertuples():
        t = r.ticker.upper().replace(".", "-")
        d0 = pd.Timestamp(str(r.date_or_period)[:10] if len(str(r.date_or_period)) >= 10
                          else str(r.date_or_period)[:7] + "-15")
        f = load(t)
        rec = {"ticker": t, "action": r.action, "date": r.date_or_period, "in_sp500": t in set(u.get("sp500", []))}
        if f is None or len(f.loc[:d0]) < 260:
            res.append(rec | {"note": "no/short price history"})
            continue
        fr = PANEL.ticker_frame(f)
        fr["high50_prev"] = fr["Close"].shift(1).rolling(50, min_periods=50).max()
        days = fr.index
        i0 = days.searchsorted(d0)
        best = None
        for d in days[max(i0 - 10, 0):i0 + 11]:
            tt = bool(fr.at[d, "tt_core"]) if fr.at[d, "tt_core"] == fr.at[d, "tt_core"] else False
            rs = float((ret252.loc[:d].iloc[-1] < fr.at[d, "ret_252"]).mean() * 100) if fr.at[d, "ret_252"] == fr.at[d, "ret_252"] else np.nan
            brk = bool(fr.at[d, "Close"] > fr.at[d, "high50_prev"] and fr.at[d, "vol_ratio"] >= 1.2)
            score = tt + (rs >= 70) + brk
            if best is None or score > best[0]:
                best = (score, d, tt, rs, brk)
        _, d, tt, rs, brk = best
        try:
            s = F.screen(t, d.date(), US)
            fund, why = s["verdict"], s["reason"]
        except Exception as e:  # noqa: BLE001
            fund, why = "ERROR", type(e).__name__
        from kashif_engine.strategies.minervini_sepa_v1.module import fund_score
        res.append(rec | {"check_day": str(d.date()), "trend_template": tt, "rs_pct_vs_sp1500": round(rs, 1),
                          "fundamentals_strict": fund, "fund_reason": str(why)[:70],
                          "fund_score_0_4": fund_score(fund, why), "breakout_50d_high": brk,
                          "passes_strict": bool(tt and rs >= 70 and fund == "PASS"),
                          "passes_rank_only": bool(tt and rs >= 70)})
    out = pd.DataFrame(res)
    out.to_csv(DIR / "quick_check.csv", index=False)
    ok = out.dropna(subset=["check_day"]) if "check_day" in out else out
    print(f"checked {len(ok)} of {len(out)} rows (others: no price history)")
    for col in ("trend_template", "breakout_50d_high", "passes_strict", "passes_rank_only"):
        print(f"  {col}: {int(ok[col].sum())}")
    print(f"  RS >= 70 vs S&P 1500: {int((ok['rs_pct_vs_sp1500'] >= 70).sum())}")
    print(f"  fundamentals strict PASS: {int((ok['fundamentals_strict'] == 'PASS').sum())}, "
          f"no data (foreign/20-F etc.): {int(ok['fundamentals_strict'].isin(['SKIP']).sum())}")
    print(out.to_string(index=False, max_colwidth=45))


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"{time.time() - t0:.0f}s")
