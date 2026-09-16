"""
Known-answer tests for JOB 1 — automatic split correction (split_corrections.py)
and the COPR bad-data exclusion (egx_tickers.py).

Predictions were hand-derived from the ratio table BEFORE running, in the usual
discipline for this repo. Each fixture states its prediction in the docstring.
"""

import numpy as np
import pandas as pd
import pytest

from egx_tickers import BAD_DATA_TICKERS, EXCLUDED_TICKERS, VALID_TICKERS, ZERO_DATA_TICKERS
from split_corrections import (
    ADJUST_VOLUME,
    CONTINUITY_RATIO_HIGH,
    CONTINUITY_RATIO_LOW,
    KNOWN_SPLITS,
    apply_split_corrections,
    snap_split_ratio,
)

TOL = 1e-9


def make_series(n_pre, n_post, pre_price, split_factor, start="2024-01-01", volume=1000):
    """
    Build a flat OHLCV frame with an unadjusted split: `n_pre` bars at
    `pre_price`, then `n_post` bars at pre_price / split_factor. Volume is flat
    at `volume` before the split and volume * split_factor after, which is what
    a raw (unadjusted) feed shows for a genuine forward split.
    """
    idx = pd.bdate_range(start, periods=n_pre + n_post)
    post_price = pre_price / split_factor
    close = np.array([pre_price] * n_pre + [post_price] * n_post, dtype=float)
    vol = np.array([volume] * n_pre + [volume * split_factor] * n_post, dtype=float)
    return pd.DataFrame(
        {"Open": close, "High": close, "Low": close, "Close": close, "Volume": vol},
        index=idx,
    )


# ---------------------------------------------------------------------------
# Fixture 1 — ladder snapping, log-space
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "measured, expected",
    [
        (8.0000, 8),    # AMES  — exact rung
        (5.8667, 6),    # ARAB
        (12.1640, 12),  # CCRS
        (5.5532, 6),    # COSG  — 5.55, log-nearer 6
        (5.5000, 6),    # DCCC  — dead centre in LINEAR space, 6 in LOG space
        (8.1100, 8),    # MFPC
        (5.0000, 5),    # MHOT  — exact rung, confirmed 5:1
        (3.8125, 4),    # OCDI
    ],
)
def test_f1_snap_split_ratio(measured, expected):
    """PREDICTION: each measured factor snaps to the ladder rung above."""
    ratio, _ = snap_split_ratio(measured)
    assert ratio == expected


def test_f1b_log_tiebreak_beats_linear():
    """
    PREDICTION: 5.5 is equidistant from 5 and 6 under linear distance, so the
    choice is only well-defined in log space, where 6 wins (|ln 5.5 - ln 6| =
    0.0870 < |ln 5.5 - ln 5| = 0.0953). This is the DCCC case and the reason
    the snap is not a plain round().
    """
    ratio, dist = snap_split_ratio(5.5)
    assert ratio == 6
    assert dist == pytest.approx(0.0870, abs=1e-4)
    assert abs(5.5 - 5) == abs(5.5 - 6)  # linear distance really is a tie


def test_f1c_ratio_one_for_continuous_series():
    """PREDICTION: a factor of 1.0 snaps to rung 1 at zero distance."""
    assert snap_split_ratio(1.0) == (1, 0.0)


def test_f1d_rejects_nonpositive():
    with pytest.raises(ValueError):
        snap_split_ratio(0.0)


# ---------------------------------------------------------------------------
# Fixture 2 — the adjustment itself
# ---------------------------------------------------------------------------
def test_f2_applies_8to1_split():
    """
    PREDICTION: 100 bars at 80.00 then 50 bars at 10.00 is a clean 8:1 split.
    All 100 pre-split bars become 10.00; the 50 post-split bars are untouched;
    bars_adjusted == 100; residual == 1.0000; continuous is True.
    """
    df = make_series(100, 50, 80.0, 8)
    entry = [{"ticker": "TEST", "date": str(df.index[100].date()),
              "prev_close": 80.0, "post_close": 10.0}]
    out, recs = apply_split_corrections("TEST", df, known_splits=entry)

    assert len(recs) == 1
    r = recs[0]
    assert r["status"] == "APPLIED"
    assert r["ratio"] == 8
    assert r["bars_adjusted"] == 100
    assert r["residual_ratio"] == pytest.approx(1.0, abs=1e-9)
    assert r["continuous"] is True

    assert out["Close"].iloc[:100].eq(10.0).all()
    assert out["Close"].iloc[100:].eq(10.0).all()
    for col in ("Open", "High", "Low"):
        assert out[col].iloc[:100].eq(10.0).all()


