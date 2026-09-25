"""
Merged fundamentals pipeline — custom + EdgarTools → single trusted dataset.
Reconciles field by field using explicit rules, derives Q4 EPS from
net_income / diluted shares, outputs Excel with per-field confidence.
"""
import sys, os, json, re, time, math, warnings, requests, traceback
from datetime import datetime, timedelta, date
from collections import Counter
from pathlib import Path
from statistics import median
import pandas as pd
import numpy as np
from fundamentals_store import STOCK_SPLITS

warnings.filterwarnings("ignore")

SCRATCHPAD = Path(__file__).resolve().parent
OUTPUT = SCRATCHPAD / "merged_fundamentals_v3.xlsx"

TICKERS = [
    # Previously tested (regression check) — 24
    "MANH","GOOGL","AMZN","BURL","TTEK",
    "AAPL","NVDA","WMT","CRM",
    "CELH","AXON","SMCI","DUOL","CROX",
    "FIX","RCL","ANF","CAVA","ONON",
    "RDDT","APP","VRT","CRWD","SFM",
    # Restatement test cases — 2
    "ADM","AES",
    # Additional non-calendar FY — 10
    "COST","HD","DE","ORCL","PANW",
    "FDX","NKE","MSFT","TGT","KR",
]
CUTOFF = datetime(2021, 1, 1)
SEC_EXTRACT_CUTOFF = datetime(2019, 7, 1)  # earlier cutoff for SEC API so Q4 derivation has Q1-Q3
SEC_UA = "KashifBacktest/1.0 (ahmed.marzouk@sprints.ai)"
SEC_DELAY = 0.15
DATE_TOL = 5
REV_NI_TOL = 0.005
EPS_TOL = 0.02

REV_CONCEPTS = [
    "Revenues",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenuesNetOfInterestExpense",
    "RegulatedAndUnregulatedOperatingRevenue",
    "RegulatedOperatingRevenue",
    "InvestmentBankingRevenue",
]
# Banks don't tag Revenues; press-release "total revenue" = NII + noninterest income.
BANK_NII_CONCEPTS = ["InterestIncomeExpenseNet"]
BANK_NONII_CONCEPTS = ["NoninterestIncome"]
# Only lenders tag these; non-banks use InterestIncomeExpenseNet for interest expense.
BANK_MARKER_CONCEPTS = ["NoninterestIncome", "InterestAndDividendIncomeOperating",
                        "InterestIncomeOperating", "InterestIncomeDebtSecuritiesOperating"]
# An annual fact filed later than this after FY end is a later 10-K's comparative
# (possibly restated for divestitures); quarters are as-originally-filed, so the
# annual must be too or Q4 = FY - Q1..Q3 mixes bases.
ANNUAL_ORIGINAL_FILING_DAYS = 300
NI_CONCEPTS = [
    "NetIncomeLoss","ProfitLoss",
    "NetIncomeLossAvailableToCommonStockholdersDiluted",
    "NetIncomeLossAvailableToCommonStockholdersBasic",
]
# EPS numerator: net income after preferred dividends / participating securities.
NI_COMMON_CONCEPTS = [
    "NetIncomeLossAvailableToCommonStockholdersDiluted",
    "NetIncomeLossAvailableToCommonStockholdersBasic",
]
EPS_CONCEPTS = ["EarningsPerShareDiluted","EarningsPerShareBasic"]
SHARES_CONCEPTS = [
    "WeightedAverageNumberOfDilutedSharesOutstanding",
    "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
]

# ═══════════════════════════════════════════════════════════════
#  CIK map
# ═══════════════════════════════════════════════════════════════
_cik = None
def cik_for(ticker):
    global _cik
    if _cik is None:
        r = requests.get("https://www.sec.gov/files/company_tickers.json",
                         headers={"User-Agent": SEC_UA}, timeout=15)
        r.raise_for_status(); time.sleep(SEC_DELAY)
        _cik = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in r.json().values()}
    return _cik.get(ticker.upper())

def _placeholder_zero(field, current, new):
    """A revenue of exactly 0 from a higher-priority concept yields to a later
    concept's non-zero value for the same period (FLS FY2023 Revenues = 0)."""
    return field == "revenue" and current == 0 and bool(new)


def _originally_filed(end, filed):
    try:
        lag = (datetime.strptime(filed, "%Y-%m-%d") - datetime.strptime(end, "%Y-%m-%d")).days
    except (ValueError, TypeError):
        return True
    return lag <= ANNUAL_ORIGINAL_FILING_DAYS

def _days(e):
    s, end = e.get("start",""), e.get("end","")
    if s and end:
        try: return (datetime.strptime(end,"%Y-%m-%d")-datetime.strptime(s,"%Y-%m-%d")).days
        except: pass
    return None

# ═══════════════════════════════════════════════════════════════
#  SEC API: clean extraction of quarterly + annual + shares
# ═══════════════════════════════════════════════════════════════

