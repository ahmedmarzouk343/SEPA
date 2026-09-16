"""
JOB 1 — Automatic pre-backtest split correction for the EGX universe.

Yahoo's `.CA` feed does not back-adjust several EGX corporate actions, so a
handful of tickers carry a raw price cliff on the split date: the series drops
by the split factor overnight and every indicator that spans that date is
garbage — moving averages, the 52-week range in the Trend Template, VCP
contraction depths, and the largest-decline-since-entry term in the
distribution-bar exit all read a corporate action as a crash.

This module divides every price bar BEFORE the split date by the split factor,
which restores continuity without touching any post-split bar (so live
behaviour and recent history are unchanged).

It runs automatically from run_backtest.py on every future run — it is not a
one-time manual repair — and appends what it did to split_corrections_applied.log.

Choosing the ratio
------------------
Each entry records the closes actually observed on either side of the cliff.
The raw factor is prev_close / post_close, then snapped to the nearest value on
SPLIT_RATIO_LADDER in LOG space, not linear space: split ratios are
multiplicative, so 5.5 sits closer to 6 than to 5 the way a price series
experiences it. This matters for exactly one ticker — DCCC's factor is 5.500,
dead-centre between two ladder rungs under linear distance and unambiguous
under log distance.

Safety guard
------------
The correction is applied ONLY if the cliff is still present in the data as
fetched. If Yahoo later back-adjusts a ticker at source, applying a stored
correction on top would *create* the discontinuity it exists to remove, so a
ticker whose anchor bar no longer shows the drop is logged as SKIPPED and left
untouched.
"""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent
SPLIT_LOG_PATH = PROJECT_DIR / "split_corrections_applied.log"

# Plausible whole-number split ratios. A measured factor is snapped to the
# nearest rung; anything landing far from every rung is reported, not applied.
SPLIT_RATIO_LADDER = (1, 2, 3, 4, 5, 6, 8, 10, 12)

# A snapped ratio more than this far (in log space) from the measured factor is
# not a recognisable split. ln(1.25) — i.e. the snap may not move the factor by
# more than 25%.
MAX_SNAP_LOG_DISTANCE = math.log(1.25)

# Continuity bounds — identical to the scan thresholds in run_backtest.py, so a
# corrected series is one the split scan would no longer flag.
CONTINUITY_RATIO_HIGH = 3.0
CONTINUITY_RATIO_LOW = 1.0 / 3.0

# A genuine forward split multiplies the share count, so pre-split volume must
# be scaled up by the same factor or the split date shows a spurious N-fold
# volume spike — which is precisely what the breakout-volume gate
# (PIVOT_BREAKOUT_VOLUME_MULTIPLIER) and the volume-dry-up gate look for.
ADJUST_VOLUME = True

PRICE_COLUMNS = ("Open", "High", "Low", "Close", "Adj Close")

# ---------------------------------------------------------------------------
# The eight confirmed splits, from the Fix 3 scan of the 2022-08 -> 2025-08
# fetch window. `prev_close` / `post_close` are the observed closes either side
# of the cliff and are what the ratio is derived from; they also let the guard
# below confirm the cliff is still there before touching anything.
#
# COPR is deliberately absent: its 40.93 -> 0.61 print on 2023-07-05 is a 67:1
# ratio, off the ladder entirely and not a plausible corporate action. It is
# excluded from the universe in egx_tickers.py instead.
# ---------------------------------------------------------------------------
KNOWN_SPLITS = [
    {"ticker": "AMES", "date": "2024-04-30", "prev_close": 64.5200, "post_close": 8.0650},
    {"ticker": "ARAB", "date": "2024-05-07", "prev_close": 2.2000, "post_close": 0.3750},
    {"ticker": "CCRS", "date": "2025-03-02", "prev_close": 40.8200, "post_close": 3.3558},
    {"ticker": "COSG", "date": "2022-11-10", "prev_close": 0.7830, "post_close": 0.1410},
    {"ticker": "DCCC", "date": "2025-03-04", "prev_close": 9.3500, "post_close": 1.7000},
    {"ticker": "MFPC", "date": "2024-01-02", "prev_close": 411.8851, "post_close": 50.7876},
    {"ticker": "MHOT", "date": "2024-08-04", "prev_close": 118.3062, "post_close": 23.6612},
    {"ticker": "OCDI", "date": "2025-08-17", "prev_close": 61.0000, "post_close": 16.0000},
]


def snap_split_ratio(measured, ladder=SPLIT_RATIO_LADDER):
    """
    Snap a measured split factor to the nearest rung of `ladder`, minimising
    distance in LOG space.

    Returns (snapped_int, log_distance). A caller should reject the snap when
    log_distance > MAX_SNAP_LOG_DISTANCE.
    """
    m = float(measured)
    if not (m > 0):
        raise ValueError(f"split factor must be positive, got {measured!r}")
    lm = math.log(m)
    best = min(ladder, key=lambda r: abs(math.log(r) - lm))
    return int(best), abs(math.log(best) - lm)


def _anchor_position(index, date_str):
    """
    Position of the first bar on or after `date_str`. Returns None when the
    anchor falls outside the fetched window entirely, or lands on bar 0 (no
    pre-split bars to adjust).
    """
    anchor = pd.Timestamp(date_str)
    later = index[index >= anchor]
    if len(later) == 0:
        return None
    pos = index.get_loc(later[0])
    return pos if pos > 0 else None


