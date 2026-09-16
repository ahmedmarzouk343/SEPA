import json
import time
import datetime
import pickle
import os
import yfinance as yf
import pandas as pd
import numpy as np
from egx_tickers import TICKERS as ALL_TICKERS
from trend_template_test import compute_rs_percentile

from kashif_config import CONFIG_PATH
CACHE_DIR = r"C:\Users\Asuss\AppData\Local\Temp\claude\C--Users-Asuss-Stocks\f0ac14dd-1461-42d9-a6dc-d45e241f8230\scratchpad\egx_price_cache"
LOG_FILE = r"C:\Users\Asuss\AppData\Local\Temp\claude\C--Users-Asuss-Stocks\f0ac14dd-1461-42d9-a6dc-d45e241f8230\scratchpad\full_universe_run.log"
SLOPE_MIN_DURATION = 21
RS_THRESHOLD = 70
MIN_ROWS_REQUIRED = 260  # need > 252 to have at least 1 evaluable day for high/low/RS

os.makedirs(CACHE_DIR, exist_ok=True)

def log(msg):
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def load_hard_filter():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg["hard_filter"]

def fetch_all():
    """Fetch 2y daily history for every ticker, cache to disk, log failures. Resumable."""
    skipped = {}
    fetched_count = 0
    start = time.time()
    for i, tkr in enumerate(ALL_TICKERS, 1):
        cache_path = os.path.join(CACHE_DIR, f"{tkr}.pkl")
        if os.path.exists(cache_path):
            fetched_count += 1
            continue
        sym = f"{tkr}.CA"
        try:
            hist = yf.Ticker(sym).history(period="2y", interval="1d")
            if hist.index.tz is not None:
                hist.index = hist.index.tz_localize(None)
            n = len(hist)
            if n == 0:
                skipped[tkr] = "zero rows returned"
                log(f"[{i}/{len(ALL_TICKERS)}] {tkr}: SKIP (0 rows)")
            elif n < MIN_ROWS_REQUIRED:
                skipped[tkr] = f"only {n} rows (< {MIN_ROWS_REQUIRED} needed for any evaluable day)"
                log(f"[{i}/{len(ALL_TICKERS)}] {tkr}: SKIP ({n} rows, too thin)")
                with open(cache_path, "wb") as f:
                    pickle.dump(hist, f)  # cache anyway so we don't refetch on resume
            else:
                with open(cache_path, "wb") as f:
                    pickle.dump(hist, f)
                fetched_count += 1
                log(f"[{i}/{len(ALL_TICKERS)}] {tkr}: OK ({n} rows)")
        except Exception as e:
            skipped[tkr] = f"exception: {e}"
            log(f"[{i}/{len(ALL_TICKERS)}] {tkr}: SKIP (exception: {e})")
        time.sleep(1.5)

    elapsed = time.time() - start
    log(f"Fetch phase done. {fetched_count} usable, {len(skipped)} skipped/thin. Elapsed this run: {elapsed:.1f}s")
    return skipped

def load_cached():
    data = {}
    thin = {}
    for tkr in ALL_TICKERS:
        cache_path = os.path.join(CACHE_DIR, f"{tkr}.pkl")
        if not os.path.exists(cache_path):
            continue
        with open(cache_path, "rb") as f:
            hist = pickle.load(f)
        if len(hist) < MIN_ROWS_REQUIRED:
            thin[tkr] = len(hist)
            continue
        data[tkr] = hist
    return data, thin

def compute_indicators(df):
    out = df.copy()
    out["sma_50"] = out["Close"].rolling(50).mean()
    out["sma_150"] = out["Close"].rolling(150).mean()
    out["sma_200"] = out["Close"].rolling(200).mean()
    out["high_52wk"] = out["High"].rolling(252).max()
    out["low_52wk"] = out["Low"].rolling(252).min()
    out["sma_200_slope_ok"] = out["sma_200"] > out["sma_200"].shift(SLOPE_MIN_DURATION)
    out["ret_252"] = out["Close"] / out["Close"].shift(252) - 1
    return out