def test_f2b_volume_scaled_with_price():
    """
    PREDICTION: with ADJUST_VOLUME on, pre-split volume is multiplied by 8, so
    a flat 1,000 -> 8,000 raw volume series becomes flat 8,000 throughout. If
    it were left alone the split date would show an 8x volume spike — exactly
    the pattern the breakout-volume gate treats as institutional demand.
    """
    df = make_series(100, 50, 80.0, 8, volume=1000)
    entry = [{"ticker": "TEST", "date": str(df.index[100].date()),
              "prev_close": 80.0, "post_close": 10.0}]
    out, _ = apply_split_corrections("TEST", df, known_splits=entry)
    if ADJUST_VOLUME:
        assert out["Volume"].iloc[:100].eq(8000.0).all()
        assert out["Volume"].iloc[100:].eq(8000.0).all()
    else:
        assert out["Volume"].iloc[:100].eq(1000.0).all()


def test_f2c_input_frame_not_mutated():
    """PREDICTION: the caller's frame is untouched; a copy is returned."""
    df = make_series(100, 50, 80.0, 8)
    original = df["Close"].copy()
    entry = [{"ticker": "TEST", "date": str(df.index[100].date()),
              "prev_close": 80.0, "post_close": 10.0}]
    apply_split_corrections("TEST", df, known_splits=entry)
    pd.testing.assert_series_equal(df["Close"], original)


# ---------------------------------------------------------------------------
# Fixture 3 — the safety guard
# ---------------------------------------------------------------------------
def test_f3_skips_already_adjusted_feed():
    """
    PREDICTION: if Yahoo back-adjusts at source, the anchor bar shows no cliff.
    Applying the stored ratio anyway would CREATE an 8x break, so the guard
    must return SKIPPED_ALREADY_ADJUSTED and leave the frame identical.
    """
    df = make_series(100, 50, 10.0, 1)  # already continuous at 10.00 throughout
    entry = [{"ticker": "TEST", "date": str(df.index[100].date()),
              "prev_close": 80.0, "post_close": 10.0}]
    out, recs = apply_split_corrections("TEST", df, known_splits=entry)
    assert recs[0]["status"] == "SKIPPED_ALREADY_ADJUSTED"
    assert recs[0]["bars_adjusted"] == 0
    pd.testing.assert_frame_equal(out, df)


def test_f3b_idempotent():
    """
    PREDICTION: running the correction twice must not double-adjust. The second
    pass sees a continuous series and hits the same guard.
    """
    df = make_series(100, 50, 80.0, 8)
    entry = [{"ticker": "TEST", "date": str(df.index[100].date()),
              "prev_close": 80.0, "post_close": 10.0}]
    once, _ = apply_split_corrections("TEST", df, known_splits=entry)
    twice, recs2 = apply_split_corrections("TEST", once, known_splits=entry)
    assert recs2[0]["status"] == "SKIPPED_ALREADY_ADJUSTED"
    pd.testing.assert_frame_equal(twice, once)


def test_f3c_rejects_unrecognisable_ratio():
    """
    PREDICTION: COPR's 40.93 -> 0.61 is a 67.1:1 factor. Its nearest rung is 12
    at a log distance of 1.72, far past MAX_SNAP_LOG_DISTANCE (0.223), so even
    if it were added to the table it would be refused, not silently snapped to
    12:1. Belt-and-braces behind the universe exclusion.
    """
    df = make_series(100, 50, 40.93, 40.93 / 0.61)
    entry = [{"ticker": "COPR", "date": str(df.index[100].date()),
              "prev_close": 40.93, "post_close": 0.61}]
    out, recs = apply_split_corrections("COPR", df, known_splits=entry)
    assert recs[0]["status"] == "SKIPPED_UNRECOGNISED_RATIO"
    pd.testing.assert_frame_equal(out, df)


