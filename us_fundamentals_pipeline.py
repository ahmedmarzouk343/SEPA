"""
US Fundamentals Data Collection Pipeline
Sources: SEC EDGAR (primary), stockanalysis.com (secondary), yfinance (last resort)
Output: Excel (.xlsx) with append behavior
"""

import re
import time
import json
import logging
import warnings
import requests
import yfinance as yf
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, date, timedelta

warnings.filterwarnings("ignore", category=FutureWarning)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
log = logging.getLogger("us_fundamentals")

# ── Configuration ────────────────────────────────────────────────────────────

SEC_USER_AGENT = "KashifBacktest/1.0 (ahmed.marzouk@sprints.ai)"
SEC_RATE_DELAY = 0.15          # ~7 req/sec, well under SEC's 10/sec
YF_DELAY = 0.3
SA_DELAY = 1.0
LOOKBACK_YEARS = 5
OUTPUT_PATH = Path(r"C:\Users\Asuss\Stocks\us_fundamentals_raw.xlsx")
SHEET_NAME = "us_fundamentals_raw"

CUTOFF_DATE = datetime.now() - timedelta(days=LOOKBACK_YEARS * 365)

# SEC EDGAR concept name priority lists (companies use different names)
SEC_REVENUE_CONCEPTS = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
    "RevenueNet",
]
SEC_NET_INCOME_CONCEPTS = [
    "NetIncomeLoss",
    "NetIncomeLossAvailableToCommonStockholdersBasic",
    "ProfitLoss",
]
SEC_EPS_CONCEPTS = [
    "EarningsPerShareDiluted",
    "EarningsPerShareBasic",
]
SEC_INVENTORY_CONCEPTS = [
    "InventoryNet",
    "Inventories",
]
SEC_RECEIVABLES_CONCEPTS = [
    "AccountsReceivableNetCurrent",
    "AccountsReceivableNet",
    "ReceivablesNetCurrent",
]

# ── SEC EDGAR ────────────────────────────────────────────────────────────────

_cik_map = None

def _load_cik_map():
    global _cik_map
    if _cik_map is not None:
        return _cik_map
    log.info("Loading SEC ticker→CIK map...")
    url = "https://www.sec.gov/files/company_tickers.json"
    r = requests.get(url, headers={"User-Agent": SEC_USER_AGENT}, timeout=15)
    r.raise_for_status()
    data = r.json()
    _cik_map = {}
    for entry in data.values():
        ticker = entry["ticker"].upper()
        cik = entry["cik_str"]
        _cik_map[ticker] = cik
    log.info("Loaded %d ticker→CIK mappings", len(_cik_map))
    time.sleep(SEC_RATE_DELAY)
    return _cik_map


def _get_cik(ticker):
    cik_map = _load_cik_map()
    cik = cik_map.get(ticker.upper())
    if cik is None:
        return None
    return str(cik).zfill(10)


def _period_days(entry):
    """Return the number of days in the entry's period, or None."""
    start = entry.get("start", "")
    end = entry.get("end", "")
    if start and end:
        try:
            s = datetime.strptime(start, "%Y-%m-%d")
            e = datetime.strptime(end, "%Y-%m-%d")
            return (e - s).days
        except ValueError:
            pass
    return None