def main():
    hard_filter = load_hard_filter()
    log("=" * 70)
    log(f"Full-universe Trend Template test. {len(ALL_TICKERS)} tickers in list.")
    log("=" * 70)

    fetch_all()
    data_raw, thin = load_cached()
    log(f"Loaded {len(data_raw)} usable cached tickers ({len(thin)} thin/skipped).")

    log("Computing indicators for all usable tickers...")
    data = {tkr: compute_indicators(df) for tkr, df in data_raw.items()}

    # Build wide ret_252 table (different tickers may have slightly different
    # trading calendars/lengths; NaN where a ticker has no value that day)
    ret_wide = pd.DataFrame({tkr: data[tkr]["ret_252"] for tkr in data})
    log(f"ret_252 wide table shape: {ret_wide.shape}")

    # Cross-sectional percentile rank per day, via the SAME compute_rs_percentile()
    # used by trend_template_test.py (imported above) -- previously this script had
    # its own separate inline copy of this formula (na_option='keep'), while
    # trend_template_test.py's compute_rs_percentile() used a different, fragile
    # dropna(how="any") approach. Now unified on one canonical implementation
    # (na_option='keep' -- ranks per-day among whichever tickers have data that
    # day, rather than blanking an entire date because one ticker is missing)
    # so the two scripts can no longer silently drift apart.
    rs_pct = compute_rs_percentile(ret_wide)
    n_names_per_day = ret_wide.notna().sum(axis=1)
    log(f"Universe size for RS ranking ranges from {n_names_per_day.min()} to {n_names_per_day.max()} "
        f"names/day (median {int(n_names_per_day.median())}).")

    condition_ever_true = {c["id"]: False for c in hard_filter["conditions"]}
    results = {}
    all_pass_matrix = {}  # ticker -> boolean Series of all_pass, for the "typical day" report

    for tkr, df in data.items():
        df = df.copy()
        df["rs_percentile"] = rs_pct[tkr] if tkr in rs_pct.columns else np.nan

        cond = pd.DataFrame(index=df.index)
        cond["tt_1"] = df["Close"] > df["sma_150"]
        cond["tt_2"] = df["Close"] > df["sma_200"]
        cond["tt_3"] = df["sma_150"] > df["sma_200"]
        cond["tt_4"] = df["sma_200_slope_ok"]
        cond["tt_5"] = df["sma_50"] > df["sma_150"]
        cond["tt_6"] = df["sma_50"] > df["sma_200"]
        cond["tt_7"] = df["Close"] > df["sma_50"]
        cond["tt_8a"] = df["Close"] >= 1.30 * df["low_52wk"]
        cond["tt_8b"] = df["Close"] >= 0.75 * df["high_52wk"]
        cond["tt_9"] = df["rs_percentile"] >= RS_THRESHOLD

        raw_needed = df[["sma_150", "sma_200", "high_52wk", "low_52wk", "rs_percentile"]]
        evaluable = raw_needed.notna().all(axis=1)
        cond_eval = cond[evaluable]

        for cid in condition_ever_true:
            if cond_eval[cid].any():
                condition_ever_true[cid] = True

        all_pass = cond_eval.all(axis=1)
        all_pass_matrix[tkr] = all_pass

        segments = []
        in_seg = False
        seg_start = None
        prev_date = None
        for date, val in all_pass.items():
            if val and not in_seg:
                in_seg = True
                seg_start = date
            elif not val and in_seg:
                in_seg = False
                segments.append((seg_start, prev_date))
            prev_date = date
        if in_seg:
            segments.append((seg_start, prev_date))

        seg_info = []
        for s, e in segments:
            price_start = df.loc[s, "Close"]
            price_end = df.loc[e, "Close"]
            pct_change = (price_end / price_start - 1) * 100
            n_days = len(df.loc[s:e])
            seg_info.append({
                "start": s.date(), "end": e.date(), "n_days": n_days,
                "price_start": round(float(price_start), 2),
                "price_end": round(float(price_end), 2),
                "pct_change": round(float(pct_change), 1),
            })

        results[tkr] = {
            "n_evaluable_days": int(evaluable.sum()),
            "n_pass_days": int(all_pass.sum()),
            "segments": seg_info,
        }

    # Save everything needed for reporting
    with open(os.path.join(CACHE_DIR, "_results.pkl"), "wb") as f:
        pickle.dump({
            "results": results,
            "condition_ever_true": condition_ever_true,
            "all_pass_matrix": all_pass_matrix,
            "thin": thin,
            "n_names_per_day": n_names_per_day,
        }, f)

    log("Analysis complete. Results saved to _results.pkl")

    # quick top-line summary in the log
    total_pass_days = sum(r["n_pass_days"] for r in results.values())
    n_with_any_pass = sum(1 for r in results.values() if r["n_pass_days"] > 0)
    log(f"SUMMARY: {n_with_any_pass} / {len(results)} tickers had at least 1 passing day. "
        f"Total ticker-days passing across universe: {total_pass_days}")

if __name__ == "__main__":
    main()
