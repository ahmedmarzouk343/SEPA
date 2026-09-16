# VCP Calibration — Exploratory Script Spec

*This is NOT Feature 5. This is a standalone calibration script whose only output
is charts and numbers a human looks at. Nothing in this script touches the main
pipeline. The goal is to find parameters that produce sane peaks on EGX before
writing any production code.*

---

## Why this exists

`scipy.signal.find_peaks` needs a prominence threshold — how large a swing must be
to count as a real structural peak vs. daily noise. A static number fails on EGX
because COMI and BELT have completely different noise profiles. This script answers
one question: what ATR multiplier and smoothing window produce peaks that match
what a trained eye would draw by hand on these specific EGX tickers?

Minervini's own process: identify the macro VCP structure on the **weekly** chart
first (the base's overall shape, contraction count, depth), then refine entry timing
on the **daily** chart. This script runs the same detection on both timeframes and
plots them side by side so we can see which one handles EGX noise better — and
whether the two timeframes agree on where the real structure is.

---

## Tickers

Four tickers chosen to cover the full EGX liquidity spectrum:

- **COMI** — large-cap, liquid, low noise
- **TMGH** — mid-cap, moderate liquidity
- **SWDY** — mid-cap, real base patterns already confirmed in prior testing
- **BELT** — high-volatility, thin liquidity (the stress test)

All four already have confirmed yfinance coverage (`SYMBOL.CA` format). No new
data source needed.

---

## Parameters — exposed as variables at the top of the script, never hardcoded

```python
# --- CALIBRATION PARAMETERS (adjust these, re-run, compare charts) ---
ATR_PERIOD        = 14      # ATR lookback window
ATR_MULTIPLIER    = 1.5     # prominence = ATR_MULTIPLIER × ATR(ATR_PERIOD)
SMOOTHING_WINDOW  = 5       # rolling median pre-smoothing, in trading days
DISTANCE_DAYS     = 5       # minimum bars between detected peaks (daily bars)
DISTANCE_WEEKS    = 2       # minimum bars between detected peaks (weekly bars)

TICKERS = ["COMI", "TMGH", "SWDY", "BELT"]
LOOKBACK_DAYS = 504         # ~2 years of daily data, same as the main pipeline
OUTPUT_DIR = "vcp_calibration_output"
```

These are **starting points, not decisions**. The whole point of running the script
is to find out if 1.5× is right, if 5-day smoothing is too aggressive or not enough,
and whether distance=5 or distance=10 better matches real EGX base structure.

---

## Detection logic — identical on both timeframes

Same function called twice per ticker. Not two different implementations.

```python
def detect_swings(price_series, high_series, low_series, close_series,
                  atr_period, atr_multiplier, smoothing_window, distance):
    """
    1. Compute ATR(atr_period) on the input series (handles both daily and weekly
       bars — pandas-ta's ATR works on any bar frequency)
    2. Smooth the close price with a rolling median of `smoothing_window` bars
       (median not mean — more robust to single-day thin-trading spikes)
    3. Run find_peaks on the SMOOTHED series with:
         prominence = atr_multiplier × ATR[-1]   (scalar, last bar's ATR value)
         distance   = distance                    (in bars, set per timeframe)
    4. For each detected peak index, record the ACTUAL high from the raw
       (unsmoothed) high_series — smoothing is only for detection, not measurement
    5. For troughs: invert the smoothed series, run find_peaks again with the
       same parameters
    6. Return: peak indices, trough indices, smoothed series, ATR series
    """
```

**Why median smoothing before detection**: thin EGX stocks can have days of zero
volume followed by a single large trade that moves price 5% in one day. That
spike is not a structural swing high. Rolling median removes it before find_peaks
sees the series, so the prominence threshold isn't inflated by noise accidents.
ATR alone doesn't protect against this because a spike day raises ATR too.

**Why raw prices for measurement**: the detected LOCATION comes from the smoothed
series (more reliable), but the actual contraction DEPTH is measured from the raw
high/low (what actually traded). These are different things.

---

## Weekly bars

```python
# Aggregate daily OHLCV to weekly — standard pandas resample
weekly = daily_df.resample('W').agg({
    'Open':   'first',
    'High':   'max',
    'Low':    'min',
    'Close':  'last',
    'Volume': 'sum'
}).dropna()
```

Run `detect_swings()` on the weekly DataFrame with `distance=DISTANCE_WEEKS`.
ATR is recomputed on weekly bars — pandas-ta handles this correctly without any
modification, since ATR only cares about the H/L/C values, not their frequency.

---

## Output per ticker — one figure, four panels

Save to `OUTPUT_DIR/TICKER_calibration.png`. Do not just `plt.show()` — saved
files can be reviewed without re-running.

```
Row 1, left:   DAILY — raw close price + smoothed close + detected peaks (▲) and
               troughs (▼) overlaid. Title: "Daily — ATR×{multiplier}, smooth={window}d"

Row 1, right:  WEEKLY — same layout on weekly bars.
               Title: "Weekly — ATR×{multiplier}, smooth={window}w"

Row 2, left:   DAILY ATR(14) over the same date range.
               Horizontal line at ATR_MULTIPLIER × mean(ATR) for reference.

Row 2, right:  WEEKLY ATR(14) over the same date range.

Row 3 (full width): Contraction depth sequence for each detected base on the
               DAILY bars. A "base" is a trough-to-peak-to-trough sequence.
               For each base: plot the depths of each contraction in order.
               A genuine VCP should show decreasing depths. Random noise should not.
               This panel is the clearest signal of whether the parameters are working.
```

---

## Text summary per ticker — printed to console AND saved to a .txt file

For each ticker, for each timeframe (daily / weekly):

```
COMI — Daily:
  Bars analyzed: 504
  Peaks found: 12
  Troughs found: 11
  Bases identified (trough→peak→trough): 8
  Contraction counts per base: [3, 2, 4, 2, 3, 2, 2, 3]  (target: 2–6 per book)
  Average contraction depth: 14.2%  (target: 10–35% per book)
  Deepest contraction: 28.4%
  Tightest final contraction: 4.1%
  ATR range over period: 2.3 – 6.8 EGP

COMI — Weekly:
  [same fields]
```

These numbers are what you use to calibrate. If "peaks found" is 40+ on a 2-year
daily series, the threshold is too loose. If it's 2–3, too tight. If the
"contraction counts per base" are all 1 (just one pullback per base), the distance
parameter is too large. The book says 2–6 contractions — that's the target range.

---

## What this script does NOT do

- Does not score or classify bases as "VCP" or "not VCP" — that's Feature 5
- Does not connect to the main pipeline in any way
- Does not use backtrader, the Sizer, or any Feature 1–4 code
- Does not make any trading decisions or generate signals
- Does not filter by the Trend Template — we want to see raw swing structure,
  not just Stage 2 stocks

---

## Success criterion

The script is "done" when a human looks at the four ticker charts side-by-side and
can answer yes to all of these:

1. Do the detected peaks and troughs on COMI match where you'd draw them by hand?
2. Does BELT (the thin, volatile ticker) have fewer false peaks than it would with
   a static threshold?
3. Do the weekly charts show cleaner, less noisy structure than the daily charts
   for the same tickers?
4. Are the contraction depth sequences for confirmed-good tickers (SWDY, COMI)
   showing the decreasing pattern the book describes?

If the answer to any of these is no, adjust the parameters at the top of the script
and re-run. The parameters are not committed until a human confirms the charts look
right.

---

## Files

- Input: existing yfinance data pull (same `SYMBOL.CA` format as the rest of the project)
- Output: `vcp_calibration_output/COMI_calibration.png`, `TMGH_calibration.png`,
  `SWDY_calibration.png`, `BELT_calibration.png`
- Output: `vcp_calibration_output/summary.txt`
- Script: `vcp_calibration_explorer.py`

No changes to any existing project file. Standalone only.

---

## Convention references

- `trend_template_test.py` — yfinance fetch pattern (`SYMBOL.CA`, `period="2y"`)
- `market_regime_gate.py` — pandas-ta ATR usage pattern
- `fundamentals_screen.py` — output structure / reporting style

---

## Change Log

- v1 — initial spec. Dual timeframe (daily + weekly resample), ATR-scaled dynamic
  prominence, rolling median pre-smoothing, four-panel chart per ticker, text
  summary with book-grounded target ranges for sanity checking.
