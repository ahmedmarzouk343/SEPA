"""
vcp_calibration_explorer.py -- standalone, calibration-only exploratory
script per vcp_calibration_spec.md (v1). NOT Feature 5. Produces charts and
numbers a human looks at to decide if ATR-scaled peak detection parameters
make sense on real EGX tickers before any production code gets written.

Does NOT touch the main pipeline, backtrader, the Sizer, or any Feature 1-4
code. Does NOT score or classify bases as "VCP" or "not VCP" (Feature 5's
job) and does NOT filter by the Trend Template -- this looks at raw swing
structure on every ticker regardless of Stage 2 status.

--------------------------------------------------------------------------
TWO DEVIATIONS FROM THE SPEC, both flagged rather than silently resolved
--------------------------------------------------------------------------
1. TICKER SUBSTITUTION: the spec's 4th ticker, "BELT", is not a real
   yfinance symbol -- confirmed empirically (yf.Ticker("BELT.CA").history()
   returns a 404 "Quote not found"), and BELT does not appear anywhere in
   egx_tickers.py's 224-ticker confirmed EGX universe either. Per the task's
   own explicit fallback instruction, the universe was screened for the
   next most volatile, thinnest-liquidity CONFIRMED ticker instead:
     - Bulk-screened 212 candidate tickers (egx_tickers.py minus COMI/TMGH/
       SWDY and the familiar large-cap names) over 6mo of daily data,
       ranking by annualized return volatility (high) combined with average
       daily EGP dollar volume (low).
     - Top-ranked candidate, EGBE, was REJECTED after inspection: its
       history contains negative Close prices (a data-quality artifact,
       most likely a bad split/redenomination adjustment upstream in
       yfinance -- not a real, tradeable price series). Volatility computed
       from a series that crosses zero is meaningless, so it was excluded
       rather than used.
     - Next-ranked candidate, TRTO, was inspected and confirmed clean: 490
       bars of real 2-year history (close to LOOKBACK_DAYS=504, no negative
       or zero prices), price range 0.030-0.051 EGP (a genuine EGX penny
       stock), median daily volume ~11,400 shares with real zero-volume
       days, and a real ~43% single-week price move on a volume spike late
       in the series -- matches the "high-volatility, thin liquidity, the
       stress test" role the spec described for BELT. TRTO.CA is used in
       its place. See TICKERS below.

2. pandas-ta: the spec's Convention References cite market_regime_gate.py
   for "pandas-ta usage pattern" -- checked, and that file contains NO
   pandas-ta usage at all (only json/numpy/pandas; pandas_ta was not even
   installed in this environment before this script). Considerations.md's
   own Tech Stack section (Section 2) does specify pandas-ta as the
   intended library for exactly this ("volatility indicators like ATR"),
   so it was installed fresh here (pandas_ta 0.4.71b0, the actively
   maintained fork -- NOT the abandoned original 0.3.14b0 that breaks on
   numpy>=2.0's removed numpy.NaN) and ATR is implemented directly against
   its documented API, not copied from an existing project pattern that
   turned out not to exist. Installing it pulled numpy down from 2.5.2 to
   2.2.6 as a dependency resolution -- the full existing regression suite
   (test_trend_template_known_answer.py, test_trend_template_test_A/B.py,
   test_fundamentals_screen_known_answer.py,
   test_market_regime_gate_known_answer.py, test_feature4_known_answer.py)
   was re-run against the downgraded numpy and confirmed zero regressions
   before this script was written.

--------------------------------------------------------------------------
CALIBRATION PARAMETERS -- adjust these, re-run, compare charts in
OUTPUT_DIR. These are STARTING POINTS, not decisions (spec's own framing).
--------------------------------------------------------------------------
"""

import os

import numpy as np
import pandas as pd
import yfinance as yf
import pandas_ta as ta
import matplotlib

matplotlib.use("Agg")  # headless -- this script saves files, never plt.show()
import matplotlib.pyplot as plt  # noqa: E402
from scipy.signal import find_peaks  # noqa: E402

