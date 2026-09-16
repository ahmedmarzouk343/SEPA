import json
import yfinance as yf
import pandas as pd
import numpy as np

from kashif_config import CONFIG_PATH
TICKERS = ["COMI", "TMGH", "SWDY", "HRHO", "ABUK"]
SYMBOLS = [f"{t}.CA" for t in TICKERS]
SLOPE_MIN_DURATION = 21  # tt_4 min_duration_days from config
RS_THRESHOLD = 70        # tt_9 threshold from config

def load_hard_filter():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg["hard_filter"]

def fetch_data(symbol):
    t = yf.Ticker(symbol)
    hist = t.history(period="2y", interval="1d")
    hist.index = hist.index.tz_localize(None) if hist.index.tz is not None else hist.index
    return hist

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

def evaluate_conditions(df, rs_percentile):
    """
    Evaluate all 10 hard_filter conditions (tt_1..tt_9, tt_8 split a/b) for one
    stock's indicator-augmented DataFrame (the output of compute_indicators()),
    given an externally-supplied cross-sectional RS percentile Series aligned to
    df.index (0-100 scale; NaN on any day it can't be computed).

    Returns (cond, evaluable, all_pass):
      cond      -- DataFrame of the 10 boolean tt_* columns, one per condition
      evaluable -- boolean Series, True where every needed raw indicator has
                   real (non-NaN) data that day
      all_pass  -- boolean Series, True only on evaluable days where every
                   condition passed (guaranteed False, never NaN, on
                   non-evaluable days -- see the NaN-comparison note below)

    Extracted out of main() so this exact logic (not a re-typed copy of it) can
    be exercised directly by the known-answer regression test.
    """
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
    cond["tt_9"] = rs_percentile >= RS_THRESHOLD

    # Only evaluate rows where every needed indicator has real data.
    # IMPORTANT: must check the RAW indicator columns for NaN, not the derived
    # boolean condition columns -- pandas/numpy comparisons against NaN resolve
    # to False, not NaN, so checking notna() on `cond` itself would silently
    # treat "insufficient history" rows as "evaluated and failed."
    raw_needed = df[["sma_150", "sma_200", "high_52wk", "low_52wk"]].copy()
    raw_needed["rs_percentile"] = rs_percentile
    evaluable = raw_needed.notna().all(axis=1)

    all_pass = cond.all(axis=1)
    return cond, evaluable, all_pass

def compute_rs_percentile(ret_wide):
    """
    Cross-sectional RS percentile ranking.

    ret_wide: DataFrame, one column per ticker, trailing-252-day returns.
    Returns a same-shaped DataFrame of 0-100 percentiles, ranked per-date
    among whichever tickers have valid data that day (na_option='keep' --
    a ticker's NaN stays NaN in the output and does not affect other
    tickers' ranks that day).

    CORRECTED: this function originally used dropna(how="any") (an inner
    join) -- a date was dropped entirely, for EVERY ticker, if even ONE
    ticker lacked a valid return that day. That's fine for this script's
    original 5-ticker test, where all 5 tickers happen to have complete,
    gap-free data across their whole evaluable range (confirmed empirically:
    switching to na_option='keep' and re-running this script reproduces
    byte-identical output -- there was nothing to drop either way). But it's
    a real, live discrepancy at production/full-universe scale: with ~224
    tickers, real-world data gaps (a thin/newly-listed stock, a suspension,
    a data-source hiccup) are near-certain somewhere in the universe on any
    given day, and dropna(how="any") would blank out RS percentile for
    EVERY ticker that day, not just the affected one -- silently shrinking
    the evaluable date range for the whole universe, potentially severely.
    trend_template_full_universe.py's separate inline RS computation
    already used na_option='keep' for exactly this reason; this function is
    now unified to match it (and that script now imports this function
    instead of duplicating its own copy), so there is one canonical RS
    percentile implementation instead of two that could silently drift
    apart.
    """
    return ret_wide.rank(axis=1, pct=True, method="average", na_option="keep") * 100