def fetch_sec_edgar(ticker):
    """Fetch quarterly facts from SEC EDGAR Company Facts API.

    Keys use the XBRL entry's own fy (fiscal year) field, NOT the calendar
    year derived from end_date.  This groups all quarters of the same fiscal
    year under one year number and eliminates collisions for companies with
    non-calendar fiscal years.

    Comparative filtering: SEC filings include prior-period data as
    comparatives.  The same data point appears with different fy values
    (the original filing's fy vs. later filings' fy).  Only entries from
    the ORIGINAL filing (smallest fy for each period) may CREATE a new
    quarterly slot.  Entries from later filings (larger fy, i.e. comparatives)
    can UPDATE values in an existing slot whose quarter_end_date matches,
    but never create new slots — this prevents phantom entries.

    Filing dates: the EARLIEST filed date per period is tracked separately
    and used as earnings_release_date (when the market first saw the data).
    """
    cik = _get_cik(ticker)
    if cik is None:
        log.warning("SEC: No CIK found for %s", ticker)
        return {}

    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    try:
        r = requests.get(url, headers={"User-Agent": SEC_USER_AGENT}, timeout=20)
        time.sleep(SEC_RATE_DELAY)
        if r.status_code == 404:
            log.warning("SEC: No XBRL data for %s (CIK %s)", ticker, cik)
            return {}
        r.raise_for_status()
        facts = r.json()
    except Exception as e:
        log.error("SEC: Failed to fetch %s: %s", ticker, e)
        return {}

    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    if not us_gaap:
        log.warning("SEC: No us-gaap facts for %s", ticker)
        return {}

    quarterly = {}          # q_key -> {field: val, quarter_end_date, ...}
    quarterly_filed = {}    # (q_key, field_name) -> filed_date (latest value wins)
    annuals = {}            # fy_str -> {field: val, quarter_end_date, ...}
    annual_filed = {}       # (fy_str, field_name) -> filed_date
    original_dates = {}     # q_key -> earliest filing date (for release_date)
    # Track which (end_date) already has a slot, to prevent comparatives
    # from creating phantom entries under a different q_key.
    end_date_to_qkey = {}   # end_date_str -> q_key (first slot created for that date)

    def _find_existing_slot(end_date):
        """Find an existing quarterly slot whose end_date is within 5 days."""
        if end_date in end_date_to_qkey:
            return end_date_to_qkey[end_date]
        try:
            dt = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            return None
        for existing_end, qk in end_date_to_qkey.items():
            try:
                edt = datetime.strptime(existing_end, "%Y-%m-%d")
                if abs(dt - edt).days <= 5:
                    return qk
            except ValueError:
                continue
        return None

    def _extract_concept(concept_names, field_name, is_instant=False):
        for concept in concept_names:
            if concept not in us_gaap:
                continue
            units = us_gaap[concept].get("units", {})
            unit_key = "USD/shares" if "EarningsPer" in concept else "USD"
            entries = units.get(unit_key, [])
            found_data = False

            # --- Pass 1: find the smallest fy per (end_date, fp, form) ---
            # This identifies which entries are originals vs comparatives.
            original_fy = {}  # (end_date, fp_or_q4) -> smallest fy
            for entry in entries:
                form = entry.get("form", "")
                if form not in ("10-Q", "10-K"):
                    continue
                end_date = entry.get("end", "")
                fp = entry.get("fp", "")
                fy = entry.get("fy")
                if not end_date or fy is None:
                    continue
                try:
                    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
                except ValueError:
                    continue
                if end_dt < CUTOFF_DATE:
                    continue
                fy_int = int(fy)

                if is_instant:
                    if fp in ("FY", "Q4"):
                        group_key = (end_date, "Q4")
                    elif fp in ("Q1", "Q2", "Q3"):
                        group_key = (end_date, fp)
                    else:
                        continue
                else:
                    days = _period_days(entry)
                    if form == "10-Q" and fp in ("Q1", "Q2", "Q3"):
                        if days is not None and not (75 <= days <= 105):
                            continue
                        group_key = (end_date, fp)
                    elif form == "10-K" and fp == "FY":
                        if days is not None and days < 300:
                            continue
                        group_key = (end_date, "FY")
                    else:
                        continue

                prev = original_fy.get(group_key)
                if prev is None or fy_int < prev:
                    original_fy[group_key] = fy_int

            # --- Pass 2: process entries, using fy to build keys ---
            for entry in entries:
                form = entry.get("form", "")
                if form not in ("10-Q", "10-K"):
                    continue
                end_date = entry.get("end", "")
                filed_date = entry.get("filed", "")
                fp = entry.get("fp", "")
                fy = entry.get("fy")
                val = entry.get("val")
                if not end_date or val is None or fy is None:
                    continue
                try:
                    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
                except ValueError:
                    continue
                if end_dt < CUTOFF_DATE:
                    continue
                fy_int = int(fy)

                days = _period_days(entry)

                # ─── Balance sheet items (instant/snapshot) ───
                if is_instant:
                    if fp in ("FY", "Q4"):
                        slot_fp = "Q4"
                        group_key = (end_date, "Q4")
                    elif fp in ("Q1", "Q2", "Q3"):
                        slot_fp = fp
                        group_key = (end_date, fp)
                    else:
                        continue

                    is_original = (fy_int == original_fy.get(group_key, -1))

                    # For balance sheet, fp from the FILING may not match the
                    # data's actual quarter.  Always check for an existing slot
                    # first to avoid creating duplicate Q4 entries from
                    # comparative filings that reuse the same end_date.
                    existing = _find_existing_slot(end_date)
                    if fp in ("FY", "Q4"):
                        if existing:
                            q_key = existing
                        elif is_original:
                            q_key = f"Q4_{fy_int}"
                        else:
                            continue  # comparative year-end snapshot, no slot — skip
                    else:
                        # fp is Q1/Q2/Q3 — might be correct, or might be
                        # a year-end snapshot repeated in a later quarter's filing.
                        # Only trust it if it's the original (smallest fy).
                        existing = _find_existing_slot(end_date)
                        if existing:
                            q_key = existing
                        elif is_original:
                            q_key = f"{fp}_{fy_int}"
                        else:
                            continue  # comparative with wrong fp — skip

                    track_key = (q_key, field_name)
                    prev_filed = quarterly_filed.get(track_key, "")
                    if filed_date >= prev_filed:
                        if q_key not in quarterly:
                            quarterly[q_key] = {"quarter_end_date": end_date}
                            end_date_to_qkey[end_date] = q_key
                        quarterly[q_key][field_name] = val
                        quarterly_filed[track_key] = filed_date
                    if filed_date:
                        original_dates[q_key] = min(original_dates.get(q_key, "9999-99-99"), filed_date)
                    found_data = True
                    continue

                # ─── Income statement items (duration) ───

                # QUARTERLY: 10-Q, fp=Q1/Q2/Q3, ~90 day period
                if form == "10-Q" and fp in ("Q1", "Q2", "Q3"):
                    if days is not None and not (75 <= days <= 105):
                        continue
                    group_key = (end_date, fp)
                    is_original = (fy_int == original_fy.get(group_key, -1))

                    # Always check for an existing slot first — prevents
                    # creating a duplicate key when a later concept sees the
                    # same end_date with a different fp (e.g. Q1 data in Q3 filing).
                    existing = _find_existing_slot(end_date)
                    if existing:
                        q_key = existing
                    elif is_original:
                        q_key = f"{fp}_{fy_int}"
                    else:
                        continue  # comparative, no slot exists — skip

                    track_key = (q_key, field_name)
                    prev_filed = quarterly_filed.get(track_key, "")
                    if filed_date >= prev_filed:
                        if q_key not in quarterly:
                            quarterly[q_key] = {"quarter_end_date": end_date}
                            end_date_to_qkey[end_date] = q_key
                        quarterly[q_key][field_name] = val
                        quarterly_filed[track_key] = filed_date
                    if filed_date:
                        original_dates[q_key] = min(original_dates.get(q_key, "9999-99-99"), filed_date)
                    found_data = True

                # ANNUAL: 10-K, fp=FY, ~365 day period
                elif form == "10-K" and fp == "FY":
                    if days is not None and days < 300:
                        continue
                    fy_str = str(fy_int)
                    is_original = (fy_int == original_fy.get((end_date, "FY"), -1))
                    if not is_original:
                        continue  # skip ALL comparative annuals — prevents cross-FY contamination

                    track_key = (fy_str, field_name)
                    prev_filed = annual_filed.get(track_key, "")
                    if filed_date >= prev_filed:
                        if fy_str not in annuals:
                            annuals[fy_str] = {"quarter_end_date": end_date}
                        annuals[fy_str][field_name] = val
                        annual_filed[track_key] = filed_date
                    if filed_date:
                        q4k = f"Q4_{fy_str}"
                        original_dates[q4k] = min(original_dates.get(q4k, "9999-99-99"), filed_date)
                    found_data = True

            if found_data:
                break

    _extract_concept(SEC_EPS_CONCEPTS, "sec_eps")
    _extract_concept(SEC_REVENUE_CONCEPTS, "sec_revenue")
    _extract_concept(SEC_NET_INCOME_CONCEPTS, "sec_net_income")
    _extract_concept(SEC_INVENTORY_CONCEPTS, "sec_inventory", is_instant=True)
    _extract_concept(SEC_RECEIVABLES_CONCEPTS, "sec_receivables", is_instant=True)

    # Derive Q4 = Annual - (Q1 + Q2 + Q3) for income fields
    for fy_str, annual_data in annuals.items():
        q4_key = f"Q4_{fy_str}"
        annual_end = annual_data.get("quarter_end_date", "")
        # If a slot already exists for this annual's end_date under a
        # different key (from balance sheet processing), reuse that key
        # instead of creating a duplicate.
        existing = _find_existing_slot(annual_end) if annual_end else None
        if existing and existing != q4_key:
            q4_key = existing
        q_count = sum(1 for q in (f"Q1_{fy_str}", f"Q2_{fy_str}", f"Q3_{fy_str}") if q in quarterly)
        if q4_key not in quarterly:
            quarterly[q4_key] = {"quarter_end_date": annual_end}
            if annual_end:
                end_date_to_qkey[annual_end] = q4_key
        if q_count == 3:
            for field in ("sec_eps", "sec_revenue", "sec_net_income"):
                if field not in annual_data:
                    continue
                annual_val = annual_data[field]
                q1_val = quarterly.get(f"Q1_{fy_str}", {}).get(field)
                q2_val = quarterly.get(f"Q2_{fy_str}", {}).get(field)
                q3_val = quarterly.get(f"Q3_{fy_str}", {}).get(field)
                if q1_val is None or q2_val is None or q3_val is None:
                    continue
                q4_val = annual_val - q1_val - q2_val - q3_val
                quarterly[q4_key][field] = round(q4_val, 4) if isinstance(q4_val, float) else q4_val
        quarterly[q4_key]["sec_q4_derived"] = True
        quarterly[q4_key]["sec_q4_inputs"] = q_count

    # Attach filing dates — use EARLIEST (original disclosure) as release date
    for q_key in quarterly:
        if q_key in original_dates:
            quarterly[q_key]["sec_filing_date"] = original_dates[q_key]

    log.info("SEC: %s -> %d quarters extracted (%d annual used for Q4 derivation)",
             ticker, len(quarterly), len(annuals))
    return quarterly