# --- CALIBRATION PARAMETERS (adjust these, re-run, compare charts) ---
ATR_PERIOD = 14  # ATR lookback window
ATR_MULTIPLIER = 1.0  # prominence = ATR_MULTIPLIER x ATR(ATR_PERIOD)  [2nd pass: was 1.5]
SMOOTHING_WINDOW = 5  # rolling median pre-smoothing, in trading days
DISTANCE_DAYS = 3  # minimum bars between detected peaks (daily bars)  [2nd pass: was 5]
DISTANCE_WEEKS = 2  # minimum bars between detected peaks (weekly bars)

# TRTO substituted for the spec's "BELT" (not a real yfinance symbol -- see
# module docstring deviation #1 above).
TICKERS = ["COMI", "TMGH", "SWDY", "TRTO"]
LOOKBACK_DAYS = 504  # ~2 years of daily data, same as the main pipeline
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vcp_calibration_output")

# Book-grounded target ranges (feature-04/Considerations.md's own VCP
# framing) -- used only for the printed sanity-check summary, never to
# filter or reject anything here.
BOOK_CONTRACTION_COUNT_RANGE = (2, 6)
BOOK_CONTRACTION_DEPTH_RANGE = (0.10, 0.35)


# ==========================================================================
# Data fetching
# ==========================================================================

def fetch_daily(ticker):
    """
    Same yfinance fetch pattern as trend_template_test.py: SYMBOL.CA,
    period="2y". Trimmed to the last LOOKBACK_DAYS rows so the printed
    "Bars analyzed" figure is exact and comparable across tickers, rather
    than however many rows yfinance's "2y" period happens to return (thin
    tickers like TRTO can come back with fewer than 504 even over a full
    2-year window, since there simply weren't 504 trading days with a
    price print).
    """
    symbol = f"{ticker}.CA"
    t = yf.Ticker(symbol)
    hist = t.history(period="2y", interval="1d")
    hist.index = hist.index.tz_localize(None) if hist.index.tz is not None else hist.index
    hist = hist.dropna(subset=["Open", "High", "Low", "Close"])
    if len(hist) > LOOKBACK_DAYS:
        hist = hist.tail(LOOKBACK_DAYS)
    return hist


def to_weekly(daily_df):
    """Standard pandas resample, per spec Section 'Weekly bars'."""
    weekly = daily_df.resample("W").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }).dropna()
    return weekly


# ==========================================================================
# Detection logic -- IDENTICAL function called on both daily and weekly
# bars (spec's central requirement: not two separate implementations).
# ==========================================================================

def detect_swings(price_series, high_series, low_series, close_series,
                   atr_period, atr_multiplier, smoothing_window, distance):
    """
    1. ATR(atr_period) via pandas_ta -- works on any bar frequency, since it
       only depends on H/L/C values, not their timeframe.
    2. Smooth the close price with a rolling median of `smoothing_window`
       bars (median, not mean -- more robust to single-day thin-trading
       price spikes, per spec).
    3. find_peaks() on the SMOOTHED series: prominence = atr_multiplier x
       ATR[-1] (scalar, the last bar's ATR value), distance = distance.
    4. For each detected peak/trough index, the LOCATION comes from the
       smoothed series, but callers must measure actual DEPTH from the raw
       high_series/low_series -- this function returns both so that
       distinction is preserved, not collapsed here.
    5. Troughs: find_peaks() on the INVERTED smoothed series, same params.

    Returns: peak_idx (np.ndarray), trough_idx (np.ndarray),
             smoothed (pd.Series), atr (pd.Series)

    `price_series` is accepted per the spec's declared signature but not
    used directly -- detection runs on close_series (smoothed), matching
    the spec's own detect_swings() docstring ("smooth the close price").
    Kept as a parameter so the function signature matches the spec exactly
    (flagged here rather than silently dropped).
    """
    atr = ta.atr(high_series, low_series, close_series, length=atr_period)
    smoothed = close_series.rolling(smoothing_window, min_periods=1).median()

    last_atr = atr.iloc[-1]
    if pd.isna(last_atr) or last_atr <= 0:
        # Not enough history yet for a real ATR reading -- fail closed
        # (no peaks/troughs) rather than let prominence=NaN silently
        # disable the threshold and return every noise wiggle as a peak.
        empty = np.array([], dtype=int)
        return empty, empty, smoothed, atr

    prominence = atr_multiplier * last_atr
    values = smoothed.values

    peak_idx, _ = find_peaks(values, prominence=prominence, distance=distance)
    trough_idx, _ = find_peaks(-values, prominence=prominence, distance=distance)

    return peak_idx, trough_idx, smoothed, atr