def _normalize_shares(shares_dict):
    """Rescale diluted shares filed in thousands or millions to a raw count
    (BRKR files 149 for 149M; CYTK files 71,200 for 71.2M). No constituent of
    this universe has under 1M diluted shares, so any smaller value is scaled
    by 1e3 or 1e6 -- whichever lands nearest the ticker's own raw-count values,
    or by magnitude when the ticker has none."""
    ref = sorted(v for v in shares_dict.values() if v and v >= 1_000_000)
    ref_med = ref[len(ref) // 2] if ref else None
    for k, v in list(shares_dict.items()):
        if v is None or v <= 0 or v >= 1_000_000:
            continue
        if ref_med:
            f = min((1e3, 1e6), key=lambda f: abs(math.log(v * f / ref_med)))
        else:
            f = 1e6 if v < 10_000 else 1e3
        shares_dict[k] = int(round(v * f))


def _infer_fy_end_month(entries):
    """FY-end month from the most common end month of 10-Q fp=Q1 facts."""
    months = Counter()
    for e in entries:
        if e.get("form") not in ("10-Q", "10-Q/A") or e.get("fp") != "Q1":
            continue
        d = _days(e)
        if d is None or not (60 <= d <= 120) or not e.get("end"):
            continue
        months[int(e["end"][5:7])] += 1
    if not months:
        return None
    q1_month = months.most_common(1)[0][0]
    return (q1_month + 9 - 1) % 12 + 1


def _synthetic_anchors(quarterly, fy_end_month):
    """FY anchors for filers whose companyfacts carry no 10-K annual facts.
    A 7-day slack absorbs 52/53-week calendars ending just after month-end."""
    years = [int(qv["end_date"][:4]) for qv in quarterly.values() if qv.get("end_date")]
    if not years:
        return []
    anchors = []
    for y in range(min(years) - 1, max(years) + 2):
        nxt = date(y + (fy_end_month == 12), fy_end_month % 12 + 1, 1)
        month_end = datetime.combine(nxt, datetime.min.time()) - timedelta(days=1)
        anchors.append((y, month_end + timedelta(days=7)))
    return anchors


def _relabel_quarters(quarterly, annuals, shares_dict, fy_end_month=None,
                      direct_q4=None):
    """Reassign quarterly entries to correct fiscal years using annual end
    dates as boundaries, then relabel Q1/Q2/Q3 by chronological position
    within each FY.  Fixes Q5+ labels from SEC fy mislabeling.
    Without annual facts, anchors are synthesized from fy_end_month.
    Direct 10-K Q4 facts are collected into direct_q4 (end_date -> entry)."""
    if not annuals:
        anchors = _synthetic_anchors(quarterly, fy_end_month) if fy_end_month else []
        if not anchors:
            return quarterly, shares_dict
        return _relabel_with_anchors(quarterly, shares_dict, anchors, 365, direct_q4)

    # Deduplicate annuals by end_date: when two FYs share a date,
    # keep the one whose fy is closest to the end_date's calendar year
    end_to_fy = {}
    for fy_str, ann in annuals.items():
        ed = ann["end_date"]
        fy = int(fy_str)
        ed_year = int(ed[:4])
        if ed not in end_to_fy:
            end_to_fy[ed] = fy
        else:
            old_fy = end_to_fy[ed]
            if abs(fy - ed_year) < abs(old_fy - ed_year):
                end_to_fy[ed] = fy

    anchors = sorted([(fy, datetime.strptime(ed, "%Y-%m-%d"))
                       for ed, fy in end_to_fy.items()],
                      key=lambda x: x[1])

    if len(anchors) >= 2:
        gaps = [(anchors[i+1][1] - anchors[i][1]).days
                for i in range(len(anchors)-1)]
        fy_len = min(gaps)
    else:
        fy_len = 365
    if fy_len < 300:
        fy_len = 365

    # Fill gaps where consecutive anchors span >1.5 FY lengths
    filled = [anchors[0]]
    for i in range(1, len(anchors)):
        gap_days = (anchors[i][1] - filled[-1][1]).days
        while gap_days > fy_len * 1.5:
            interp_fy = filled[-1][0] + 1
            interp_end = filled[-1][1] + timedelta(days=fy_len)
            filled.append((interp_fy, interp_end))
            gap_days = (anchors[i][1] - filled[-1][1]).days
        filled.append(anchors[i])
    anchors = filled

    # Ensure anchors have strictly increasing fy values (safety net
    # for XBRL convention changes that survive gap-filling).
    for i in range(1, len(anchors)):
        if anchors[i][0] <= anchors[i-1][0]:
            anchors[i] = (anchors[i-1][0] + 1, anchors[i][1])

    # Update annuals dict keys to match renumbered anchors
    anchor_end_to_fy = {a[1].strftime("%Y-%m-%d"): a[0] for a in anchors}
    new_annuals = {}
    for fy_str, ann in annuals.items():
        ed = ann["end_date"]
        new_fy = anchor_end_to_fy.get(ed, int(fy_str))
        new_fy_str = str(new_fy)
        ann["fy"] = new_fy
        new_annuals[new_fy_str] = ann
    annuals.clear()
    annuals.update(new_annuals)
    return _relabel_with_anchors(quarterly, shares_dict, anchors, fy_len, direct_q4)


def _relabel_with_anchors(quarterly, shares_dict, anchors, fy_len, direct_q4=None):
    # Find earliest/latest non-derived quarterly end dates
    q_dates = []
    for qv in quarterly.values():
        if qv.get("is_derived"):
            continue
        try:
            q_dates.append(datetime.strptime(qv["end_date"], "%Y-%m-%d"))
        except:
            pass
    if not q_dates:
        return quarterly, shares_dict
    earliest_q = min(q_dates)
    latest_q = max(q_dates)

    # Extend anchors backward to cover all early quarterly data
    while anchors[0][1] - timedelta(days=fy_len) >= earliest_q - timedelta(days=60):
        anchors.insert(0, (anchors[0][0] - 1,
                           anchors[0][1] - timedelta(days=fy_len)))

    # Extend anchors forward to cover all late quarterly data
    while anchors[-1][1] < latest_q:
        anchors.append((anchors[-1][0] + 1,
                        anchors[-1][1] + timedelta(days=fy_len)))

    # Build FY boundaries: (fy_int, lower_exclusive, upper_inclusive)
    boundaries = []
    for i, (fy_int, upper) in enumerate(anchors):
        lower = anchors[i - 1][1] if i > 0 else upper - timedelta(days=fy_len)
        boundaries.append((fy_int, lower, upper))

    # Group every non-derived quarterly entry into its FY bucket
    fy_groups = {}
    old_shares = {}
    for qk, qv in list(quarterly.items()):
        if qv.get("is_derived"):
            continue
        try:
            qed = datetime.strptime(qv["end_date"], "%Y-%m-%d")
        except:
            continue
        for fy_int, lower, upper in boundaries:
            if lower < qed <= upper:
                fy_groups.setdefault(fy_int, []).append(qv)
                break
        if qk in shares_dict:
            old_shares[qv["end_date"]] = shares_dict[qk]

    # Rebuild quarterly dict with correct Q1/Q2/Q3 labels per FY (cap at 3).
    # A later entry ending at the FY boundary is a 3-month Q4 fact from the
    # 10-K; keep it aside as a fallback for implausible Q4 derivations.
    fy_upper = {fy_int: upper for fy_int, _, upper in boundaries}
    fy_lower = {fy_int: lower for fy_int, lower, _ in boundaries}
    new_quarterly = {}
    for fy_int, entries in fy_groups.items():
        entries.sort(key=lambda v: v["end_date"])
        # A 3-month fact ending at the FY boundary is the 10-K's Q4, never
        # Q1-Q3; derive_q4 uses it when Q4 can't be derived or looks wrong.
        at_fy_end = [qv for qv in entries if abs(
            (fy_upper[fy_int] - datetime.strptime(qv["end_date"], "%Y-%m-%d")).days) <= 10]
        if direct_q4 is not None:
            for qv in at_fy_end:
                direct_q4[qv["end_date"]] = qv
        entries = [qv for qv in entries if qv not in at_fy_end]
        # A bucket spanning well over a year contains a fiscal-year-change
        # transition period (UA moved Dec->Mar with a Jan-Mar 2022 stub).
        # Measure from the true 12-month FY start and leave the stub out, so
        # it can't push a regular quarter past the Q1-Q3 cap.
        fy_start = fy_lower[fy_int]
        if (fy_upper[fy_int] - fy_start).days > fy_len + 45:
            fy_start = fy_upper[fy_int] - timedelta(days=fy_len)
            entries = [qv for qv in entries if
                       datetime.strptime(qv["end_date"], "%Y-%m-%d") > fy_start + timedelta(days=20)]
        # Number by elapsed months since FY start so a partial year (first
        # year after an IPO) isn't labeled from Q1; positional on collision.
        by_elapsed = [min(3, max(1, round(
            (datetime.strptime(qv["end_date"], "%Y-%m-%d") - fy_start).days / 91.3)))
            for qv in entries[:3]]
        use_elapsed = len(set(by_elapsed)) == len(by_elapsed) and by_elapsed == sorted(by_elapsed)
        for i, qv in enumerate(entries[:3]):
            q_num = by_elapsed[i] if use_elapsed else i + 1
            new_key = f"Q{q_num}_{fy_int}"
            qv["fp"] = f"Q{q_num}"
            qv["fy"] = fy_int
            new_quarterly[new_key] = qv

    # Rebuild shares dict keyed by the new quarterly keys
    new_shares = {}
    for sk, sv in shares_dict.items():
        if sk.startswith("FY_"):
            new_shares[sk] = sv
    for qk, qv in new_quarterly.items():
        ed = qv["end_date"]
        if ed in old_shares:
            new_shares.setdefault(qk, old_shares[ed])

    return new_quarterly, new_shares


def fetch_sec_full(ticker):
    """One SEC companyfacts call → quarterly, annual, shares dicts."""
    cik = cik_for(ticker)
    if not cik:
        return {}, {}, {}
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    # A throttled or dropped request must never look like "no filings": a
    # 2026-09-24 run lost 1,016 tickers that way. Retry, then raise.
    for attempt in range(6):
        try:
            r = requests.get(url, headers={"User-Agent": SEC_UA}, timeout=30)
            time.sleep(SEC_DELAY)
        except requests.exceptions.RequestException:
            if attempt == 5:
                raise
            time.sleep(2 ** attempt * 5)
            continue
        if r.status_code in (403, 429, 500, 502, 503, 504) and attempt < 5:
            time.sleep(2 ** attempt * 5)
            continue
        break
    if r.status_code == 404:
        return {}, {}, {}
    r.raise_for_status()
    facts = r.json().get("facts", {})
    if "us-gaap" not in facts:
        print(f"SKIP (no us-gaap — likely IFRS)", end=" ")
        return {}, {}, {}
    gaap = facts["us-gaap"]

    # ── helpers ──
    def _originals(entries):
        """For each unique end_date, find the original fiscal year.
        10-Q entries get priority over 10-K fp=FY quarterly-duration entries
        to guard against XBRL fy tagging errors in 10-K filings.
        Groups quarterly and annual entries separately."""
        q_orig_fy = {}
        q_from_10q = set()
        a_orig_fy = {}
        first_filed = {}
        n_facts = {}
        for e in entries:
            form = e.get("form",""); fp = e.get("fp","")
            end = e.get("end",""); fy = e.get("fy")
            if form not in ("10-Q","10-K","10-Q/A","10-K/A") or not end or fy is None:
                continue
            try:
                if datetime.strptime(end,"%Y-%m-%d") < SEC_EXTRACT_CUTOFF:
                    continue
            except: continue
            days = _days(e)
            fy_int = int(fy)
            filed = e.get("filed", "")
            if filed and (end not in first_filed or filed < first_filed[end]):
                first_filed[end] = filed
            n_facts[end] = n_facts.get(end, 0) + 1
            if form in ("10-Q","10-Q/A") and fp in ("Q1","Q2","Q3"):
                if days is not None and not (60 <= days <= 120): continue
                if end not in q_orig_fy or fy_int < q_orig_fy[end]:
                    q_orig_fy[end] = fy_int
                q_from_10q.add(end)
            elif form == "10-K" and fp == "Q4":
                if days is not None and not (60 <= days <= 120): continue
                if end not in q_from_10q:
                    if end not in q_orig_fy or fy_int < q_orig_fy[end]:
                        q_orig_fy[end] = fy_int
            elif form == "10-K" and fp == "FY":
                if days is not None and 60 <= days <= 120:
                    if end not in q_from_10q:
                        if end not in q_orig_fy or fy_int < q_orig_fy[end]:
                            q_orig_fy[end] = fy_int
                elif days is not None and days >= 300:
                    if end not in a_orig_fy or fy_int < a_orig_fy[end]:
                        a_orig_fy[end] = fy_int
            elif form in ("10-Q/A","10-K/A"):
                if days is not None and 60 <= days <= 120:
                    if end not in q_orig_fy or fy_int < q_orig_fy[end]:
                        q_orig_fy[end] = fy_int
                    q_from_10q.add(end)
                elif days is not None and days >= 300:
                    if end not in a_orig_fy or fy_int < a_orig_fy[end]:
                        a_orig_fy[end] = fy_int

        # Period ends within 10 days of each other are one period re-dated in a
        # later filing (ATI's 52/53-week switch re-presented 2022-03-31 as
        # 2022-04-03). Keep the end date filed first -- the original report --
        # otherwise the copy crowds real quarters out and triggers the fy
        # renumbering below. Same-day ties (JXN tags stray 2023-04-01 facts
        # beside 2023-03-31) go to the end date carrying more facts.
        ends_dt = {k: datetime.strptime(k, "%Y-%m-%d") for k in first_filed}
        rank = {k: (first_filed[k], -n_facts.get(k, 0)) for k in first_filed}
        def _redated(end, pool, window):
            d = ends_dt[end]
            return any(abs((d - ends_dt[k]).days) <= window and rank[k] < rank[end]
                       for k in pool if k != end and k in ends_dt)
        for end in [k for k in q_orig_fy if k in ends_dt and _redated(k, ends_dt, 10)]:
            del q_orig_fy[end]
        # Fiscal years can't end weeks apart (RBC: stray 2022-04-30 beside
        # the 2022-04-02 FY end), so annual ends get a wider window.
        a_pool = list(a_orig_fy)
        for end in [k for k in a_pool if k in ends_dt and _redated(k, a_pool, 60)]:
            del a_orig_fy[end]

        # Ensure unique fy per annual end_date: when a company changes
        # its XBRL fy convention mid-stream (CRWD skips fy=2025, KR jumps
        # from fy=2022 to fy=2024), minimum-fy maps two end_dates to the
        # same fy.
        if len(a_orig_fy) >= 2:
            sorted_a_ends = sorted(a_orig_fy.keys())
            has_collision = len(set(a_orig_fy.values())) < len(a_orig_fy)
            # Number every FY from its end date using the fy-vs-year offset of
            # originally filed 10-Ks, so one mis-tagged fy (AZZ, AAP) or a
            # first 10-K tagging its comparatives with its own year (AESI)
            # can't skip or shift labels. -20 days keeps 52/53-week years
            # ending Dec 28-Jan 3 on one fiscal year.
            def _adj_year(end):
                return (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=20)).year
            offsets = Counter()
            for e in entries:
                end = e.get("end", "")
                if (e.get("form") in ("10-K", "10-K/A") and e.get("fp") == "FY"
                        and end in a_orig_fy and e.get("fy") is not None
                        and (_days(e) or 0) >= 300
                        and _originally_filed(end, e.get("filed", ""))):
                    offsets[int(e["fy"]) - _adj_year(end)] += 1
            renumbered = None
            if offsets:
                off = offsets.most_common(1)[0][0]
                cand = {end: _adj_year(end) + off for end in sorted_a_ends}
                if len(set(cand.values())) == len(cand):
                    renumbered = cand
            if renumbered is None and has_collision:
                base_fy = a_orig_fy[sorted_a_ends[0]]
                renumbered = {end: base_fy + i for i, end in enumerate(sorted_a_ends)}
            if renumbered:
                a_orig_fy.update(renumbered)

        return q_orig_fy, a_orig_fy

    # Pre-compute GLOBAL _originals across ALL concepts so every concept
    # uses the same fy mapping. Per-concept _originals differ when concepts
    # have different subsets of fy values for the same end_date, causing
    # two FYs to share one end_date and losing anchors in _relabel_quarters.
    all_concept_names = list(REV_CONCEPTS) + list(NI_CONCEPTS) + list(EPS_CONCEPTS)
    all_entries_usd = []
    for c in all_concept_names:
        if c in gaap:
            all_entries_usd.extend(gaap[c].get("units",{}).get("USD",[]))
            all_entries_usd.extend(gaap[c].get("units",{}).get("USD/shares",[]))
    for c in SHARES_CONCEPTS:
        if c in gaap:
            all_entries_usd.extend(gaap[c].get("units",{}).get("shares",[]))
    global_q_orig, global_a_orig = _originals(all_entries_usd)

    def _extract(concepts, unit_key, target_q, target_a, field):
        """Extract field values keyed by end_date-based quarter labels.
        For each (end_date, original_fy), takes the latest-filed value
        to capture restatements while rejecting cross-year comparatives.
        Uses the global _originals mapping for consistent fy assignment."""
        for concept in concepts:
            if concept not in gaap: continue
            entries = gaap[concept].get("units",{}).get(unit_key,[])
            if not entries: continue
            q_orig_fy, a_orig_fy = global_q_orig, global_a_orig

            q_best = {}
            a_best = {}
            ytd9_best = {}  # Q3 end -> 9-month YTD value, as originally filed
            q_restated = {}  # quarter end -> value as re-presented a year later
            for e in entries:
                form = e.get("form",""); fp = e.get("fp","")
                end = e.get("end",""); fy = e.get("fy")
                val = e.get("val"); filed = e.get("filed","")
                if val is None or fy is None or not end: continue
                try:
                    if datetime.strptime(end,"%Y-%m-%d") < SEC_EXTRACT_CUTOFF:
                        continue
                except: continue
                fy_int = int(fy); days = _days(e)

                if (form in ("10-Q","10-Q/A") and fp == "Q3" and days is not None
                        and 250 <= days <= 290):
                    if fy_int == q_orig_fy.get(end, -1) and \
                            (end not in ytd9_best or filed > ytd9_best[end][1]):
                        ytd9_best[end] = (val, filed)
                    continue

                is_quarterly = False
                is_annual = False
                if form in ("10-Q","10-Q/A") and fp in ("Q1","Q2","Q3"):
                    if days is not None and not (60 <= days <= 120): continue
                    is_quarterly = True
                elif form in ("10-K","10-K/A") and fp == "Q4":
                    if days is not None and not (60 <= days <= 120): continue
                    is_quarterly = True
                elif form in ("10-K","10-K/A") and fp == "FY":
                    if days is not None and 60 <= days <= 120:
                        is_quarterly = True
                    elif days is not None and days >= 300:
                        is_annual = True
                    else:
                        continue
                elif form in ("10-Q/A","10-K/A"):
                    if days is not None and 75 <= days <= 105:
                        is_quarterly = True
                    elif days is not None and days >= 300:
                        is_annual = True
                    else:
                        continue
                else:
                    continue

                if is_quarterly:
                    orig = q_orig_fy.get(end, -1)
                    if fy_int == orig + 1 and form in ("10-Q", "10-Q/A"):
                        # Next year's comparative: restated for later spin-offs
                        if end not in q_restated or filed > q_restated[end][1]:
                            q_restated[end] = (val, filed)
                        continue
                    if fy_int != orig: continue
                    if end not in q_best or filed > q_best[end][1]:
                        q_best[end] = (val, filed, fy_int)
                elif is_annual:
                    if end not in a_orig_fy: continue
                    if not _originally_filed(end, filed): continue
                    norm_fy = a_orig_fy[end]
                    if end not in a_best or filed > a_best[end][1]:
                        a_best[end] = (val, filed, norm_fy)

            existing_end_qk = {qv["end_date"]: qk for qk, qv in target_q.items()}
            new_by_fy = {}
            found = False

            def _set_q(entry, end, val):
                # Record the concept (and its Q3 9-month YTD) so Q4 can be
                # derived as FY - YTD9 on one concept, like companies do.
                entry.pop(f"{field}_ytd9", None)
                entry.pop(f"{field}_restated", None)
                entry[field] = val
                entry[f"{field}_concept"] = concept
                if end in ytd9_best:
                    entry[f"{field}_ytd9"] = ytd9_best[end][0]
                if end in q_restated:
                    entry[f"{field}_restated"] = q_restated[end][0]

            for end, (val, filed, fy_int) in q_best.items():
                if end in existing_end_qk:
                    qk = existing_end_qk[end]
                    if field not in target_q[qk] or _placeholder_zero(field, target_q[qk][field], val):
                        _set_q(target_q[qk], end, val)
                        found = True
                else:
                    new_by_fy.setdefault(fy_int, []).append((end, val, filed))

            for fy_int, items in new_by_fy.items():
                fy_ends = set()
                for qk, qv in target_q.items():
                    if qv.get("fy") == fy_int:
                        fy_ends.add(qv["end_date"])
                for end, _, _ in items:
                    fy_ends.add(end)
                sorted_ends = sorted(fy_ends)
                end_to_label = {e: f"Q{i+1}" for i, e in enumerate(sorted_ends)}
                for end, val, filed in items:
                    q_label = end_to_label[end]
                    qk = f"{q_label}_{fy_int}"
                    # A later quarter created by an earlier concept pass may
                    # already hold this label (FHN: Q1 revenue untagged, so
                    # 06-30 took "Q1_2024"); key by date so 03-31 isn't lost.
                    # _relabel_quarters rebuilds all keys by date afterwards.
                    if qk in target_q and target_q[qk]["end_date"] != end:
                        qk = f"{q_label}_{fy_int}_{end}"
                    if qk not in target_q:
                        target_q[qk] = {"end_date": end, "fy": fy_int,
                                        "fp": q_label, "filed": filed}
                    if field not in target_q[qk]:
                        _set_q(target_q[qk], end, val)
                        found = True

            # Original 10-Q didn't tag this field (BFAM 2021 EPS, PTGX 2021
            # revenue): keep next year's comparative aside. Attached after all
            # passes, since the quarter entry may only be created later.
            for end, (val, filed) in q_restated.items():
                comparatives.setdefault((field, end), (val, filed))

            for end, (val, filed, fy_int) in sorted(a_best.items(), reverse=True):
                fy_str = str(fy_int)
                if fy_str not in target_a:
                    target_a[fy_str] = {"end_date": end, "fy": fy_int,
                                        "filed": filed}
                else:
                    existing_end = target_a[fy_str]["end_date"]
                    new_dist = abs(int(end[:4]) - fy_int)
                    old_dist = abs(int(existing_end[:4]) - fy_int)
                    if new_dist < old_dist:
                        target_a[fy_str]["end_date"] = end
                        target_a[fy_str]["fy"] = fy_int
                        target_a[fy_str]["filed"] = filed
                        for f in ("revenue","net_income","eps","ni_common","_nii","_nonii"):
                            target_a[fy_str].pop(f, None)
                            target_a[fy_str].pop(f"{f}_concept", None)
                            target_a[fy_str].pop(f"{f}_by_concept", None)
                if end != target_a[fy_str]["end_date"]:
                    continue
                # Every concept's annual value, so derive_q4 can subtract the
                # quarters from the SAME concept (FLS tags FY Revenues = 0,
                # WTFC tags no FY Revenues at all).
                target_a[fy_str].setdefault(f"{field}_by_concept", {}).setdefault(concept, val)
                if field not in target_a[fy_str] or _placeholder_zero(field, target_a[fy_str][field], val):
                    target_a[fy_str][field] = val
                    target_a[fy_str][f"{field}_concept"] = concept
                    found = True

    quarterly = {}  # qk -> {end_date, fy, fp, filed, revenue, net_income, eps}
    annuals   = {}  # fy_str -> {end_date, fy, filed, revenue, net_income, eps}
    comparatives = {}  # (field, end) -> (value, filed) from next year's 10-Q

    _extract(REV_CONCEPTS, "USD", quarterly, annuals, "revenue")
    _extract(NI_CONCEPTS, "USD", quarterly, annuals, "net_income")
    _extract(EPS_CONCEPTS, "USD/shares", quarterly, annuals, "eps")
    _extract(NI_COMMON_CONCEPTS, "USD", quarterly, annuals, "ni_common")
    _extract(["ProfitLoss"], "USD", quarterly, annuals, "ni_total")
    for qv in quarterly.values():
        for fld in ("revenue", "eps"):
            comp = comparatives.get((fld, qv["end_date"]))
            if comp and fld not in qv:
                qv[f"{fld}_comparative"] = comp

    # Bank mode: standard revenue concepts cover under half the NI periods.
    # Replace revenue for ALL periods so Q4 = FY - Q1..Q3 stays on one basis.
    ni_periods = [v for v in quarterly.values() if v.get("net_income") is not None]
    rev_periods = [v for v in ni_periods if v.get("revenue") is not None]
    is_lender = any(c in gaap for c in BANK_MARKER_CONCEPTS)
    # A bank (tags NoninterestIncome) always gets the composite, so every
    # period is on one basis: WTFC tags quarterly Revenues (= NII + non-II)
    # but no annual Revenues, and stopped tagging it in 2025.
    is_bank = "NoninterestIncome" in gaap
    if is_lender and ni_periods and (is_bank or len(rev_periods) < 0.5 * len(ni_periods)):
        _extract(BANK_NII_CONCEPTS, "USD", quarterly, annuals, "_nii")
        _extract(BANK_NONII_CONCEPTS, "USD", quarterly, annuals, "_nonii")
        periods = list(quarterly.values()) + list(annuals.values())
        niis = [v["_nii"] for v in periods if v.get("_nii") is not None]
        if niis and sum(n > 0 for n in niis) > len(niis) / 2:
            has_nonii = any(v.get("_nonii") is not None for v in periods)
            for v in periods:
                nii, nonii = v.pop("_nii", None), v.pop("_nonii", None)
                nii_ytd, nonii_ytd = v.get("_nii_ytd9"), v.get("_nonii_ytd9")
                for k in ("revenue", "revenue_concept", "revenue_ytd9", "revenue_restated",
                          "revenue_by_concept", "revenue_comparative"):
                    v.pop(k, None)
                if nii is None:
                    continue
                if has_nonii and nonii is not None:
                    v["revenue"] = nii + nonii
                    v["revenue_basis"] = "net interest income + noninterest income"
                    if nii_ytd is not None and nonii_ytd is not None:
                        v["revenue_ytd9"] = nii_ytd + nonii_ytd
                else:
                    v["revenue"] = nii
                    v["revenue_basis"] = "net interest income"
                    if nii_ytd is not None:
                        v["revenue_ytd9"] = nii_ytd
                if "revenue" in v:
                    v["revenue_concept"] = v["revenue_basis"]
        for v in periods:
            for k in ("_nii", "_nonii", "_nii_concept", "_nonii_concept",
                      "_nii_ytd9", "_nonii_ytd9", "_nii_restated", "_nonii_restated",
                      "_nii_comparative", "_nonii_comparative"):
                v.pop(k, None)

    # ── shares ──
    shares = {}
    late_fy_shares = {}  # end -> (val, fy): FY shares only in a later 10-K
    for concept in SHARES_CONCEPTS:
        if concept not in gaap: continue
        entries = gaap[concept].get("units",{}).get("shares",[])
        if not entries: continue
        q_orig_fy, a_orig_fy = global_q_orig, global_a_orig

        q_best = {}
        a_best = {}
        for e in entries:
            form = e.get("form",""); fp = e.get("fp","")
            end = e.get("end",""); fy = e.get("fy"); val = e.get("val")
            filed = e.get("filed","")
            if val is None or fy is None or not end: continue
            try:
                if datetime.strptime(end,"%Y-%m-%d") < SEC_EXTRACT_CUTOFF:
                    continue
            except: continue
            fy_int = int(fy); days = _days(e)

            is_quarterly = False
            is_annual = False
            if form in ("10-Q","10-Q/A") and fp in ("Q1","Q2","Q3"):
                if days is not None and not (60 <= days <= 120): continue
                is_quarterly = True
            elif form in ("10-K","10-K/A") and fp == "Q4":
                if days is not None and not (60 <= days <= 120): continue
                is_quarterly = True
            elif form in ("10-K","10-K/A") and fp == "FY":
                if days is not None and 60 <= days <= 120:
                    is_quarterly = True
                elif days is not None and days >= 300:
                    is_annual = True
                else:
                    continue
            elif form in ("10-Q/A","10-K/A"):
                if days is not None and 60 <= days <= 120:
                    is_quarterly = True
                elif days is not None and days >= 300:
                    is_annual = True
                else:
                    continue
            else:
                continue

            if is_quarterly:
                if fy_int != q_orig_fy.get(end, -1): continue
                if end not in q_best or filed > q_best[end][1]:
                    q_best[end] = (val, filed, fy_int)
            elif is_annual:
                if end not in a_orig_fy: continue
                if not _originally_filed(end, filed):
                    # Earliest later filing, i.e. the least re-presented copy
                    prev = late_fy_shares.get(end)
                    if prev is None or (prev[2] == concept and filed < prev[3]):
                        late_fy_shares[end] = (val, a_orig_fy[end], concept, filed)
                    continue
                norm_fy = a_orig_fy[end]
                if end not in a_best or filed > a_best[end][1]:
                    a_best[end] = (val, filed, norm_fy)

        existing_end_qk = {qv["end_date"]: qk for qk, qv in quarterly.items()}
        new_by_fy = {}
        for end, (val, filed, fy_int) in q_best.items():
            if end in existing_end_qk:
                shares.setdefault(existing_end_qk[end], val)
            else:
                new_by_fy.setdefault(fy_int, []).append((end, val, filed))

        for fy_int, items in new_by_fy.items():
            fy_ends = set()
            for qk, qv in quarterly.items():
                if qv.get("fy") == fy_int:
                    fy_ends.add(qv["end_date"])
            for end, _, _ in items:
                fy_ends.add(end)
            sorted_ends = sorted(fy_ends)
            end_to_label = {e: f"Q{i+1}" for i, e in enumerate(sorted_ends)}
            for end, val, filed in items:
                qk = f"{end_to_label[end]}_{fy_int}"
                shares.setdefault(qk, val)

        a_shares_by_fy = {}
        for end, (val, filed, fy_int) in a_best.items():
            a_shares_by_fy.setdefault(fy_int, []).append((end, val))
        for fy_int, candidates in a_shares_by_fy.items():
            best = min(candidates, key=lambda x: abs(int(x[0][:4]) - fy_int))
            shares.setdefault(f"FY_{fy_int}", best[1])

    # SSD tagged FY diluted shares only as later comparatives. Weighted shares
    # for a past year change only on a split, so derive_q4 accepts these only
    # when they agree with that year's as-filed Q1-Q3 shares.
    for end, (val, fy_int, _, _) in late_fy_shares.items():
        if f"FY_{fy_int}" not in shares:
            shares[f"FY_{fy_int}"] = val
            for ann in annuals.values():
                if ann["end_date"] == end:
                    ann["fy_shares_late"] = True

    # Relabel quarters using annual end dates as FY boundaries,
    # fixing Q5+ labels caused by SEC fy mislabeling.
    direct_q4 = {}
    quarterly, shares = _relabel_quarters(
        quarterly, annuals, shares,
        fy_end_month=_infer_fy_end_month(all_entries_usd), direct_q4=direct_q4)
    for ann in annuals.values():
        dq = direct_q4.get(ann["end_date"])
        if dq:
            ann["direct_q4"] = {f: dq[f] for f in ("revenue", "net_income", "eps")
                                if dq.get(f) is not None}

    _normalize_shares(shares)

    # Q1-Q3 whose original 10-Q didn't tag EPS: use next year's comparative
    # only if it is provably the same number basis -- identical net income
    # (not restated: BANC's comparative is PacWest's history), no known split
    # between the two filings, and implied shares in line with the ticker's.
    known_sh = sorted((quarterly[k]["end_date"], v) for k, v in shares.items()
                      if k in quarterly and v)
    for qk, qv in quarterly.items():
        comp = qv.get("eps_comparative")
        if qv.get("eps") is not None or not comp or not comp[0]:
            continue
        val, comp_filed = comp
        ni = qv.get("net_income")
        if ni is None or ni != qv.get("net_income_restated"):
            continue
        if any(qv.get("filed", "") < str(s["effective_date"]) <= comp_filed
               for s in STOCK_SPLITS.get(ticker, [])):
            continue
        near = [v for e, v in known_sh
                if abs((datetime.strptime(e, "%Y-%m-%d")
                        - datetime.strptime(qv["end_date"], "%Y-%m-%d")).days) <= 400]
        if near and not 0.75 <= (ni / val) / median(near) <= 1.33:
            continue
        qv["eps"] = val
        qv["eps_from_comparative"] = True

    # Same for revenue (PTGX 2021-23 tagged it only in later comparatives,
    # including genuine $0 quarters). Equal NI doesn't rule out a revenue
    # restatement (discontinued ops keep total NI), so also require that every
    # nearby quarter with both an original and a comparative revenue agrees.
    def _dt(s):
        return datetime.strptime(s, "%Y-%m-%d")
    both = [(qv["end_date"], qv["revenue"], qv["revenue_restated"]) for qv in quarterly.values()
            if qv.get("revenue") is not None and qv.get("revenue_restated") is not None]
    for qv in quarterly.values():
        comp = qv.get("revenue_comparative")
        if qv.get("revenue") is not None or not comp:
            continue
        ni = qv.get("net_income")
        if ni is None or ni != qv.get("net_income_restated"):
            continue
        near = [(o, r) for e, o, r in both if abs((_dt(e) - _dt(qv["end_date"])).days) <= 400]
        if any(o != r for o, r in near):
            continue
        qv["revenue"] = comp[0]
        qv["revenue_from_comparative"] = True

    # Cross-check filed EPS against NI/shares: XBRL scale errors produce EPS
    # like 810,000 where NI/shares gives 0.78.
    for qk, qv in quarterly.items():
        eps, sh = qv.get("eps"), shares.get(qk)
        ni = qv.get("ni_common", qv.get("net_income"))
        if eps is None or ni is None or not sh:
            continue
        implied = ni / sh
        if abs(eps) > 50 and abs(eps) > 20 * max(abs(implied), 0.01):
            qv["eps_filed"] = eps
            qv["eps"] = round(implied, 2)
            qv["eps_derived_from_shares"] = True

    # Derive missing EPS from NI/shares for any quarter (not just Q4)
    for qk, qv in quarterly.items():
        if qv.get("eps") is not None:
            continue
        ni = qv.get("ni_common", qv.get("net_income"))
        sh = shares.get(qk)
        if ni is not None and sh and sh > 0:
            qv["eps"] = round(ni / sh, 2)
            qv["eps_derived_from_shares"] = True

    return quarterly, annuals, shares