# ── yfinance ─────────────────────────────────────────────────────────────────

def fetch_yfinance(ticker):
    """Fetch quarterly financials from yfinance (last-resort source)."""
    log.info("yfinance: Fetching %s...", ticker)
    try:
        tk = yf.Ticker(ticker)
        time.sleep(YF_DELAY)
    except Exception as e:
        log.error("yfinance: Failed to create Ticker for %s: %s", ticker, e)
        return {}

    quarters = {}

    # Quarterly income statement
    try:
        inc = tk.quarterly_income_stmt
        if inc is not None and not inc.empty:
            for col in inc.columns:
                col_date = pd.Timestamp(col)
                if col_date < pd.Timestamp(CUTOFF_DATE):
                    continue
                end_date = col_date.strftime("%Y-%m-%d")
                q_num = (col_date.month - 1) // 3 + 1
                q_key = f"Q{q_num}_{col_date.year}"

                row_data = {}
                for field, names in [
                    ("yf_eps", ["Diluted EPS", "Basic EPS"]),
                    ("yf_revenue", ["Total Revenue", "Revenue"]),
                    ("yf_net_income", ["Net Income", "Net Income Common Stockholders"]),
                ]:
                    for name in names:
                        if name in inc.index:
                            val = inc.loc[name, col]
                            if pd.notna(val):
                                row_data[field] = float(val)
                                break

                if row_data:
                    quarters[q_key] = {
                        "quarter_end_date": end_date,
                        **row_data,
                    }
        time.sleep(YF_DELAY)
    except Exception as e:
        log.warning("yfinance: Income stmt failed for %s: %s", ticker, e)

    # Quarterly balance sheet
    try:
        bs = tk.quarterly_balance_sheet
        if bs is not None and not bs.empty:
            for col in bs.columns:
                col_date = pd.Timestamp(col)
                if col_date < pd.Timestamp(CUTOFF_DATE):
                    continue
                end_date = col_date.strftime("%Y-%m-%d")
                q_num = (col_date.month - 1) // 3 + 1
                q_key = f"Q{q_num}_{col_date.year}"

                if q_key not in quarters:
                    quarters[q_key] = {"quarter_end_date": end_date}

                for field, names in [
                    ("yf_inventory", ["Inventory", "Inventories"]),
                    ("yf_receivables", ["Accounts Receivable", "Receivables", "Net Receivables"]),
                ]:
                    for name in names:
                        if name in bs.index:
                            val = bs.loc[name, col]
                            if pd.notna(val):
                                quarters[q_key][field] = float(val)
                                break
        time.sleep(YF_DELAY)
    except Exception as e:
        log.warning("yfinance: Balance sheet failed for %s: %s", ticker, e)

    # Earnings dates (for analyst estimates and surprise)
    try:
        ed = tk.earnings_dates
        if ed is not None and not ed.empty:
            cutoff_ts = pd.Timestamp(CUTOFF_DATE, tz="UTC")
            for idx, row in ed.iterrows():
                ed_date = pd.Timestamp(idx)
                if ed_date.tzinfo is not None:
                    if cutoff_ts.tzinfo is None:
                        cutoff_ts = cutoff_ts.tz_localize("UTC")
                else:
                    if cutoff_ts.tzinfo is not None:
                        cutoff_ts = cutoff_ts.tz_localize(None)
                if ed_date < cutoff_ts:
                    continue
                ed_date_naive = ed_date.tz_localize(None) if ed_date.tzinfo else ed_date
                best_q = None
                best_gap = timedelta(days=999)
                for q_key, q_data in quarters.items():
                    qend = q_data.get("quarter_end_date", "")
                    if not qend:
                        continue
                    qend_ts = pd.Timestamp(qend)
                    gap = abs(ed_date_naive - qend_ts)
                    if gap < best_gap and gap < timedelta(days=75):
                        best_gap = gap
                        best_q = q_key
                if best_q is not None:
                    if pd.notna(row.get("EPS Estimate")):
                        quarters[best_q]["yf_eps_estimate"] = float(row["EPS Estimate"])
                    if pd.notna(row.get("Reported EPS")):
                        quarters[best_q]["yf_reported_eps"] = float(row["Reported EPS"])
                    if pd.notna(row.get("Surprise(%)")):
                        quarters[best_q]["yf_surprise_pct"] = float(row["Surprise(%)"])
                    quarters[best_q]["yf_earnings_date"] = ed_date_naive.strftime("%Y-%m-%d")
        time.sleep(YF_DELAY)
    except Exception as e:
        log.warning("yfinance: Earnings dates failed for %s: %s", ticker, e)

    log.info("yfinance: %s → %d quarters extracted", ticker, len(quarters))
    return quarters