# ==========================================================================
# Base / contraction identification (calibration-only heuristic -- NOT
# Feature 5's VCP classifier, just enough structure to eyeball whether
# depths decrease within a base, per spec Row 3 requirement)
# ==========================================================================

def build_swing_sequence(peak_idx, trough_idx):
    """
    Merge peak and trough indices into one time-ordered, strictly
    alternating sequence of ('P', idx) / ('T', idx) tuples. If two
    same-type points occur consecutively (both detectors can occasionally
    fire back to back near the smoothing window's edge), keep only the
    more extreme one of that pair -- the higher peak, or the lower trough
    -- since that is the one that actually defines the swing.
    """
    points = [("P", i) for i in peak_idx] + [("T", i) for i in trough_idx]
    points.sort(key=lambda p: p[1])

    cleaned = []
    for kind, idx in points:
        if cleaned and cleaned[-1][0] == kind:
            cleaned.pop()
        cleaned.append((kind, idx))
    return cleaned


def identify_contractions(swing_seq, raw_high, raw_low):
    """
    Walk consecutive PEAK -> TROUGH pairs in the swing sequence. Each pair
    is one "contraction": depth = (peak_high - trough_low) / peak_high,
    measured from the RAW (unsmoothed) high/low series at the detected
    indices -- per spec, detected LOCATION comes from the smoothed series,
    but measured DEPTH comes from raw prices (these are different things).

    Returns a list of dicts: {peak_idx, trough_idx, depth}, in time order.
    """
    contractions = []
    for (kind1, idx1), (kind2, idx2) in zip(swing_seq, swing_seq[1:]):
        if kind1 == "P" and kind2 == "T":
            peak_high = raw_high.iloc[idx1]
            trough_low = raw_low.iloc[idx2]
            if peak_high > 0:
                depth = (peak_high - trough_low) / peak_high
                contractions.append({"peak_idx": idx1, "trough_idx": idx2, "depth": depth})
    return contractions


def group_into_bases(contractions, raw_high):
    """
    Groups the flat contraction list into "bases" (spec: "a base is a
    trough-to-peak-to-trough sequence"). A calibration-only heuristic, not
    Feature 5's classifier: a new base starts whenever a contraction's peak
    makes a fresh high ABOVE the current base's own starting peak -- i.e.
    price broke out above where this base began, so the prior base is
    considered resolved and a new one begins from the breakout peak. This
    is the natural "base ends at a new high, next base starts there"
    reading of the spec's definition; it is not asserted to be Feature 5's
    eventual, more rigorous base-boundary algorithm.

    Returns a list of bases, each a list of contraction dicts (in order).
    """
    if not contractions:
        return []

    bases = [[contractions[0]]]
    base_reference_high = raw_high.iloc[contractions[0]["peak_idx"]]

    for c in contractions[1:]:
        this_peak_high = raw_high.iloc[c["peak_idx"]]
        if this_peak_high > base_reference_high:
            bases.append([c])
            base_reference_high = this_peak_high
        else:
            bases[-1].append(c)

    return bases


# ==========================================================================
# Summary statistics
# ==========================================================================