# ═══════════════════════════════════════════════════════════════
#  Q4 derivation
# ═══════════════════════════════════════════════════════════════

EPS_NUMERATORS = ("ni_common", "net_income", "ni_total")


def _eps_numerator(quarterly, shares, q_keys, q4):
    """Pick the NI measure that reproduces the company's own reported Q1-Q3
    diluted EPS against its diluted shares. UPREITs (PECO) count OP units in
    diluted shares, so the matching numerator is total NI including the OP-unit
    NCI; preferred issuers (REXR) need NI available to common."""
    best, best_err = None, None
    for f in EPS_NUMERATORS:
        if q4.get(f) is None:
            continue
        errs = []
        for qk in q_keys:
            qv, sh = quarterly[qk], shares.get(qk)
            if qv.get(f) is None or not sh or qv.get("eps") is None \
                    or qv.get("eps_derived_from_shares"):
                continue
            errs.append(abs(round(qv[f] / sh, 2) - qv["eps"]))
        if not errs:
            continue
        err = sum(errs) / len(errs)
        if best_err is None or err < best_err - 0.005:
            best, best_err = f, err
    if best:
        return best
    return next((f for f in EPS_NUMERATORS if q4.get(f) is not None), "net_income")


def derive_q4(quarterly, annuals, shares, ticker=None):
    """Derive Q4 revenue, NI, EPS for each fiscal year.
    Rule 2: Q4 EPS = Q4_NI / Q4_shares (not subtraction-based).
    Rule 4: Q4 rev/NI = FY - Q1 - Q2 - Q3, verified.
    Finds quarters by date range between consecutive annual end dates,
    not by fy-labeled keys (robust against SEC fy mislabeling).
    """
    q4_rows = {}

    sorted_ann = sorted(annuals.items(), key=lambda x: x[1]["end_date"])
    ann_end_dates = [datetime.strptime(a["end_date"], "%Y-%m-%d") for _, a in sorted_ann]

    for idx, (fy_str, ann) in enumerate(sorted_ann):
        fy_int = int(fy_str)
        ann_end = datetime.strptime(ann["end_date"], "%Y-%m-%d")
        prev_end = ann_end_dates[idx - 1] if idx > 0 else ann_end - timedelta(days=400)

        # Find non-derived quarterly entries whose end_date is in (prev_end, ann_end]
        fy_qkeys = []
        for qk, qv in quarterly.items():
            if qv.get("is_derived"):
                continue
            try:
                qed = datetime.strptime(qv["end_date"], "%Y-%m-%d")
            except:
                continue
            if prev_end < qed <= ann_end:
                fy_qkeys.append(qk)
        fy_qkeys.sort(key=lambda k: quarterly[k]["end_date"])

        q4k = f"Q4_{fy_int}"
        q4 = {"end_date": ann["end_date"], "fy": fy_int, "fp": "Q4",
               "filed": ann.get("filed",""), "is_derived": True}

        has_3q = len(fy_qkeys) >= 3

        for fld in ("revenue", "net_income", "ni_common", "ni_total"):
            av = ann.get(fld)
            if not has_3q:
                continue
            q_vals = [quarterly[qk].get(fld) for qk in fy_qkeys[:3]]
            if any(v is None for v in q_vals):
                continue
            q_concepts = {quarterly[qk].get(f"{fld}_concept") for qk in fy_qkeys[:3]}
            if av is None:
                continue
            if fld == "revenue" and len({quarterly[qk].get("revenue_basis") for qk in fy_qkeys[:3]}
                                        | {ann.get("revenue_basis")}) > 1:
                continue  # bank periods on different bases can't be subtracted
            # Prefer FY - 9M YTD: summing three separately rounded quarters
            # drifts by the rounding unit (BURL FY2022: $1K) from the Q4 the
            # company reports.
            q3 = quarterly[fy_qkeys[2]]
            ytd9 = q3.get(f"{fld}_ytd9")
            same_concept = (q3.get(f"{fld}_concept") is not None
                            and q3.get(f"{fld}_concept") == ann.get(f"{fld}_concept"))
            if ytd9 is not None and same_concept:
                derived = av - ytd9
            else:
                derived = av - sum(q_vals)
            q4[fld] = derived
            q4[f"{fld}_verified"] = True
            if fld == "revenue":
                q4["revenue_source"] = "derived"
                # FY and Q1-Q3 on one concept: FY - 9M is exact arithmetic, so a
                # big Q4 is real (biotech milestones), not a basis mismatch.
                q4["revenue_same_concept"] = (
                    len(q_concepts) == 1 and next(iter(q_concepts)) is not None
                    and next(iter(q_concepts)) == ann.get("revenue_concept"))
                # Negative Q4 from non-negative inputs, or a >3x spike, means the
                # annual and Q1-Q3 are on different bases (e.g. annual restated
                # for a divestiture, quarters as originally filed).
                def _implausible(d, qs):
                    return ((d < 0 and av >= 0 and min(qs) >= 0)
                            or d > 3 * max(abs(v) for v in qs))
                # Fallback 1: the annual value of the concept the quarters used.
                # Only as a fallback -- a concept can change meaning mid-year
                # (RCUS 2024 moved collaboration revenue out of it in the 10-K).
                qc = next(iter(q_concepts)) if len(q_concepts) == 1 else None
                alt = ann.get("revenue_by_concept", {}).get(qc)
                if _implausible(derived, q_vals) and alt is not None \
                        and qc != ann.get("revenue_concept") \
                        and not _implausible(alt - sum(q_vals), q_vals):
                    derived = alt - sum(q_vals)
                    q4["revenue"] = derived
                    q4["revenue_same_concept"] = True
                    q4["revenue_annual_concept_fallback"] = qc
                if _implausible(derived, q_vals):
                    direct = ann.get("direct_q4", {}).get("revenue")
                    restated = [quarterly[qk].get("revenue_restated") for qk in fy_qkeys[:3]]
                    if direct is not None:
                        q4["revenue"] = direct
                        q4["revenue_source"] = "direct_10k"
                    elif (all(v is not None for v in restated) and same_concept
                          and not _implausible(av - sum(restated), restated)):
                        q4["revenue"] = av - sum(restated)
                        q4["revenue_source"] = "derived_restated"
        # FY without three prior 10-Q quarters (spin-off, emergence, FY change):
        # fall back to the 10-K's own 3-month Q4 facts.
        for fld, val in ann.get("direct_q4", {}).items():
            if fld in ("revenue", "net_income") and fld not in q4:
                q4[fld] = val
                q4[f"{fld}_verified"] = True
                q4["q4_from_10k_fact"] = True
                if fld == "revenue":
                    q4["revenue_source"] = "direct_10k"
        if ann.get("revenue_basis"):
            q4["revenue_basis"] = ann["revenue_basis"]

        # Q4 shares: prefer directly-reported, else derive with split sanity check
        q4_shares = shares.get(q4k)
        shares_source = "direct"
        direct_eps = ann.get("direct_q4", {}).get("eps")
        if q4_shares is None:
            fy_shares = shares.get(f"FY_{fy_int}")
            # A split between a 10-Q and the 10-K leaves Q1-Q3 shares on the
            # old basis while the 10-K restates FY shares (NSSC FY2022: 4xFY -
            # sum(Q) gave 55M instead of 37M). Put the quarters on FY basis.
            q_sh = []
            for qk in (fy_qkeys[:3] if has_3q else []):
                s = shares.get(qk)
                if s is not None:
                    for sp in STOCK_SPLITS.get(ticker, []):
                        if quarterly[qk].get("filed", "") < str(sp["effective_date"]) <= ann.get("filed", ""):
                            s *= float(sp["ratio"])
                q_sh.append(s)
            if fy_shares and ann.get("fy_shares_late"):
                # Later-filed FY shares: the company's own Q4 EPS beats them,
                # and they're only usable on the same basis as Q1-Q3.
                known = [s for s in q_sh if s]
                if direct_eps is not None or not known \
                        or abs(fy_shares / (sum(known) / len(known)) - 1) > 0.15:
                    fy_shares = None
                else:
                    q4["fy_shares_late_used"] = True
            if fy_shares and len(q_sh) == 3 and all(s is not None for s in q_sh):
                derived_shares = 4 * fy_shares - sum(q_sh)
                if derived_shares > 0 and derived_shares < 2 * fy_shares:
                    q4_shares = derived_shares
                    shares_source = "derived"
                else:
                    q4_shares = fy_shares
                    shares_source = "annual_proxy(split)"
            elif fy_shares:
                q4_shares = fy_shares
                shares_source = "annual_proxy"
        if q4.get("fy_shares_late_used") and q4_shares is not None:
            shares_source += ", FY shares from a later 10-K"
        q4["shares"] = q4_shares
        q4["shares_source"] = shares_source

        q4_ni = q4.get(_eps_numerator(quarterly, shares, fy_qkeys[:3], q4))
        if q4_ni is not None and q4_shares and q4_shares > 0:
            q4["eps"] = round(q4_ni / q4_shares, 2)
            q4["eps_from_shares"] = True
        elif direct_eps is not None:
            q4["eps"] = direct_eps
            q4["eps_from_shares"] = False
            q4["eps_from_10k_fact"] = True
        else:
            q4["eps"] = None
            q4["eps_from_shares"] = False

        if q4k in quarterly:
            existing = quarterly[q4k]
            for fld in ("revenue", "net_income"):
                if fld in q4 and q4.get(f"{fld}_verified"):
                    existing[fld] = q4[fld]
                    existing[f"{fld}_verified"] = True
            for k in ("revenue_source", "q4_from_10k_fact", "revenue_same_concept"):
                if k in q4:
                    existing[k] = q4[k]
            existing["shares"] = q4.get("shares")
            existing["shares_source"] = q4.get("shares_source")
            if q4.get("eps_from_shares") or q4.get("eps_from_10k_fact"):
                existing["eps"] = q4["eps"]
                existing["eps_from_shares"] = q4.get("eps_from_shares", False)
                existing["eps_from_10k_fact"] = q4.get("eps_from_10k_fact", False)
            existing["is_derived"] = True
            q4_rows[q4k] = existing
        else:
            quarterly[q4k] = q4
            q4_rows[q4k] = q4

    return q4_rows


