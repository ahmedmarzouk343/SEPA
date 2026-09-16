"""
fundamentals_fetcher.py — Fetch quarterly fundamentals from yfinance for EGX tickers.

Converts yfinance's quarterly_income_stmt / quarterly_balance_sheet into the
dict format that fundamentals_screen.compute_composite() expects:
  eps_yoy_growth_by_quarter, revenue_yoy_growth_by_quarter, margin_by_quarter,
  sources_by_quarter, peg, deep_checks_available, deep_checks_result,
  post_earnings_returns

Applies the 60-day FRA filing lag: a quarter's data is only "known" 60 days
after the quarter-end date. For backtesting, this means a Q ending 2024-03-31
is not usable until 2024-05-30.
"""

import logging
from datetime import timedelta
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

log = logging.getLogger("fundamentals_fetcher")

FRA_LAG_DAYS = 60


def _quarter_end_to_available_date(quarter_end: pd.Timestamp) -> pd.Timestamp:
    return quarter_end + timedelta(days=FRA_LAG_DAYS)


def fetch_fundamentals(ticker: str, suffix: str = ".CA", as_of_date: Optional[pd.Timestamp] = None) -> dict:
    """
    Fetch quarterly fundamentals for a ticker from yfinance.

    Args:
        ticker: Ticker symbol (without exchange suffix).
        suffix: Exchange suffix appended to form the yfinance symbol
                (e.g. ".CA" for EGX, "" for US equities).
        as_of_date: if provided, only quarters whose data would be available
                    by this date (after 60-day FRA lag) are included.

    Returns:
        Dict in compute_composite() format, or None if no data available.
    """
    symbol = f"{ticker}{suffix}"
    try:
        tk = yf.Ticker(symbol)
        income = tk.quarterly_income_stmt
        info = tk.info or {}
    except Exception as e:
        log.warning("yfinance fetch failed for %s: %s", ticker, e)
        return None

    # A3 (Q4): annual income statement, for the annual-EPS question. Fetched
    # in its own try/except so an annual-feed outage degrades Q4 to SKIPPED
    # rather than killing the whole quarterly fetch.
    annual_eps = _fetch_annual_eps(tk, ticker, as_of_date=as_of_date)

    if income is None or income.empty:
        log.info("No quarterly income statement for %s", ticker)
        return None

    income = income.T.sort_index()

    if as_of_date is not None:
        available_mask = income.index.map(
            lambda qe: _quarter_end_to_available_date(pd.Timestamp(qe)) <= as_of_date
        )
        income = income[available_mask]

    if income.empty:
        log.info("No quarters available for %s after FRA lag filter (as_of=%s)", ticker, as_of_date)
        return None

    eps_growth = _compute_yoy_growth(income, "Basic EPS", "Diluted EPS")
    revenue_growth = _compute_yoy_growth(income, "Total Revenue", "Operating Revenue")
    margin = _compute_margins(income)
    sources = ["yfinance"] * len(income)
    peg = info.get("pegRatio") or info.get("trailingPegRatio")
    if peg is None or (isinstance(peg, float) and (np.isnan(peg) or peg <= 0)):
        peg = None

    post_earnings_returns = []

    return {
        "eps_yoy_growth_by_quarter": eps_growth if eps_growth else None,
        "revenue_yoy_growth_by_quarter": revenue_growth if revenue_growth else None,
        "margin_by_quarter": margin if margin else None,
        "annual_eps_by_year": annual_eps if annual_eps else None,
        "sources_by_quarter": sources,
        "peg": peg,
        "deep_checks_available": False,
        "deep_checks_result": None,
        "post_earnings_returns": post_earnings_returns,
    }


def _fetch_annual_eps(tk, ticker: str, as_of_date: Optional[pd.Timestamp] = None) -> list:
    """
    A3 (Q4): absolute annual EPS, oldest-first, from yfinance's annual income
    statement. Returns [] on any failure — Q4 then SKIPS rather than fails.

    Applies the same 60-day availability lag as the quarterly path so a fiscal
    year that had not been filed yet as of `as_of_date` cannot leak backwards
    into a backtest bar.
    """
    try:
        annual = tk.financials
    except Exception as e:
        log.info("No annual income statement for %s: %s", ticker, e)
        return []
    if annual is None or annual.empty:
        return []
    annual = annual.T.sort_index()
    if as_of_date is not None:
        mask = annual.index.map(
            lambda ye: _quarter_end_to_available_date(pd.Timestamp(ye)) <= as_of_date
        )
        annual = annual[mask]
    if annual.empty:
        return []
    col = "Basic EPS" if "Basic EPS" in annual.columns else "Diluted EPS"
    if col not in annual.columns:
        return []
    values = []
    for v in annual[col].tolist():
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if not np.isnan(f):
            values.append(f)
    return values


def _compute_yoy_growth(income_df: pd.DataFrame, primary_col: str, fallback_col: str) -> list:
    col = primary_col if primary_col in income_df.columns else fallback_col
    if col not in income_df.columns:
        return []

    values = income_df[col].values
    growth_ratios = []
    for i in range(len(values)):
        if i < 4:
            growth_ratios.append(None)
            continue
        current = values[i]
        year_ago = values[i - 4]
        if year_ago is None or pd.isna(year_ago) or year_ago == 0:
            growth_ratios.append(None)
            continue
        if current is None or pd.isna(current):
            growth_ratios.append(None)
            continue
        growth_ratios.append(float(current / year_ago))

    valid = [g for g in growth_ratios if g is not None]
    return valid


def _compute_margins(income_df: pd.DataFrame) -> list:
    revenue_col = "Total Revenue" if "Total Revenue" in income_df.columns else "Operating Revenue"
    income_col = "Net Income" if "Net Income" in income_df.columns else "Net Income Common Stockholders"

    if revenue_col not in income_df.columns or income_col not in income_df.columns:
        return []

    margins = []
    for _, row in income_df.iterrows():
        rev = row.get(revenue_col)
        inc = row.get(income_col)
        if rev is None or pd.isna(rev) or rev == 0 or inc is None or pd.isna(inc):
            margins.append(None)
        else:
            margins.append(float(inc / rev))

    valid = [m for m in margins if m is not None]
    return valid


def test_five_tickers():
    """Quick test on 5 tickers — report 4-question screen results."""
    from fundamentals_screen import evaluate_fundamentals

    tickers = ["COMI", "TMGH", "SWDY", "HRHO", "ABUK"]
    print("=" * 70)
    print("Fundamentals Fetcher — 5-ticker test")
    print("=" * 70)

    for ticker in tickers:
        print(f"\n--- {ticker} ---")
        data = fetch_fundamentals(ticker)
        if data is None:
            print(f"  Status: SKIPPED (no data from yfinance)")
            continue

        eps = data["eps_yoy_growth_by_quarter"]
        rev = data["revenue_yoy_growth_by_quarter"]
        print(f"  EPS growth quarters: {len(eps) if eps else 0}")
        print(f"  Revenue growth quarters: {len(rev) if rev else 0}")
        print(f"  PEG: {data['peg']}")

        if eps:
            result = evaluate_fundamentals(data, category=None)
            print(f"  Pass: {result.get('pass')}")
            print(f"  {result.get('overall_reason')}")
            for q in ("q1", "q2", "q3", "q4"):
                print(f"    {q.upper()}: {result[q]['status']} — {result[q].get('reason','')}")
        else:
            print(f"  Status: SKIPPED (no EPS growth data)")


if __name__ == "__main__":
    test_five_tickers()