def summarize(ticker, timeframe_label, bars_df, peak_idx, trough_idx, atr, bases):
    all_depths = [c["depth"] for base in bases for c in base]
    counts_per_base = [len(base) for base in bases]
    final_depths_per_base = [base[-1]["depth"] for base in bases if base]

    lines = []
    lines.append(f"{ticker} -- {timeframe_label}:")
    lines.append(f"  Bars analyzed: {len(bars_df)}")
    lines.append(f"  Peaks found: {len(peak_idx)}")
    lines.append(f"  Troughs found: {len(trough_idx)}")
    lines.append(f"  Bases identified (trough->peak->trough): {len(bases)}")
    if counts_per_base:
        lines.append(f"  Contraction counts per base: {counts_per_base}  "
                      f"(target: {BOOK_CONTRACTION_COUNT_RANGE[0]}-{BOOK_CONTRACTION_COUNT_RANGE[1]} per book)")
    else:
        lines.append("  Contraction counts per base: [] (no bases identified)")
    if all_depths:
        avg_depth = float(np.mean(all_depths))
        deepest = float(np.max(all_depths))
        lines.append(f"  Average contraction depth: {avg_depth:.1%}  "
                      f"(target: {BOOK_CONTRACTION_DEPTH_RANGE[0]:.0%}-{BOOK_CONTRACTION_DEPTH_RANGE[1]:.0%} per book)")
        lines.append(f"  Deepest contraction: {deepest:.1%}")
    else:
        lines.append("  Average contraction depth: n/a (no contractions identified)")
        lines.append("  Deepest contraction: n/a")
    if final_depths_per_base:
        tightest_final = float(np.min(final_depths_per_base))
        lines.append(f"  Tightest final contraction: {tightest_final:.1%}")
    else:
        lines.append("  Tightest final contraction: n/a")
    atr_valid = atr.dropna()
    if len(atr_valid):
        # [CORRECTED -- display bug caught by running this on TRTO] a fixed
        # .2f format silently rounds a thin, low-absolute-price ticker's real
        # ATR (e.g. TRTO's ~0.0004-0.0028 EGP) down to "0.00 - 0.00", which
        # reads as "ATR is zero" -- misleading for exactly the kind of
        # ticker this calibration is meant to stress-test. Precision now
        # scales with the ATR values themselves instead of a blanket 2dp.
        atr_min, atr_max = atr_valid.min(), atr_valid.max()
        decimals = 2 if atr_max >= 1 else 4
        lines.append(f"  ATR range over period: {atr_min:.{decimals}f} - {atr_max:.{decimals}f} EGP")
    else:
        lines.append("  ATR range over period: n/a (insufficient history)")

    return "\n".join(lines)


# ==========================================================================
# Plotting -- one figure per ticker, four panels, saved to OUTPUT_DIR
# ==========================================================================