# ═══════════════════════════════════════════════════════════════
#  Load cached comparison data
# ═══════════════════════════════════════════════════════════════

def load_cached():
    try:
        with open(SCRATCHPAD / "custom_results.json") as f:
            custom = json.load(f)
    except FileNotFoundError:
        custom = []
    try:
        with open(SCRATCHPAD / "et_results.json") as f:
            et = json.load(f)
    except FileNotFoundError:
        et = []
    return custom, et


# ═══════════════════════════════════════════════════════════════
#  Matching & Reconciliation
# ═══════════════════════════════════════════════════════════════

def _close(a, b, tol_pct):
    if a == 0 and b == 0: return True
    if a == 0: return False
    return abs(a - b) / abs(a) <= tol_pct

def _date_close(d1, d2, tol=DATE_TOL):
    try:
        return abs(datetime.strptime(d1,"%Y-%m-%d") - datetime.strptime(d2,"%Y-%m-%d")).days <= tol
    except: return False

def reconcile_ticker(ticker, sec_q, sec_a, sec_shares, custom_rows, et_rows):
    """Reconcile all sources for one ticker.  Returns list of final rows."""

    # Index cached data by quarter_end_date
    c_by_date = {}
    for r in custom_rows:
        if r["ticker"] == ticker:
            c_by_date.setdefault(r["quarter_end_date"], r)
    e_by_date = {}
    for r in et_rows:
        if r["ticker"] == ticker:
            e_by_date.setdefault(r["quarter_end_date"], r)

    # Index SEC fresh data by end_date
    sec_by_date = {}
    for qk, qv in sec_q.items():
        sec_by_date.setdefault(qv["end_date"], qv)

    # Collect all unique quarter_end_dates across all sources
    all_dates = set()
    all_dates.update(c_by_date.keys())
    all_dates.update(e_by_date.keys())
    all_dates.update(sec_by_date.keys())

    # Merge close dates
    sorted_dates = sorted(all_dates)
    canonical = {}  # raw_date -> canonical_date
    used = set()
    for d in sorted_dates:
        if d in used:
            continue
        canonical[d] = d
        used.add(d)
        for d2 in sorted_dates:
            if d2 in used: continue
            if _date_close(d, d2):
                canonical[d2] = d
                used.add(d2)

    # Group data by canonical date
    groups = {}  # canonical_date -> {custom, et, sec}
    for d, cd in canonical.items():
        if cd not in groups:
            groups[cd] = {"custom": None, "et": None, "sec": None}
        if d in c_by_date and groups[cd]["custom"] is None:
            groups[cd]["custom"] = c_by_date[d]
        if d in e_by_date and groups[cd]["et"] is None:
            groups[cd]["et"] = e_by_date[d]
        if d in sec_by_date and groups[cd]["sec"] is None:
            groups[cd]["sec"] = sec_by_date[d]

    rows = []
    eps_mismatches = []

    for qdate in sorted(groups.keys()):
        # Skip quarters before the output cutoff
        try:
            if datetime.strptime(qdate, "%Y-%m-%d") < CUTOFF:
                continue
        except:
            continue

        g = groups[qdate]
        c = g["custom"]   # cached custom pipeline row
        e = g["et"]        # cached EdgarTools row
        s = g["sec"]       # fresh SEC API parse

        is_q4 = False
        if s and s.get("is_derived"):
            is_q4 = True
        elif s and s.get("fp") == "Q4":
            is_q4 = True
        elif c and "Q4" in c.get("note", ""):
            is_q4 = True
        elif e and "Q4" in str(e.get("form", "")):
            is_q4 = True

        # SEC relabeling is anchored to the company's own 10-K fiscal years;
        # the cached custom label is only a fallback (it mislabels CRM FY2026 Q4).
        fiscal_q = ""
        if s:
            fiscal_q = f"{s.get('fp','Q?')} {s.get('fy','')}"
        elif c and c.get("fiscal_quarter"):
            fiscal_q = c["fiscal_quarter"]

        row = {"ticker": ticker, "quarter_end_date": qdate,
               "fiscal_quarter": fiscal_q, "is_q4": is_q4}
        notes = []

        # ── REVENUE ──
        c_rev = c.get("revenue") if c else None
        e_rev = e.get("revenue") if e else None
        s_rev = s.get("revenue") if s else None

        row["_rev_derived"] = bool(is_q4 and s and s.get("revenue_source") == "derived")
        row["_rev_same_concept"] = bool(s and s.get("revenue_same_concept"))
        row["_ni_common"] = s.get("ni_common") if s else None
        if is_q4 and s_rev is not None and s.get("revenue_source") in ("direct_10k", "derived_restated"):
            row["revenue"] = s_rev
            row["revenue_conf"] = "SINGLE_SOURCE"
            if s["revenue_source"] == "direct_10k":
                notes.append("Q4 rev from 10-K 3-month fact (FY-Q1-Q2-Q3 on mismatched bases)")
            else:
                notes.append("Q4 rev = FY - Q1..Q3 as restated in next year's 10-Qs "
                             "(original quarters include since-discontinued ops)")
        elif is_q4 and s_rev is not None:
            matches_et = e_rev is not None and _close(s_rev, e_rev, REV_NI_TOL)
            matches_custom = c_rev is not None and _close(s_rev, c_rev, REV_NI_TOL)
            row["revenue"] = s_rev
            if matches_et or matches_custom:
                row["revenue_conf"] = "HIGH_CONFIDENCE"
                src = []
                if matches_et: src.append("ET")
                if matches_custom: src.append("custom")
                notes.append(f"Q4 rev derived, confirmed by {'+'.join(src)}")
            elif c_rev is not None or e_rev is not None:
                row["revenue_conf"] = "RECONCILED"
                notes.append(f"Q4 rev derived (SEC={s_rev:,.0f})")
            else:
                row["revenue_conf"] = "SINGLE_SOURCE"
                notes.append("Q4 rev derived from SEC FY-Q1-Q2-Q3, no independent check")
        elif c_rev is not None and e_rev is not None:
            if _close(c_rev, e_rev, REV_NI_TOL):
                row["revenue"] = e_rev
                row["revenue_conf"] = "HIGH_CONFIDENCE"
            else:
                row["revenue"] = e_rev
                row["revenue_conf"] = "RECONCILED"
                notes.append(f"Rev disagree (concept order): custom={c_rev:,.0f} vs ET={e_rev:,.0f}")
        elif e_rev is not None:
            row["revenue"] = e_rev
            row["revenue_conf"] = "SINGLE_SOURCE"
        elif c_rev is not None:
            row["revenue"] = c_rev
            row["revenue_conf"] = "SINGLE_SOURCE"
        elif s_rev is not None:
            row["revenue"] = s_rev
            row["revenue_conf"] = "SINGLE_SOURCE"
        else:
            row["revenue"] = None
            row["revenue_conf"] = "NEEDS_MANUAL_REVIEW"
        if s and s.get("revenue_basis") and row.get("revenue") is not None:
            notes.append(f"revenue basis: {s['revenue_basis']}")
        if s and s.get("revenue_from_comparative") and row.get("revenue") is not None:
            notes.append("revenue from next year's 10-Q comparative (original 10-Q untagged; "
                         "no restatement nearby)")
        if is_q4 and s and s.get("q4_from_10k_fact"):
            notes.append("Q4 from 10-K 3-month facts (FY lacks three prior 10-Q quarters)")

        # ── NET INCOME ──
        c_ni = c.get("net_income") if c else None
        e_ni = e.get("net_income") if e else None
        s_ni = s.get("net_income") if s else None

        if is_q4 and s_ni is not None:
            matches_et = e_ni is not None and _close(s_ni, e_ni, REV_NI_TOL)
            matches_custom = c_ni is not None and _close(s_ni, c_ni, REV_NI_TOL)
            row["net_income"] = s_ni
            if matches_et or matches_custom:
                row["net_income_conf"] = "HIGH_CONFIDENCE"
                src = []
                if matches_et: src.append("ET")
                if matches_custom: src.append("custom")
                notes.append(f"Q4 NI derived, confirmed by {'+'.join(src)}")
            elif c_ni is not None or e_ni is not None:
                row["net_income_conf"] = "RECONCILED"
                notes.append(f"Q4 NI derived (SEC={s_ni:,.0f})")
            else:
                row["net_income_conf"] = "SINGLE_SOURCE"
                notes.append("Q4 NI derived from SEC FY-Q1-Q2-Q3, no independent check")
        elif c_ni is not None and e_ni is not None:
            if _close(c_ni, e_ni, REV_NI_TOL):
                row["net_income"] = e_ni
                row["net_income_conf"] = "HIGH_CONFIDENCE"
            else:
                row["net_income"] = e_ni
                row["net_income_conf"] = "RECONCILED"
                notes.append(f"NI disagree: c={c_ni:,.0f} e={e_ni:,.0f}")
        elif e_ni is not None:
            row["net_income"] = e_ni
            row["net_income_conf"] = "SINGLE_SOURCE"
        elif c_ni is not None:
            row["net_income"] = c_ni
            row["net_income_conf"] = "SINGLE_SOURCE"
        elif s_ni is not None:
            row["net_income"] = s_ni
            row["net_income_conf"] = "SINGLE_SOURCE"
        else:
            row["net_income"] = None
            row["net_income_conf"] = "NEEDS_MANUAL_REVIEW"

        # ── EPS ──
        c_eps = c.get("eps") if c else None
        e_eps = e.get("eps") if e else None

        if is_q4:
            # Rule 2: Q4 EPS = Q4_NI / Q4_shares (not subtraction-based)
            q4_eps_set = False
            if s and s.get("eps_from_shares") and s.get("eps") is not None:
                row["eps"] = s["eps"]
                row["eps_conf"] = "RECONCILED"
                src = s.get("shares_source","?")
                notes.append(f"Q4 EPS = NI/shares ({src} shares)")
                q4_eps_set = True
            elif s and s.get("eps_from_10k_fact") and s.get("eps") is not None:
                row["eps"] = s["eps"]
                row["eps_conf"] = "SINGLE_SOURCE"
                notes.append("Q4 EPS as filed in the 10-K (no Q4 share count to derive from)")
                q4_eps_set = True
            elif row.get("net_income") is not None and s and s.get("shares") and s["shares"] > 0:
                row["eps"] = round(row["net_income"] / s["shares"], 2)
                row["eps_conf"] = "RECONCILED"
                src = s.get("shares_source","?") if s else "?"
                notes.append(f"Q4 EPS from reconciled NI / shares ({src})")
                q4_eps_set = True
            if not q4_eps_set:
                # Fallback: use EdgarTools or custom Q4 EPS if available
                # (subtraction-based — less reliable but better than nothing)
                if e_eps is not None and (c_eps is None or abs(c_eps - e_eps) <= EPS_TOL):
                    row["eps"] = e_eps
                    row["eps_conf"] = "SINGLE_SOURCE"
                    notes.append("Q4 EPS fallback to EdgarTools (no shares data)")
                elif c_eps is not None:
                    row["eps"] = c_eps
                    row["eps_conf"] = "SINGLE_SOURCE"
                    notes.append("Q4 EPS fallback to custom (no shares data)")
                else:
                    row["eps"] = None
                    row["eps_conf"] = "NEEDS_MANUAL_REVIEW"
                    notes.append("Q4 EPS: no shares data for derivation")
        elif c_eps is not None and e_eps is not None:
            if abs(c_eps - e_eps) <= EPS_TOL:
                row["eps"] = e_eps
                row["eps_conf"] = "HIGH_CONFIDENCE"
            else:
                # Rule 3: prefer EdgarTools, log mismatch
                row["eps"] = e_eps
                row["eps_conf"] = "RECONCILED"
                eps_mismatches.append({"ticker": ticker, "quarter": qdate,
                    "custom_eps": c_eps, "et_eps": e_eps,
                    "diff": round(e_eps - c_eps, 4)})
                notes.append(f"EPS concept mismatch: custom={c_eps} ET={e_eps}")
        elif e_eps is not None:
            row["eps"] = e_eps
            row["eps_conf"] = "SINGLE_SOURCE"
        elif c_eps is not None:
            row["eps"] = c_eps
            row["eps_conf"] = "SINGLE_SOURCE"
        elif s and s.get("eps") is not None:
            row["eps"] = s["eps"]
            if s.get("eps_derived_from_shares"):
                row["eps_conf"] = "SINGLE_SOURCE"
                if s.get("eps_filed") is not None:
                    notes.append(f"EPS derived from SEC NI/shares (filed XBRL EPS "
                                 f"{s['eps_filed']:,.2f} rejected as scale error)")
                else:
                    notes.append("EPS derived from SEC NI/shares")
            else:
                row["eps_conf"] = "SINGLE_SOURCE"
                if s.get("eps_from_comparative"):
                    notes.append("EPS from next year's 10-Q comparative (original 10-Q "
                                 "untagged; same NI, no split between)")
        else:
            row["eps"] = None
            row["eps_conf"] = "NEEDS_MANUAL_REVIEW"

        # ── EARNINGS RELEASE DATE ──
        c_rd = c.get("earnings_release_date","") if c else ""
        e_rd = e.get("earnings_release_date","") if e else ""
        s_rd = s.get("filed","") if s else ""

        rd = c_rd or e_rd or s_rd
        if c_rd and e_rd and _date_close(c_rd, e_rd, 3):
            row["earnings_release_date"] = c_rd
            row["release_date_conf"] = "HIGH_CONFIDENCE"
        elif c_rd and e_rd:
            row["earnings_release_date"] = min(c_rd, e_rd)
            row["release_date_conf"] = "RECONCILED"
            notes.append(f"Release date: picked earlier of c={c_rd} e={e_rd}")
        elif rd:
            row["earnings_release_date"] = rd
            row["release_date_conf"] = "SINGLE_SOURCE"
        else:
            row["earnings_release_date"] = ""
            row["release_date_conf"] = "NEEDS_MANUAL_REVIEW"

        row["notes"] = "; ".join(notes) if notes else ""
        rows.append(row)

    return rows, eps_mismatches