# ── stockanalysis.com (gap-filler) ───────────────────────────────────────────

def fetch_stockanalysis(ticker):
    """Placeholder — stockanalysis.com is JS-rendered with no public API."""
    log.info("stockanalysis: Skipped %s (no public API available)", ticker)
    return {}


# ── Merge logic ──────────────────────────────────────────────────────────────

def _fiscal_quarter_label(q_key):
    """Convert 'Q1_2024' to 'Q1 2024'."""
    return q_key.replace("_", " ")


def _validate_yf_match(yf_entry, quarter_end_str):
    """Reject a yfinance match if its release date falls before the quarter ended."""
    yf_release = yf_entry.get("yf_earnings_date", "")
    if not yf_release or not quarter_end_str:
        return True  # can't validate, allow
    try:
        release_dt = datetime.strptime(yf_release, "%Y-%m-%d")
        qend_dt = datetime.strptime(quarter_end_str, "%Y-%m-%d")
        if release_dt < qend_dt:
            return False
    except ValueError:
        pass
    return True


def merge_sources(ticker, yf_data, sec_data, sa_data):
    """Merge quarterly data from all sources into final rows.

    Source priority: SEC EDGAR → stockanalysis.com → yfinance.
    yfinance is last resort — used only when SEC and SA both lack the field,
    except for analyst_eps_estimate and eps_surprise_pct (yfinance-exclusive).

    Matches across sources by quarter_end_date proximity (not key string)
    because SEC uses fiscal quarters while yfinance uses calendar quarters.
    SEC's fiscal quarter label is authoritative for the output.

    yfinance data is rejected for a quarter if its release date predates
    that quarter's end date (a reliable signal of a mismatched period).
    """
    # Build canonical period list from SEC (authoritative)
    all_dates = {}  # canonical_date_str -> {sec_key, yf_key, sa_key, label}
    DATE_MATCH_DAYS = 20

    for q_key, q_data in sec_data.items():
        end_date = q_data.get("quarter_end_date", "")
        if end_date:
            all_dates[end_date] = {"sec_key": q_key, "label": q_key}

    # Match stockanalysis entries to SEC dates (secondary source)
    for q_key, q_data in sa_data.items():
        end_date = q_data.get("quarter_end_date", "")
        if not end_date:
            continue
        matched = False
        for canon_date, info in all_dates.items():
            try:
                d1 = datetime.strptime(end_date, "%Y-%m-%d")
                d2 = datetime.strptime(canon_date, "%Y-%m-%d")
                if abs(d1 - d2) <= timedelta(days=DATE_MATCH_DAYS):
                    info["sa_key"] = q_key
                    matched = True
                    break
            except ValueError:
                continue
        if not matched:
            all_dates[end_date] = {"sa_key": q_key, "label": q_key}

    # Match yfinance entries to SEC/SA dates (last resort)
    yf_match_log = []
    for q_key, q_data in yf_data.items():
        end_date = q_data.get("quarter_end_date", "")
        if not end_date:
            continue
        matched = False
        for canon_date, info in all_dates.items():
            try:
                d1 = datetime.strptime(end_date, "%Y-%m-%d")
                d2 = datetime.strptime(canon_date, "%Y-%m-%d")
                if abs(d1 - d2) <= timedelta(days=DATE_MATCH_DAYS):
                    if _validate_yf_match(q_data, canon_date):
                        info["yf_key"] = q_key
                        matched = True
                    else:
                        yf_match_log.append(
                            f"yf {q_key} (end={end_date}) rejected for "
                            f"{info.get('label','?')}: release date "
                            f"{q_data.get('yf_earnings_date','')} < quarter end {canon_date}"
                        )
                    break
            except ValueError:
                continue
        if not matched and end_date not in all_dates:
            if _validate_yf_match(q_data, end_date):
                all_dates[end_date] = {"yf_key": q_key, "label": q_key}

    for msg in yf_match_log:
        log.info("Merge: %s", msg)

    rows = []
    today_str = date.today().isoformat()

    for canon_date in sorted(all_dates.keys()):
        info = all_dates[canon_date]
        q_label = info.get("label", "")
        sec_key = info.get("sec_key")
        sa_key = info.get("sa_key")
        yf_key = info.get("yf_key")

        sec = sec_data.get(sec_key, {}) if sec_key else {}
        sa = sa_data.get(sa_key, {}) if sa_key else {}
        yf = yf_data.get(yf_key, {}) if yf_key else {}

        quarter_end = sec.get("quarter_end_date") or sa.get("quarter_end_date") or yf.get("quarter_end_date") or ""
        sources = []
        notes = []

        if sec.get("sec_q4_derived"):
            q_inputs = sec.get("sec_q4_inputs", 0)
            if q_inputs < 3:
                notes.append(f"SEC Q4 derived from annual minus {q_inputs}/3 quarters (less reliable)")
            else:
                notes.append("SEC Q4 derived: annual minus Q1+Q2+Q3")

        # ── EPS: SEC → SA → yfinance ──
        eps_reported = None
        if sec.get("sec_eps") is not None:
            eps_reported = sec["sec_eps"]
            sources.append("SEC EDGAR")
        elif sa.get("sa_eps") is not None:
            eps_reported = sa["sa_eps"]
            sources.append("stockanalysis")
        elif yf.get("yf_eps") is not None or yf.get("yf_reported_eps") is not None:
            eps_reported = yf.get("yf_eps") or yf.get("yf_reported_eps")
            sources.append("yfinance")

        # ── Revenue: SEC → SA → yfinance ──
        revenue = None
        if sec.get("sec_revenue") is not None:
            revenue = sec["sec_revenue"]
            if "SEC EDGAR" not in sources:
                sources.append("SEC EDGAR")
        elif sa.get("sa_revenue") is not None:
            revenue = sa["sa_revenue"]
            if "stockanalysis" not in sources:
                sources.append("stockanalysis")
        elif yf.get("yf_revenue") is not None:
            revenue = yf["yf_revenue"]
            if "yfinance" not in sources:
                sources.append("yfinance")

        # ── Net income: SEC → SA → yfinance ──
        net_income = None
        if sec.get("sec_net_income") is not None:
            net_income = sec["sec_net_income"]
            if "SEC EDGAR" not in sources:
                sources.append("SEC EDGAR")
        elif sa.get("sa_net_income") is not None:
            net_income = sa["sa_net_income"]
            if "stockanalysis" not in sources:
                sources.append("stockanalysis")
        elif yf.get("yf_net_income") is not None:
            net_income = yf["yf_net_income"]
            if "yfinance" not in sources:
                sources.append("yfinance")

        # Profit margin (calculated)
        profit_margin = None
        if net_income is not None and revenue is not None and revenue != 0:
            profit_margin = net_income / revenue

        # ── Balance sheet: SEC → yfinance ──
        inventory = None
        if sec.get("sec_inventory") is not None:
            inventory = sec["sec_inventory"]
        elif yf.get("yf_inventory") is not None:
            inventory = yf["yf_inventory"]

        receivables = None
        if sec.get("sec_receivables") is not None:
            receivables = sec["sec_receivables"]
        elif yf.get("yf_receivables") is not None:
            receivables = yf["yf_receivables"]

        # ── Earnings release date: SEC (authoritative) → yfinance ──
        earnings_release_date = sec.get("sec_filing_date", "")
        if not earnings_release_date:
            yf_date = yf.get("yf_earnings_date", "")
            if yf_date:
                # Validate: release date must be after quarter end
                try:
                    rel_dt = datetime.strptime(yf_date, "%Y-%m-%d")
                    qend_dt = datetime.strptime(quarter_end, "%Y-%m-%d") if quarter_end else None
                    if qend_dt and rel_dt >= qend_dt:
                        earnings_release_date = yf_date
                        notes.append("Release date from yfinance (no SEC filing date)")
                    elif qend_dt:
                        notes.append(f"yfinance release date {yf_date} rejected (before quarter end {quarter_end})")
                except ValueError:
                    pass

        # ── Analyst estimates (yfinance-exclusive) ──
        eps_estimate = yf.get("yf_eps_estimate")
        surprise_pct = yf.get("yf_surprise_pct")
        if eps_estimate is not None and "yfinance" not in sources:
            sources.append("yfinance")

        eps_adjusted = None

        # Track missing fields
        missing = []
        if eps_reported is None:
            missing.append("eps")
        if revenue is None:
            missing.append("revenue")
        if net_income is None:
            missing.append("net_income")
        if not earnings_release_date:
            missing.append("release_date")
        if missing:
            notes.append(f"Missing: {', '.join(missing)}")

        if not sources:
            sources.append("none")

        row = {
            "ticker": ticker,
            "fiscal_quarter": _fiscal_quarter_label(q_label),
            "quarter_end_date": quarter_end,
            "earnings_release_date": earnings_release_date,
            "eps_reported": eps_reported,
            "eps_adjusted": eps_adjusted,
            "revenue": revenue,
            "net_income": net_income,
            "profit_margin": round(profit_margin, 6) if profit_margin is not None else None,
            "inventory": inventory,
            "accounts_receivable": receivables,
            "analyst_eps_estimate": eps_estimate,
            "eps_surprise_pct": surprise_pct,
            "data_source": " + ".join(sources),
            "data_pulled_date": today_str,
            "confidence_note": "; ".join(notes) if notes else "",
        }
        rows.append(row)

    return rows