def test_f3d_skips_when_anchor_outside_window():
    """PREDICTION: a split date after the last bar has no anchor to adjust at."""
    df = make_series(100, 50, 80.0, 8)
    entry = [{"ticker": "TEST", "date": "2099-01-01",
              "prev_close": 80.0, "post_close": 10.0}]
    out, recs = apply_split_corrections("TEST", df, known_splits=entry)
    assert recs[0]["status"] == "SKIPPED_NO_ANCHOR"
    pd.testing.assert_frame_equal(out, df)


def test_f3e_untabled_ticker_is_a_noop():
    """PREDICTION: a ticker with no table entry returns the same object, no records."""
    df = make_series(100, 50, 80.0, 8)
    out, recs = apply_split_corrections("NOSUCH", df)
    assert recs == []
    assert out is df


# ---------------------------------------------------------------------------
# Fixture 4 — the eight real table entries, end to end
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("entry", KNOWN_SPLITS, ids=[e["ticker"] for e in KNOWN_SPLITS])
def test_f4_real_entries_become_continuous(entry):
    """
    PREDICTION: every one of the eight tabled splits, reconstructed from its own
    recorded closes, corrects to a residual inside the continuity band — i.e.
    the split scan in run_backtest.py would no longer flag that date.
    """
    factor = entry["prev_close"] / entry["post_close"]
    df = make_series(120, 60, entry["prev_close"], factor)
    e = dict(entry, date=str(df.index[120].date()))
    _, recs = apply_split_corrections(entry["ticker"], df, known_splits=[e])

    r = recs[0]
    assert r["status"] == "APPLIED", f"{entry['ticker']} was not corrected"
    assert r["continuous"] is True
    day_ratio = 1.0 / r["residual_ratio"]
    assert CONTINUITY_RATIO_LOW < day_ratio < CONTINUITY_RATIO_HIGH


def test_f4b_expected_ratios_are_locked():
    """
    PREDICTION: the eight ratios derived from the table are exactly
    AMES 8, ARAB 6, CCRS 12, COSG 6, DCCC 6, MFPC 8, MHOT 5, OCDI 4.
    Locked so a future edit to the ladder or the closes cannot silently
    reassign a ticker.
    """
    expected = {"AMES": 8, "ARAB": 6, "CCRS": 12, "COSG": 6,
                "DCCC": 6, "MFPC": 8, "MHOT": 5, "OCDI": 4}
    got = {e["ticker"]: snap_split_ratio(e["prev_close"] / e["post_close"])[0]
           for e in KNOWN_SPLITS}
    assert got == expected


def test_f4c_copr_is_not_in_the_split_table():
    """PREDICTION: COPR is excluded, never corrected."""
    assert "COPR" not in {e["ticker"] for e in KNOWN_SPLITS}


# ---------------------------------------------------------------------------
# Fixture 5 — universe exclusion
# ---------------------------------------------------------------------------
def test_f5_copr_excluded_from_universe():
    """
    PREDICTION: COPR sits in BAD_DATA_TICKERS (not ZERO_DATA_TICKERS — it has
    data, the data is wrong), is in the union, and is gone from VALID_TICKERS.
    194 valid = 224 total - 29 zero-data - 1 bad-data.
    """
    assert "COPR" in BAD_DATA_TICKERS
    assert "COPR" not in ZERO_DATA_TICKERS
    assert "COPR" in EXCLUDED_TICKERS
    assert "COPR" not in VALID_TICKERS
    assert len(VALID_TICKERS) == 194


def test_f5b_exclusion_sets_are_disjoint():
    """PREDICTION: the two reasons never overlap, so each exclusion has one cause."""
    assert not (ZERO_DATA_TICKERS & BAD_DATA_TICKERS)
    assert EXCLUDED_TICKERS == ZERO_DATA_TICKERS | BAD_DATA_TICKERS