def plot_ticker(ticker, daily_df, weekly_df,
                 d_peak_idx, d_trough_idx, d_smoothed, d_atr, d_bases,
                 w_peak_idx, w_trough_idx, w_smoothed, w_atr):
    fig = plt.figure(figsize=(16, 12))
    gs = fig.add_gridspec(3, 2, height_ratios=[2, 1, 1.2])

    # --- Row 1: price + smoothed + peaks/troughs, daily (left) / weekly (right) ---
    ax_d_price = fig.add_subplot(gs[0, 0])
    ax_d_price.plot(daily_df.index, daily_df["Close"], color="#888888", lw=0.8, label="raw close")
    ax_d_price.plot(daily_df.index, d_smoothed, color="#1f77b4", lw=1.3, label=f"smoothed ({SMOOTHING_WINDOW}d median)")
    if len(d_peak_idx):
        ax_d_price.scatter(daily_df.index[d_peak_idx], daily_df["High"].iloc[d_peak_idx],
                            marker="^", color="#2ca02c", s=60, zorder=5, label="peak")
    if len(d_trough_idx):
        ax_d_price.scatter(daily_df.index[d_trough_idx], daily_df["Low"].iloc[d_trough_idx],
                            marker="v", color="#d62728", s=60, zorder=5, label="trough")
    ax_d_price.set_title(f"Daily -- ATR x{ATR_MULTIPLIER}, smooth={SMOOTHING_WINDOW}d")
    ax_d_price.legend(loc="upper left", fontsize=8)

    ax_w_price = fig.add_subplot(gs[0, 1])
    ax_w_price.plot(weekly_df.index, weekly_df["Close"], color="#888888", lw=0.8, label="raw close")
    ax_w_price.plot(weekly_df.index, w_smoothed, color="#1f77b4", lw=1.3, label=f"smoothed ({SMOOTHING_WINDOW}w median)")
    if len(w_peak_idx):
        ax_w_price.scatter(weekly_df.index[w_peak_idx], weekly_df["High"].iloc[w_peak_idx],
                            marker="^", color="#2ca02c", s=60, zorder=5, label="peak")
    if len(w_trough_idx):
        ax_w_price.scatter(weekly_df.index[w_trough_idx], weekly_df["Low"].iloc[w_trough_idx],
                            marker="v", color="#d62728", s=60, zorder=5, label="trough")
    ax_w_price.set_title(f"Weekly -- ATR x{ATR_MULTIPLIER}, smooth={SMOOTHING_WINDOW}w")
    ax_w_price.legend(loc="upper left", fontsize=8)

    # --- Row 2: ATR, daily (left) / weekly (right) ---
    ax_d_atr = fig.add_subplot(gs[1, 0])
    ax_d_atr.plot(daily_df.index, d_atr, color="#ff7f0e", lw=1.0)
    d_atr_mean = d_atr.dropna().mean()
    if pd.notna(d_atr_mean):
        ax_d_atr.axhline(ATR_MULTIPLIER * d_atr_mean, color="#666666", ls="--", lw=1.0,
                          label=f"{ATR_MULTIPLIER}x mean ATR")
        ax_d_atr.legend(loc="upper left", fontsize=8)
    ax_d_atr.set_title(f"Daily ATR({ATR_PERIOD})")

    ax_w_atr = fig.add_subplot(gs[1, 1])
    ax_w_atr.plot(weekly_df.index, w_atr, color="#ff7f0e", lw=1.0)
    ax_w_atr.set_title(f"Weekly ATR({ATR_PERIOD})")

    # --- Row 3: contraction depth sequence per base, daily bars ---
    ax_depth = fig.add_subplot(gs[2, :])
    if d_bases:
        cmap = plt.get_cmap("tab10")
        for i, base in enumerate(d_bases):
            depths_pct = [c["depth"] * 100 for c in base]
            xs = list(range(1, len(depths_pct) + 1))
            ax_depth.plot(xs, depths_pct, marker="o", color=cmap(i % 10),
                          label=f"base {i+1} ({base[0]['peak_idx']}->{base[-1]['trough_idx']})")
        ax_depth.axhspan(BOOK_CONTRACTION_DEPTH_RANGE[0] * 100, BOOK_CONTRACTION_DEPTH_RANGE[1] * 100,
                          color="#2ca02c", alpha=0.08, label="book target 10-35%")
        ax_depth.set_xlabel("contraction # within base")
        ax_depth.set_ylabel("depth (%)")
        ax_depth.legend(loc="upper right", fontsize=7, ncol=2)
    else:
        ax_depth.text(0.5, 0.5, "No bases identified with current parameters",
                       ha="center", va="center", transform=ax_depth.transAxes)
    ax_depth.set_title("Contraction depth sequence per base (daily) -- should decrease for a genuine VCP")

    fig.suptitle(f"{ticker} -- VCP calibration", fontsize=14, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.97])

    out_path = os.path.join(OUTPUT_DIR, f"{ticker}_calibration.png")
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