# ═══════════════════════════════════════════════════════════════
#  Rule 5 — Sanity checks
# ═══════════════════════════════════════════════════════════════

def _add_note(r, text):
    r["notes"] = f"{r['notes']}; {text}" if r.get("notes") else text


def sanity_check(rows):
    """Reject arithmetic artifacts; flag (but keep) unusual filed values.

    Revenue checks only null values WE derived (Q4 = FY - Q1..Q3), since a
    negative or spiking derived Q4 means the inputs were on different bases.
    Directly filed values are what the company reported -- e.g. CNX/JXN total
    revenue is negative in quarters with large hedge losses, ARWR books
    one-off licensing revenue -- so those get a FLAG note instead."""
    by_ticker = {}
    for r in rows:
        by_ticker.setdefault(r["ticker"], []).append(r)

    rejected = []

    for tk, trows in by_ticker.items():
        trows.sort(key=lambda x: x["quarter_end_date"])
        files_negative_rev = any(
            (x.get("revenue") or 0) < 0 and not x.get("_rev_derived") for x in trows)

        for i, r in enumerate(trows):
            ni = r.get("net_income")
            eps = r.get("eps")
            rev = r.get("revenue")
            derived = r.get("_rev_derived", False)

            # Check 1: EPS sign vs the NI it is computed from (NI available to
            # common when tagged: preferred/deemed dividends can flip the sign)
            ni_eps = r.get("_ni_common") if r.get("_ni_common") is not None else ni
            if ni_eps is not None and eps is not None:
                if (ni_eps > 0 and eps < -0.05) or (ni_eps < 0 and eps > 0.05):
                    rejected.append(f"{tk} {r['quarter_end_date']}: EPS sign ({eps}) vs NI sign ({ni_eps})")
                    r["eps"] = None
                    r["eps_conf"] = "NEEDS_MANUAL_REVIEW"
                    _add_note(r, "REJECTED: EPS/NI sign mismatch")

            # Check 2: revenue > 3x any adjacent quarter
            if rev is not None and rev > 0:
                adj_revs = []
                if i > 0:
                    pr = trows[i-1].get("revenue")
                    if pr and pr > 0: adj_revs.append(pr)
                if i < len(trows)-1:
                    nr = trows[i+1].get("revenue")
                    if nr and nr > 0: adj_revs.append(nr)
                if adj_revs:
                    max_adj = max(adj_revs)
                    if rev > 3.0 * max_adj:
                        msg = f"{tk} {r['quarter_end_date']}: rev {rev:,.0f} > 3x adj {max_adj:,.0f}"
                        if derived and not r.get("_rev_same_concept"):
                            rejected.append(msg)
                            r["revenue"] = None
                            r["revenue_conf"] = "NEEDS_MANUAL_REVIEW"
                            _add_note(r, "REJECTED: derived Q4 revenue > 3x adjacent")
                        else:
                            _add_note(r, "FLAG: revenue > 3x adjacent quarter ("
                                      + ("FY - 9M on one concept" if derived else "as filed") + ")")

            # Check 3: negative revenue
            if rev is not None and rev < 0:
                msg = f"{tk} {r['quarter_end_date']}: negative revenue {rev:,.0f}"
                if derived and not files_negative_rev:
                    rejected.append(msg)
                    r["revenue"] = None
                    r["revenue_conf"] = "NEEDS_MANUAL_REVIEW"
                    _add_note(r, "REJECTED: negative derived Q4 revenue")
                else:
                    _add_note(r, "FLAG: negative total revenue as filed")

            # Check 4: extreme EPS magnitude (filing errors or shares-units bugs)
            if eps is not None and abs(eps) > 500:
                rejected.append(f"{tk} {r['quarter_end_date']}: extreme EPS {eps:,.2f}")
                r["eps"] = None
                r["eps_conf"] = "NEEDS_MANUAL_REVIEW"
                _add_note(r, f"REJECTED: extreme EPS ({eps:,.2f})")

    return rejected