def main():
    hard_filter = load_hard_filter()
    print("=" * 70)
    print("HARD FILTER CONDITIONS READ FROM CONFIG:")
    for c in hard_filter["conditions"]:
        print(f"  {c['id']}: {c['rule']}" + (f"  [{c.get('note','')}]" if c.get("note") else ""))
    print(f"  logic: {hard_filter['logic']}")
    print("=" * 70)
    print()

    data = {}
    issues = []
    for tkr, sym in zip(TICKERS, SYMBOLS):
        hist = fetch_data(sym)
        n = len(hist)
        print(f"{tkr} ({sym}): {n} rows fetched, {hist.index.min().date()} -> {hist.index.max().date()}")
        if n == 0:
            issues.append(f"{tkr}: zero rows returned")
            continue
        # check for gaps beyond normal weekends (EGX trades Sun-Thu typically, but yfinance
        # just gives us whatever trading days it has -- flag large gaps as a sanity check)
        gaps = hist.index.to_series().diff().dt.days.dropna()
        big_gaps = gaps[gaps > 7]
        if len(big_gaps) > 0:
            issues.append(f"{tkr}: {len(big_gaps)} gap(s) > 7 calendar days in the price series "
                           f"(largest: {big_gaps.max()} days, around {big_gaps.idxmax().date()})")
        data[tkr] = compute_indicators(hist)

    print()

    # Build cross-sectional 252-day-return table for RS percentile. compute_rs_percentile()
    # ranks per-date among whichever tickers have data that day (na_option='keep'), so
    # rs_pct's row count is simply ret_df's full row count, not an "all tickers present"
    # filtered subset -- report both the full range and the all-5-present count separately
    # so this diagnostic stays accurate under that semantics.
    ret_df = pd.DataFrame({tkr: data[tkr]["ret_252"] for tkr in TICKERS if tkr in data})
    rs_pct = compute_rs_percentile(ret_df)
    n_all_five = ret_df.dropna(how="any").shape[0]
    print(f"RS percentile table: {len(rs_pct)} total dates in range, "
          f"{n_all_five} of which have valid 252-day return data for ALL 5 tickers simultaneously")
    if len(rs_pct) > 0:
        print(f"  Range: {rs_pct.index.min().date()} -> {rs_pct.index.max().date()}")
    print()

    condition_ever_true = {c["id"]: False for c in hard_filter["conditions"]}
    results = {}

    for tkr in TICKERS:
        df = data[tkr].copy()
        # attach RS percentile for this ticker on dates where it's computable
        df["rs_percentile"] = np.nan
        common_idx = df.index.intersection(rs_pct.index)
        df.loc[common_idx, "rs_percentile"] = rs_pct.loc[common_idx, tkr]

        cond, evaluable, all_pass = evaluate_conditions(df, df["rs_percentile"])
        cond_eval = cond[evaluable]
        all_pass = all_pass[evaluable]  # restrict to evaluable days, matching prior behavior

        for cid in condition_ever_true:
            if cond_eval[cid].any():
                condition_ever_true[cid] = True

        n_evaluable = len(cond_eval)
        n_pass = int(all_pass.sum())

        # find contiguous True segments
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
            "n_evaluable_days": n_evaluable,
            "n_pass_days": n_pass,
            "segments": seg_info,
        }

    print("=" * 70)
    print("RESULTS PER TICKER")
    print("=" * 70)
    for tkr in TICKERS:
        r = results[tkr]
        print(f"\n{tkr}: {r['n_pass_days']} / {r['n_evaluable_days']} evaluable days passed all conditions")
        if not r["segments"]:
            print("  No passing periods found.")
        for seg in r["segments"]:
            verdict = "UPTREND (confirms)" if seg["pct_change"] > 0 else "FLAT/DOWN (does NOT confirm)"
            print(f"  {seg['start']} -> {seg['end']}  ({seg['n_days']} days)  "
                  f"price {seg['price_start']} -> {seg['price_end']}  "
                  f"({seg['pct_change']:+.1f}%)  [{verdict}]")

    print()
    print("=" * 70)
    print("CONDITIONS THAT NEVER FIRED TRUE FOR ANY STOCK (on any evaluable day):")
    never_true = [cid for cid, ever in condition_ever_true.items() if not ever]
    if never_true:
        for cid in never_true:
            print(f"  {cid}")
    else:
        print("  (none -- every condition fired true at least once for at least one stock)")

    print()
    print("=" * 70)
    print("DATA ISSUES:")
    if issues:
        for i in issues:
            print(f"  - {i}")
    else:
        print("  (none detected)")

if __name__ == "__main__":
    main()