# ── Excel I/O ────────────────────────────────────────────────────────────────

COLUMNS = [
    "ticker", "fiscal_quarter", "quarter_end_date", "earnings_release_date",
    "eps_reported", "eps_adjusted", "revenue", "net_income", "profit_margin",
    "inventory", "accounts_receivable", "analyst_eps_estimate", "eps_surprise_pct",
    "data_source", "data_pulled_date", "confidence_note",
]


def load_existing(filepath):
    """Load existing Excel data, return set of (ticker, fiscal_quarter) keys."""
    if not filepath.exists():
        return pd.DataFrame(columns=COLUMNS), set()
    try:
        df = pd.read_excel(filepath, sheet_name=SHEET_NAME)
        existing_keys = set()
        for _, row in df.iterrows():
            existing_keys.add((row["ticker"], row["fiscal_quarter"]))
        return df, existing_keys
    except Exception as e:
        log.warning("Could not read existing file: %s", e)
        return pd.DataFrame(columns=COLUMNS), set()


def save_to_excel(new_rows, filepath):
    """Append new rows to Excel, skipping duplicates."""
    existing_df, existing_keys = load_existing(filepath)

    rows_to_add = []
    skipped = 0
    for row in new_rows:
        key = (row["ticker"], row["fiscal_quarter"])
        if key in existing_keys:
            skipped += 1
            continue
        rows_to_add.append(row)

    if not rows_to_add:
        log.info("No new rows to add (all %d already exist)", skipped)
        return 0

    new_df = pd.DataFrame(rows_to_add, columns=COLUMNS)
    combined = pd.concat([existing_df, new_df], ignore_index=True)
    combined.to_excel(filepath, sheet_name=SHEET_NAME, index=False, engine="openpyxl")

    log.info("Saved %d new rows (%d skipped as duplicates) → %s", len(rows_to_add), skipped, filepath)
    return len(rows_to_add)