# ═══════════════════════════════════════════════════════════════
#  Excel output
# ═══════════════════════════════════════════════════════════════

COLS = [
    "ticker","fiscal_quarter","quarter_end_date",
    "revenue","revenue_conf",
    "net_income","net_income_conf",
    "eps","eps_conf",
    "earnings_release_date","release_date_conf",
    "notes",
]

def write_excel(rows, eps_log, rejected, path):
    df = pd.DataFrame(rows, columns=COLS + ["is_q4"])
    df.sort_values(["ticker","quarter_end_date"], inplace=True)
    df.drop(columns=["is_q4"], inplace=True, errors="ignore")

    with pd.ExcelWriter(path, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="merged_data", index=False)
        if eps_log:
            pd.DataFrame(eps_log).to_excel(w, sheet_name="EPS_concept_mismatches", index=False)
        if rejected:
            pd.DataFrame({"rejected": rejected}).to_excel(w, sheet_name="sanity_rejections", index=False)
    print(f"\nSaved -> {path}")


# ═══════════════════════════════════════════════════════════════
#  Verification & reporting
# ═══════════════════════════════════════════════════════════════

def verify_restatements(rows, sec_data_map):
    """For AES, show original vs restated NI for Q2/Q3 2024 and confirm pipeline selection."""
    print(f"\n{'='*60}")
    print(f"  AES RESTATEMENT VERIFICATION")
    print(f"{'='*60}")

    aes_q, aes_a, aes_sh = sec_data_map.get("AES", ({}, {}, {}))

    restatement_cases = [
        ("Q2 2024", "2024-06-30", 185_000_000, 276_000_000),
        ("Q3 2024", "2024-09-30", 502_000_000, 504_000_000),
    ]

    for label, end_date, orig_val, restated_val in restatement_cases:
        pipeline_row = [r for r in rows
                        if r["ticker"] == "AES" and r["quarter_end_date"] == end_date]
        pipeline_ni = pipeline_row[0].get("net_income") if pipeline_row else None
        pipeline_conf = pipeline_row[0].get("net_income_conf","") if pipeline_row else ""

        selected_restated = pipeline_ni is not None and pipeline_ni == restated_val
        selected_original = pipeline_ni is not None and pipeline_ni == orig_val

        print(f"\n  AES {label} (end={end_date}):")
        print(f"    Originally filed NI:  ${orig_val:>15,}")
        print(f"    Restated NI:          ${restated_val:>15,}")
        print(f"    Pipeline selected:    ${pipeline_ni:>15,}  conf={pipeline_conf}" if pipeline_ni else f"    Pipeline selected:    MISSING")
        if selected_restated:
            print(f"    -> CORRECT: Pipeline selected the restated value")
        elif selected_original:
            print(f"    -> WRONG: Pipeline selected the stale original value")
        else:
            print(f"    -> UNEXPECTED: Pipeline selected neither original nor restated")

    # ADM: confirm no NI restatement exists
    print(f"\n  ADM RESTATEMENT STATUS:")
    print(f"    ADM's 2023-2024 restatements affected segment disclosures only.")
    print(f"    Consolidated NetIncomeLoss was NOT restated in XBRL.")
    print(f"    (Verified from raw SEC CompanyFacts data.)")