# ==========================================================================
# Main
# ==========================================================================

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    summary_lines = []
    summary_lines.append("VCP Calibration Summary")
    summary_lines.append(f"Parameters: ATR_PERIOD={ATR_PERIOD}, ATR_MULTIPLIER={ATR_MULTIPLIER}, "
                          f"SMOOTHING_WINDOW={SMOOTHING_WINDOW}, DISTANCE_DAYS={DISTANCE_DAYS}, "
                          f"DISTANCE_WEEKS={DISTANCE_WEEKS}")
    summary_lines.append(f"Tickers: {TICKERS} (TRTO substituted for spec's BELT -- see script docstring)")
    summary_lines.append("=" * 70)

    for ticker in TICKERS:
        print(f"--- {ticker} ---")
        try:
            daily_df = fetch_daily(ticker)
        except Exception as e:  # noqa: BLE001
            msg = f"{ticker}: FETCH FAILED -- {e}"
            print(msg)
            summary_lines.append(msg)
            summary_lines.append("")
            continue

        if daily_df.empty or len(daily_df) < ATR_PERIOD + SMOOTHING_WINDOW:
            msg = f"{ticker}: INSUFFICIENT DATA ({len(daily_df)} bars) -- skipping"
            print(msg)
            summary_lines.append(msg)
            summary_lines.append("")
            continue

        weekly_df = to_weekly(daily_df)

        d_peak_idx, d_trough_idx, d_smoothed, d_atr = detect_swings(
            daily_df["Close"], daily_df["High"], daily_df["Low"], daily_df["Close"],
            ATR_PERIOD, ATR_MULTIPLIER, SMOOTHING_WINDOW, DISTANCE_DAYS,
        )
        w_peak_idx, w_trough_idx, w_smoothed, w_atr = detect_swings(
            weekly_df["Close"], weekly_df["High"], weekly_df["Low"], weekly_df["Close"],
            ATR_PERIOD, ATR_MULTIPLIER, DISTANCE_WEEKS, DISTANCE_WEEKS,
        )
        # NOTE: weekly smoothing_window intentionally reuses DISTANCE_WEEKS's
        # scale (2 weeks), not SMOOTHING_WINDOW (5, a DAILY-bar count) -- see
        # module docstring note below main() for why a separate weekly
        # smoothing constant is flagged as a follow-up, not invented here.

        d_swing_seq = build_swing_sequence(d_peak_idx, d_trough_idx)
        d_contractions = identify_contractions(d_swing_seq, daily_df["High"], daily_df["Low"])
        d_bases = group_into_bases(d_contractions, daily_df["High"])

        w_swing_seq = build_swing_sequence(w_peak_idx, w_trough_idx)
        w_contractions = identify_contractions(w_swing_seq, weekly_df["High"], weekly_df["Low"])
        w_bases = group_into_bases(w_contractions, weekly_df["High"])

        out_path = plot_ticker(
            ticker, daily_df, weekly_df,
            d_peak_idx, d_trough_idx, d_smoothed, d_atr, d_bases,
            w_peak_idx, w_trough_idx, w_smoothed, w_atr,
        )
        print(f"  chart saved: {out_path}")

        daily_summary = summarize(ticker, "Daily", daily_df, d_peak_idx, d_trough_idx, d_atr, d_bases)
        weekly_summary = summarize(ticker, "Weekly", weekly_df, w_peak_idx, w_trough_idx, w_atr, w_bases)
        print(daily_summary)
        print(weekly_summary)
        summary_lines.append(daily_summary)
        summary_lines.append("")
        summary_lines.append(weekly_summary)
        summary_lines.append("")

    summary_path = os.path.join(OUTPUT_DIR, "summary.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(summary_lines) + "\n")
    print(f"\nSummary written to: {summary_path}")


# NOTE on weekly smoothing window (flagged, not silently decided): the spec
# gives SMOOTHING_WINDOW=5 with the comment "in trading days" and a separate
# DISTANCE_WEEKS=2 for the weekly find_peaks() distance, but never defines a
# distinct smoothing-window constant for weekly bars. Reusing SMOOTHING_WINDOW
# (5) as a 5-WEEK median on weekly bars would smooth over ~35 trading days,
# far more aggressively than intended relative to the daily case's 5-DAY
# median. This script instead reuses DISTANCE_WEEKS (2) as the weekly
# smoothing window -- a 2-week median -- since it is at least dimensionally
# a "weeks" constant already exposed at the top of the file, not a value
# invented fresh here. This is a genuine open parameter a human should
# revisit when comparing the weekly charts (spec success criterion #3): if
# the weekly panel looks over- or under-smoothed, add a dedicated
# SMOOTHING_WINDOW_WEEKS constant rather than continuing to borrow DISTANCE_WEEKS.


if __name__ == "__main__":
    main()