# ── Orchestration ────────────────────────────────────────────────────────────

def process_ticker(ticker):
    """Full pipeline for one ticker: fetch from all sources, merge, return rows."""
    log.info("=" * 60)
    log.info("Processing %s", ticker)
    log.info("=" * 60)

    sec_data = fetch_sec_edgar(ticker)
    sa_data = fetch_stockanalysis(ticker)
    yf_data = fetch_yfinance(ticker)

    rows = merge_sources(ticker, yf_data, sec_data, sa_data)
    log.info("%s: %d quarterly rows merged", ticker, len(rows))
    return rows


def run_batch(tickers, filepath=OUTPUT_PATH):
    """Process a batch of tickers and save to Excel."""
    log.info("Starting batch: %d tickers → %s", len(tickers), filepath)
    start = time.time()

    all_rows = []
    summary = {"success": [], "partial": [], "failed": []}

    for i, ticker in enumerate(tickers, 1):
        log.info("[%d/%d] %s", i, len(tickers), ticker)
        try:
            rows = process_ticker(ticker)
            if rows:
                all_rows.extend(rows)
                has_eps = any(r["eps_reported"] is not None for r in rows)
                has_rev = any(r["revenue"] is not None for r in rows)
                if has_eps and has_rev:
                    summary["success"].append(ticker)
                else:
                    summary["partial"].append(ticker)
            else:
                summary["failed"].append(ticker)
        except Exception as e:
            log.error("Failed to process %s: %s", ticker, e)
            summary["failed"].append(ticker)

    saved = save_to_excel(all_rows, filepath)

    elapsed = time.time() - start
    log.info("")
    log.info("=" * 60)
    log.info("BATCH COMPLETE in %.1f seconds", elapsed)
    log.info("=" * 60)
    log.info("Total rows: %d (%d saved, rest were duplicates)", len(all_rows), saved)
    log.info("Success (full data): %s", summary["success"])
    log.info("Partial (some gaps): %s", summary["partial"])
    log.info("Failed: %s", summary["failed"])

    # Print source distribution
    source_counts = {}
    for row in all_rows:
        src = row["data_source"]
        source_counts[src] = source_counts.get(src, 0) + 1
    log.info("Source distribution:")
    for src, count in sorted(source_counts.items(), key=lambda x: -x[1]):
        log.info("  %s: %d rows", src, count)

    # Print rows with notes
    noted = [r for r in all_rows if r.get("confidence_note", "")]
    if noted:
        log.info("Rows with confidence notes: %d/%d", len(noted), len(all_rows))
        for r in noted:
            log.info("  %s %s: %s", r["ticker"], r["fiscal_quarter"], r["confidence_note"])

    return all_rows, summary


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    TEST_TICKERS = ["BURL", "MANH", "TTEK"]
    run_batch(TEST_TICKERS)