def duplicate_ni_scan(rows):
    """Check for suspiciously repeated NI values within each ticker (the original fp-keying bug pattern)."""
    by_ticker = {}
    for r in rows:
        by_ticker.setdefault(r["ticker"], []).append(r)

    flagged = []
    for tk, trows in sorted(by_ticker.items()):
        trows.sort(key=lambda x: x["quarter_end_date"])
        ni_vals = [(r["quarter_end_date"], r.get("net_income")) for r in trows
                   if r.get("net_income") is not None]
        for i in range(len(ni_vals) - 2):
            d1, v1 = ni_vals[i]
            d2, v2 = ni_vals[i+1]
            d3, v3 = ni_vals[i+2]
            if v1 == v2 == v3 and v1 != 0:
                flagged.append(f"{tk}: NI={v1:,.0f} repeated at {d1}, {d2}, {d3}")
    return flagged


def verify_and_report(rows):
    # ── Missing data ──
    fields = ["revenue","net_income","eps","earnings_release_date"]
    total_pts = len(rows) * len(fields)
    missing = 0
    for r in rows:
        for f in fields:
            v = r.get(f)
            if v is None or v == "":
                missing += 1
    pct = missing / total_pts * 100 if total_pts else 0
    print(f"\n{'='*60}")
    print(f"  MISSING DATA")
    print(f"{'='*60}")
    print(f"  Total data points: {total_pts} ({len(rows)} rows x {len(fields)} fields)")
    print(f"  Missing:           {missing} ({pct:.2f}%)")
    print(f"  Target:            <=1.00%  {'PASS' if pct <= 1.0 else 'FAIL'}")

    # Break down missing by field
    for f in fields:
        miss_f = sum(1 for r in rows if r.get(f) is None or r.get(f) == "")
        print(f"    {f:<25} missing={miss_f}")
    # Show which rows have missing data
    missing_rows = [(r["ticker"], r["quarter_end_date"], [f for f in fields if r.get(f) is None or r.get(f) == ""])
                     for r in rows if any(r.get(f) is None or r.get(f) == "" for f in fields)]
    if missing_rows:
        print(f"\n  Missing data detail ({len(missing_rows)} rows affected):")
        for tk, qd, mf in sorted(missing_rows):
            print(f"    {tk:<5} {qd}  missing: {', '.join(mf)}")

    # ── Confidence distribution ──
    conf_fields = ["revenue_conf","net_income_conf","eps_conf","release_date_conf"]
    conf_counts = {}
    for r in rows:
        for cf in conf_fields:
            v = r.get(cf,"")
            conf_counts[v] = conf_counts.get(v, 0) + 1
    print(f"\n{'='*60}")
    print(f"  CONFIDENCE DISTRIBUTION")
    print(f"{'='*60}")
    for k in ["HIGH_CONFIDENCE","RECONCILED","SINGLE_SOURCE","NEEDS_MANUAL_REVIEW"]:
        print(f"  {k:<25} {conf_counts.get(k,0):>5}")

    # ── Specific verifications ──
    checks = [
        ("BURL", "2023-01", "Q4 FY2022", {"revenue": 2_744_283_000, "net_income": 185_200_000}),
        ("BURL", "2024-02", "Q4 FY2023", {"revenue": 3_126_358_000, "net_income": 227_458_000}),
        ("TTEK", "2024-06", "Q3 FY2024", {"eps": 1.59}),
        ("TTEK", "2024-09", "Q4 FY2024", {"eps": 0.35}),
        ("CRM",  "2025-01", "Q4 FY2025", {"revenue": 9_993_000_000, "net_income": 1_708_000_000}),
    ]

    print(f"\n{'='*60}")
    print(f"  SPECIFIC VERIFICATIONS")
    print(f"{'='*60}")
    for ticker, date_prefix, label, expected in checks:
        match = [r for r in rows
                 if r["ticker"] == ticker and r["quarter_end_date"].startswith(date_prefix)]
        if not match:
            print(f"\n  {ticker} {label}: NOT FOUND")
            continue
        r = match[0]
        print(f"\n  {ticker} {label} (quarter_end_date={r['quarter_end_date']}):")
        all_ok = True
        for field, exp_val in expected.items():
            actual = r.get(field)
            conf = r.get(f"{field}_conf","")
            if field == "eps":
                ok = actual is not None and abs(actual - exp_val) <= 0.02
                print(f"    {field:<12} expected={exp_val:<15} actual={actual:<15} conf={conf:<20} {'OK' if ok else 'MISMATCH'}")
            else:
                ok = actual is not None and actual == exp_val
                if not ok and actual is not None:
                    pct_diff = abs(actual - exp_val) / abs(exp_val) * 100 if exp_val else 0
                    print(f"    {field:<12} expected={exp_val:<15,} actual={actual:<15,.0f} conf={conf:<20} MISMATCH ({pct_diff:.2f}%)")
                else:
                    print(f"    {field:<12} expected={exp_val:<15,} actual={str(actual) + (f' ({actual:,.0f})' if actual else ''):<15} conf={conf:<20} {'OK' if ok else 'MISMATCH'}")
            if not ok:
                all_ok = False
        if r.get("notes"):
            print(f"    notes: {r['notes']}")


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    T0 = time.time()
    print("="*60)
    print("  Merged Fundamentals Pipeline")
    print(f"  {len(TICKERS)} tickers, cutoff {CUTOFF.year}")
    print("="*60)

    # Step 1: Load cached comparison data
    print("\n--- Loading cached data ---")
    custom_rows, et_rows = load_cached()
    print(f"  Custom: {len(custom_rows)} rows   ET: {len(et_rows)} rows")

    # Step 2: Fresh SEC API pull for annual + shares
    print("\n--- SEC API: annual + shares ---")
    sec_data = {}  # ticker -> (quarterly, annuals, shares)
    for i, tk in enumerate(TICKERS, 1):
        print(f"  [{i:>2}/{len(TICKERS)}] {tk}...", end=" ", flush=True)
        q, a, sh = fetch_sec_full(tk)
        # Derive Q4
        q4_derived = derive_q4(q, a, sh, tk)
        sec_data[tk] = (q, a, sh)
        print(f"{len(q)} quarterly, {len(a)} annual, {len(sh)} share entries, {len(q4_derived)} Q4 derived")

    # Step 3: Reconcile
    print("\n--- Reconciliation ---")
    all_rows = []
    all_eps_log = []
    for tk in TICKERS:
        q, a, sh = sec_data[tk]
        rows, eps_log = reconcile_ticker(tk, q, a, sh, custom_rows, et_rows)
        all_rows.extend(rows)
        all_eps_log.extend(eps_log)
        print(f"  {tk}: {len(rows)} quarters")

    # Step 4: Sanity checks (Rule 5)
    print("\n--- Sanity checks ---")
    rejected = sanity_check(all_rows)
    if rejected:
        for r in rejected:
            print(f"  {r}")
    else:
        print("  No rejections")

    # Step 4b: Duplicate NI scan (fp-keying bug regression check)
    print("\n--- Duplicate NI scan (3+ consecutive identical values) ---")
    dup_flags = duplicate_ni_scan(all_rows)
    if dup_flags:
        for f in dup_flags:
            print(f"  FLAGGED: {f}")
        print(f"  {len(dup_flags)} tickers flagged — FAIL")
    else:
        print("  Zero flagged — PASS")

    # Step 5: Write Excel
    write_excel(all_rows, all_eps_log, rejected, OUTPUT)

    # Step 6: Verify
    verify_and_report(all_rows)

    # Step 7: AES/ADM restatement verification
    verify_restatements(all_rows, sec_data)

    print(f"\nTotal elapsed: {time.time()-T0:.0f}s")