def _observed_factor(df, pos):
    """prev_close / post_close across the anchor bar, or None if unusable."""
    try:
        prev = float(df["Close"].iloc[pos - 1])
        post = float(df["Close"].iloc[pos])
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    if not (prev > 0 and post > 0):
        return None
    return prev / post


def plan_correction(ticker, df, entry):
    """
    Decide what to do for one ticker without mutating anything.

    Returns a dict with `status` in:
      APPLIED-pending / SKIPPED_NO_ANCHOR / SKIPPED_ALREADY_ADJUSTED /
      SKIPPED_UNRECOGNISED_RATIO
    plus the diagnostic fields the log line is built from.
    """
    out = {
        "ticker": ticker,
        "date": entry["date"],
        "expected_prev": entry["prev_close"],
        "expected_post": entry["post_close"],
        "ratio": None,
        "measured": None,
        "snap_log_distance": None,
        "bars_adjusted": 0,
        "residual_ratio": None,
        "continuous": None,
        "status": None,
    }

    pos = _anchor_position(df.index, entry["date"])
    if pos is None:
        out["status"] = "SKIPPED_NO_ANCHOR"
        return out
    out["anchor_pos"] = pos
    out["anchor_date"] = str(df.index[pos].date())

    measured = _observed_factor(df, pos)
    if measured is None:
        out["status"] = "SKIPPED_NO_ANCHOR"
        return out
    out["measured"] = round(measured, 4)

    # Guard: the cliff must still be there. If the observed drop is already
    # inside the continuity band, the feed has been fixed upstream and applying
    # a stored ratio would introduce the very break we are removing.
    observed_drop = 1.0 / measured
    if observed_drop >= CONTINUITY_RATIO_LOW:
        out["status"] = "SKIPPED_ALREADY_ADJUSTED"
        return out

    ratio, dist = snap_split_ratio(measured)
    out["ratio"] = ratio
    out["snap_log_distance"] = round(dist, 4)
    if dist > MAX_SNAP_LOG_DISTANCE or ratio == 1:
        out["status"] = "SKIPPED_UNRECOGNISED_RATIO"
        return out

    out["bars_adjusted"] = pos
    out["residual_ratio"] = round(measured / ratio, 4)
    out["continuous"] = CONTINUITY_RATIO_LOW < (1.0 / out["residual_ratio"]) < CONTINUITY_RATIO_HIGH
    out["status"] = "APPLIED"
    return out


def apply_split_corrections(ticker, df, known_splits=KNOWN_SPLITS):
    """
    Return (corrected_df, [record, ...]) for one ticker.

    The input frame is never mutated; a copy is returned when anything changes
    and the original object is returned untouched when nothing does.
    """
    entries = [e for e in known_splits if e["ticker"] == ticker]
    if not entries or df is None or len(df) < 2:
        return df, []

    records = []
    out_df = df
    copied = False

    # Newest first, so an earlier split's adjustment does not shift the anchor
    # arithmetic of a later one.
    for entry in sorted(entries, key=lambda e: e["date"], reverse=True):
        plan = plan_correction(ticker, out_df, entry)
        records.append(plan)
        if plan["status"] != "APPLIED":
            continue

        if not copied:
            out_df = out_df.copy()
            copied = True

        pos = plan["anchor_pos"]
        ratio = plan["ratio"]
        for col in PRICE_COLUMNS:
            if col in out_df.columns:
                out_df.iloc[:pos, out_df.columns.get_loc(col)] = (
                    out_df[col].iloc[:pos] / ratio
                )
        if ADJUST_VOLUME and "Volume" in out_df.columns:
            out_df.iloc[:pos, out_df.columns.get_loc("Volume")] = (
                out_df["Volume"].iloc[:pos] * ratio
            )

        # Re-measure on the corrected frame — this is the continuity proof, not
        # the prediction made in plan_correction().
        actual = _observed_factor(out_df, pos)
        if actual:
            plan["residual_ratio"] = round(actual, 4)
            plan["continuous"] = CONTINUITY_RATIO_LOW < (1.0 / actual) < CONTINUITY_RATIO_HIGH

    return out_df, records


def format_record(rec):
    """One audit line per correction attempt."""
    if rec["status"] == "APPLIED":
        return (
            f"{rec['ticker']:<6} {rec['date']}  APPLIED   "
            f"ratio {rec['ratio']:>2}:1  measured {rec['measured']:>8.4f}  "
            f"bars_adjusted {rec['bars_adjusted']:>4}  "
            f"residual {rec['residual_ratio']:>7.4f}  "
            f"continuous={'YES' if rec['continuous'] else 'NO'}"
        )
    return (
        f"{rec['ticker']:<6} {rec['date']}  {rec['status']:<26} "
        f"measured {rec['measured'] if rec['measured'] is not None else 'n/a'}"
    )


def write_split_log(records, path=SPLIT_LOG_PATH, period=None):
    """Append this run's corrections to split_corrections_applied.log."""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    applied = [r for r in records if r["status"] == "APPLIED"]
    broken = [r for r in applied if not r["continuous"]]
    lines = [
        "=" * 78,
        f"RUN {stamp}" + (f"  period={period}" if period else ""),
        f"  volume_adjusted={ADJUST_VOLUME}  ladder={SPLIT_RATIO_LADDER}",
        f"  {len(applied)} applied / {len(records)} attempted"
        + (f"  ** {len(broken)} STILL DISCONTINUOUS **" if broken else ""),
        "-" * 78,
    ]
    lines += ["  " + format_record(r) for r in sorted(records, key=lambda r: r["ticker"])]
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path
