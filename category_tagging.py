import json
import datetime
import yfinance as yf
import pandas as pd

from kashif_config import CONFIG_PATH

# Structured equivalent of the JSON's free-text category_overrides, so
# fundamentals_screen.py can branch on it programmatically instead of parsing
# prose. Per feature-02-fundamentals-screen-rules.md Section 2.2: only
# earnings_growth's curve is overridden for turnaround -- earnings_acceleration
# /code_33 run unchanged, since they already capture acceleration separately.
CATEGORY_OVERRIDES = {
    "cyclical":   {"invert_pe_logic": True},
    "turnaround": {"earnings_growth_floor": 1.00, "earnings_growth_cap": 1.40},
    "laggard":    {"exclude_regardless_of_pe": True},
}

# market_cap_band modifiers (Section 2.3) -- pure boosts, never a penalty.
# Feeds position_sizing.prioritization_when_oversubscribed ONLY -- never the
# fundamentals_screen composite score. That's a deliberate scope boundary,
# not an oversight: this module computes and exposes these tags, but
# fundamentals_screen.py must never consume them for scoring.
MARKET_CAP_BAND_MODIFIER = {"small": 0.05, "mid": 0.025, "large": 0.0, None: 0.0}


def load_category_tagging():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg["category_tagging"]


def fetch_ticker_info(symbol):
    """
    Thin wrapper around yfinance's ticker.info dict. NEW pattern for this
    project -- every existing yfinance call elsewhere only uses .history()
    for OHLC price series; EGX coverage of .info fields (marketCap,
    sharesOutstanding, a first-trade/listing-date field) is unconfirmed per
    the spec, so callers must not assume any given key exists.
    """
    return yf.Ticker(symbol).info


def compute_market_cap_percentiles(market_caps):
    """
    market_caps: dict or Series of {ticker: market_cap}, a single point-in-time
    snapshot (not a wide time series like trend_template_test.compute_rs_percentile,
    since market-cap banding isn't recomputed per trading day the same way RS is).

    Returns a Series of 0-100 percentiles, one per ticker. NaN input values stay
    NaN in the output and do not affect other tickers' ranks (pandas .rank()'s
    default na_option='keep' -- this is judged as the right choice on its own
    merits for a per-ticker soft tag with an explicit "leave unset, no boost"
    fallback: one ticker's missing market cap shouldn't erase every other
    ticker's band assignment for that snapshot.

    NOTE, corrected: an earlier version of this docstring described this as
    "mirroring trend_template_test.compute_rs_percentile's na_option='keep'
    spirit." That was wrong -- confirmed by directly reading the real file:
    compute_rs_percentile() actually uses dropna(how="any") (inner join --
    drops an entire date if ANY ticker is missing that day), and its own
    docstring explicitly says this is NOT the outer-join/na_option='keep'
    approach, which only exists in the separate trend_template_full_universe.py
    script. The na_option='keep' choice here is independently justified for
    this function's own use case, not inherited from a precedent that doesn't
    actually behave this way.
    """
    s = pd.Series(market_caps, dtype="float64")
    return s.rank(pct=True, na_option="keep") * 100


def assign_market_cap_band(percentile):
    """
    small: [0,33), mid: [33,67), large: [67,100]. None if percentile is NaN/None.
    Boundary ownership (33 -> mid, 67 -> large) is this module's explicit choice --
    the spec states "bottom/middle/top third" without pinning which band owns an
    exact tie at the boundary.
    """
    if percentile is None or pd.isna(percentile):
        return None
    if percentile < 33:
        return "small"
    if percentile < 67:
        return "mid"
    return "large"


def market_cap_band_modifier(band):
    return MARKET_CAP_BAND_MODIFIER.get(band, 0.0)


def compute_years_since_ipo(listing_date, as_of_date=None):
    """
    listing_date: datetime.date or None (None if unavailable -- no confirmed
    EGX fallback source exists per the spec; caller must accept None).
    """
    if listing_date is None:
        return None
    if as_of_date is None:
        as_of_date = datetime.date.today()
    return (as_of_date - listing_date).days / 365.25


def years_since_ipo_modifier(years_since_ipo):
    """
    Linear decay per feature-02 Section 2.3 / JSON v0.7 resolution:
      0.05                          if years <= 5
      0.05 * (10 - years) / 5       if 5 < years < 10
      0.0                           if years >= 10 or years is None
    Checkpoints (JSON's own worked_check): 5->0.05, 7->0.03, 9->0.01, 10+->0.0.
    Feeds position_sizing only -- same scope boundary as market_cap_band.
    """
    if years_since_ipo is None:
        return 0.0
    if years_since_ipo <= 5:
        return 0.05
    if years_since_ipo < 10:
        return 0.05 * (10 - years_since_ipo) / 5
    return 0.0


def get_earnings_growth_curve_params(category):
    """
    (floor, cap) tuple consumed by fundamentals_screen.score_earnings_growth().
    Normal curve: floor=0.20, cap=0.60 (= 2x the 30% reward_above threshold).
    Turnaround override (feature-02 Section 2.2, resolved after rejecting both
    a floor-only override -- mathematically broken, floor > unchanged cap --
    and a uniform 5x scale -- needs an unreachable 300% growth to max out):
    preserves the normal curve's absolute 40-percentage-point ramp width,
    relocated to the new floor. floor=1.00, cap=1.40.
    """
    if category == "turnaround":
        ov = CATEGORY_OVERRIDES["turnaround"]
        return ov["earnings_growth_floor"], ov["earnings_growth_cap"]
    return 0.20, 0.60


def get_category_override(category):
    return CATEGORY_OVERRIDES.get(category, {})


def tag_universe(ticker_market_caps, ticker_listing_dates, as_of_date=None):
    """
    Orchestrator: wires the per-ticker functions above into a results table.

    ticker_market_caps: {ticker: market_cap or None}
    ticker_listing_dates: {ticker: datetime.date or None}

    Takes plain dicts as input rather than fetching a live ~224-ticker EGX
    universe itself -- egx_tickers.py (the full ticker list) does not exist
    on disk yet (a pre-existing gap: trend_template_full_universe.py already
    depends on it and can't currently run either). Keeping this function
    universe-agnostic means it's fully unit-testable with a small synthetic
    universe and has zero dependency on that gap being resolved first.

    Returns a DataFrame indexed by ticker with columns:
      market_cap, market_cap_percentile, market_cap_band, market_cap_band_modifier,
      years_since_ipo, years_since_ipo_modifier
    """
    tickers = list(ticker_market_caps.keys())
    percentiles = compute_market_cap_percentiles(ticker_market_caps)

    rows = []
    for tkr in tickers:
        pct = percentiles.get(tkr)
        band = assign_market_cap_band(pct)
        listing_date = ticker_listing_dates.get(tkr)
        years = compute_years_since_ipo(listing_date, as_of_date)
        rows.append({
            "ticker": tkr,
            "market_cap": ticker_market_caps[tkr],
            "market_cap_percentile": pct,
            "market_cap_band": band,
            "market_cap_band_modifier": market_cap_band_modifier(band),
            "years_since_ipo": years,
            "years_since_ipo_modifier": years_since_ipo_modifier(years),
        })
    return pd.DataFrame(rows).set_index("ticker")
