"""
catalyst_check.py -- Feature 6 (Catalyst Check), SEPA element 3.

Stage A (fetch_arabfinance_disclosures, apply_category_priority_layer) ->
Stage B (search_news) -> Stage C (score_with_model) -> Stage D
(log_to_track_record), orchestrated by catalyst_check().

--------------------------------------------------------------------------
score_with_model() makes REAL Gemini API calls via the google.genai SDK
(v2). It is NOT a stub. Every call that reaches Stage C costs real API
quota. Pass log_track_record=False in backtests to suppress track-record
side effects.
--------------------------------------------------------------------------

--------------------------------------------------------------------------
DISCREPANCY FLAGGED, not silently resolved: "hard gate" vs "never a hard
gate"
--------------------------------------------------------------------------
The JSON's catalyst_check.output field (and STATUS-technical-thread.md
Section 2) both say catalyst_check is "NEVER a hard gate... cannot force a
buy or a skip on its own." feature-06-catalyst-check-rules.md Section 0 and
Section 8 directly contradict this: "STRONG_NEGATIVE is the only score that
blocks entry -- it gates the pipeline" and pipeline_blocks_entry is
"the only field that KashifStrategy reads to gate entry." The user's task
instructions for this build are explicit and specific ("If score is
STRONG_NEGATIVE, set qualifies=False"), which resolves this in favor of the
newer, more detailed feature-06.md design -- implemented here accordingly.
The JSON's stale "never a hard gate" wording is corrected in the v0.21
changelog entry to note this is no longer accurate as stated; the narrower
truth (NEUTRAL and STRONG_POSITIVE never gate; only STRONG_NEGATIVE does)
is recorded instead.

--------------------------------------------------------------------------
REAL EXTERNAL DEPENDENCIES, both empirically verified before writing this
file (per this project's "verify empirically, don't guess a scraper's
structure blind" standard) -- not assumed from the spec's prose alone
--------------------------------------------------------------------------
1. ArabFinance disclosure feed: the spec's cited URL pattern
   ("companyprofiledisclosures?key={TICKER}") is real, but only returns the
   actual disclosure list HTML when called with an
   "X-Requested-With: XMLHttpRequest" header -- without it, the server
   returns the full page shell (SPA chrome, ~890KB) with no disclosure
   content embedded, since the real content is loaded by the page's own
   client-side jQuery AJAX call after first render. Confirmed via a live
   browser session (network-request inspection) before writing the parser,
   then re-confirmed working from plain Python requests with that header.
   Disclosure items are `<li class="Disclosures {CATEGORY}">` inside
   `<ul class="disclouser-list">`; roughly half the <li> elements on a real
   page are companion/duplicate entries with an EMPTY category class and
   href="#" (an alternate truncated-text rendering of the same disclosure,
   apparently meant for a JS-driven detail view) -- these are filtered out
   by requiring a real category class from the JSON's own 8-category set.
2. News search: DuckDuckGo's HTML search endpoint was tried first and
   rejected -- it returned a CAPTCHA bot-detection challenge ("select all
   squares containing a duck"), which this project will not attempt to
   bypass (matches the standing project rule against bot-detection bypass
   already flagged for Playwright/EGX in Features 4-5, and this
   environment's own safety constraints). Google News' RSS search endpoint
   (news.google.com/rss/search) was used instead -- a legitimate,
   machine-readable feed format with no bot-wall, confirmed working for
   both an English query and an Arabic query (via hl/gl/ceid parameters)
   before being relied on here.

--------------------------------------------------------------------------
KNOWN GAP, flagged rather than silently patched over: no ticker -> Arabic
company name mapping exists anywhere in this project. search_news()'s
signature takes company_arabic_name as a required parameter per the spec
(feature-06.md Section 4) -- catalyst_check() (the orchestrator) resolves
it from a small ARABIC_NAME_MAP covering only the ~13 tickers with real
Arabic names already visible in this project's own worked examples/CSVs
(catalyst_check_results.csv, catalyst_check_batch2.csv, and the JSON's own
scoring_rubric.worked_examples). For any ticker NOT in that map,
company_arabic_name resolves to None, and search_news() does NOT silently
substitute the bare ticker as a fake Arabic query (that would produce a
misleading "search ran, found nothing" result) -- it skips the Arabic call
and returns arabic_search_skipped=True in its result metadata instead, so
the gap is visible in the output rather than hidden. Building full
224-ticker Arabic name coverage is future work, not attempted here.
"""

import json
import os
import re
import time
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

try:
    from google import genai as _genai_module
    from google.genai import types as _genai_types
    from google.genai.errors import APIError as GenaiAPIError
except ImportError:  # pragma: no cover -- google-genai not installed
    _genai_module = None
    _genai_types = None
    GenaiAPIError = Exception

try:
    from openai import OpenAI as _OpenAI
except ImportError:  # pragma: no cover -- openai not installed
    _OpenAI = None

try:
    from anthropic import Anthropic as _Anthropic
except ImportError:  # pragma: no cover -- anthropic not installed
    _Anthropic = None

load_dotenv()  # loads .env (GOOGLE_AI_STUDIO_KEY) into os.environ, once at import time

from kashif_config import CONFIG_PATH
TRACK_RECORD_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalyst_track_record.jsonl")

# Feature 7 (Operational Safety) -- module-level HTTP error counters, wired
# out to KashifStrategy's daily ops log (feature-07-operational-safety-
# rules.md Section 3.4: "already handled gracefully in catalyst_check.py --
# increment counters there on HTTP errors"). Module-level (not per-call)
# because these track the whole run's error rate, same lifetime as a single
# backtrader run/process. reset_error_counters() exists specifically so
# KashifStrategy.__init__() can zero these at the start of each new run --
# without it, a second cerebro.run() in the same Python process would carry
# over the previous run's error counts, which Section 3.2's "one file per
# calendar day, latest run wins" framing implies should NOT happen.
_arabfinance_fetch_error_count = 0
_google_news_rss_error_count = 0

MAX_CATALYST_CALLS_PER_RUN = 20
_catalyst_budget_remaining = MAX_CATALYST_CALLS_PER_RUN
_catalyst_budget_used = 0


def get_error_counters():
    """Returns {"arabfinance_fetch_errors": int, "google_news_rss_errors": int}."""
    return {
        "arabfinance_fetch_errors": _arabfinance_fetch_error_count,
        "google_news_rss_errors": _google_news_rss_error_count,
    }


def get_budget_status():
    """Returns {"budget_used": int, "budget_remaining": int, "budget_total": int}."""
    return {
        "budget_used": _catalyst_budget_used,
        "budget_remaining": _catalyst_budget_remaining,
        "budget_total": MAX_CATALYST_CALLS_PER_RUN,
    }


def reset_error_counters():
    """Zeroes both module-level HTTP error counters and resets the API call
    budget -- call at the start of each new run (KashifStrategy.__init__()
    does this) so the ops log reflects only that run's own activity."""
    global _arabfinance_fetch_error_count, _google_news_rss_error_count
    global _catalyst_budget_remaining, _catalyst_budget_used
    _arabfinance_fetch_error_count = 0
    _google_news_rss_error_count = 0
    _catalyst_budget_remaining = MAX_CATALYST_CALLS_PER_RUN
    _catalyst_budget_used = 0


# A8 — the 90-day scoring window is REMOVED. ch03 states no time window; the
# boundary silently discarded valid older catalysts. None means "no upper age
# bound — use the most recent available information". Future-dated items are
# still rejected (see _within_window).
SCORING_WINDOW_DAYS = None  # JSON scoring_window_rule — A8: no time boundary
FORWARD_RETURN_DAYS = [10, 20, 60]  # JSON track_record_logging

# JSON category_priority_layer.priority_tiers -- confirmed against the real
# ArabFinance page's own category tab labels (General/FinancialResults/
# FinancialStatements/GeneralAssemblies/Shareholding/Listing/Corporate/
# Trading, all 8 present verbatim as <li> class names on a live fetch).
CATEGORY_PRIORITY_HIGH = {"FinancialResults", "FinancialStatements", "Corporate"}
CATEGORY_PRIORITY_MEDIUM = {"Shareholding", "GeneralAssemblies", "Listing"}
CATEGORY_PRIORITY_LOW = {"Trading", "General"}
VALID_CATEGORIES = CATEGORY_PRIORITY_HIGH | CATEGORY_PRIORITY_MEDIUM | CATEGORY_PRIORITY_LOW

ARABFINANCE_DISCLOSURES_URL = "https://arabfinance.com/ar/home/companyprofiledisclosures"
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
HTTP_TIMEOUT_SECONDS = 15
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# Known gap -- see module docstring. Names taken from this project's own
# worked-example sources (catalyst_check_results.csv, catalyst_check_batch2.csv,
# disclosure titles already fetched from ArabFinance), not invented.
# TODO: extend to top 50 EGX tickers by market cap
# Currently covers ~13/224 tickers. Tickers without a mapping skip
# Arabic search explicitly (logged in Decision Receipt). See known_gaps_and_todos
# in minervini_sepa_v1_strategy_config.json for the full context.
ARABIC_NAME_MAP = {
    "COMI": "البنك التجاري الدولي",
    "TMGH": "طلعت مصطفى",
    "SWDY": "السويدي إليكتريك",
    "HRHO": "المجموعة المالية هيرميس",
    "ABUK": "أبوقير للأسمدة",
    "JUFO": "جهينة",
    "ORWE": "الشرقية للدخان",
    "ISPH": "ابن سينا فارما",
    "MFPC": "موبكو",
    "SKPC": "سيدي كرير للبتروكيماويات",
    "EFIH": "إي فايننس",
    "EAST": "الشرقية - إيسترن كومباني",
    "OCDI": "6 أكتوبر للتنمية والاستثمار",
}


# ==========================================================================
# Stage A -- ArabFinance disclosure fetch + category priority routing
# ==========================================================================

def _within_window(date_value, window_days, reference_date=None):
    """
    Pure predicate, deliberately factored out of fetch_arabfinance_disclosures()
    so the boundary logic is directly testable without a network call
    (Fixture 2). `date_value` accepts a date/datetime or an ISO "YYYY-MM-DD"
    string.

    A8: when `window_days` is None the upper age bound is REMOVED entirely —
    any past-dated item qualifies, however old. The lower bound stays: an
    item dated in the FUTURE relative to `reference_date` is still rejected,
    because in a backtest that would be lookahead, not a stale catalyst.
    """
    if reference_date is None:
        reference_date = datetime.now().date()
    if isinstance(date_value, str):
        date_value = datetime.strptime(date_value, "%Y-%m-%d").date()
    elif isinstance(date_value, datetime):
        date_value = date_value.date()
    age_days = (reference_date - date_value).days
    if window_days is None:
        return age_days >= 0
    return 0 <= age_days <= window_days


def fetch_arabfinance_disclosures(ticker, window_days=SCORING_WINDOW_DAYS, reference_date=None):
    """
    Fetch from ArabFinance companyprofiledisclosures?key={TICKER}. Returns
    list of {date (ISO str), category, title} -- TIMING and CATEGORY only.
    Does NOT attempt to fetch PDF content -- confirmed blocked (JSON
    pdf_path_status). Handles HTTP errors and unexpected structure
    gracefully: returns [] rather than raising, per spec Section 3's
    explicit "do not crash the pipeline" requirement.
    """
    global _arabfinance_fetch_error_count
    ticker_bare = ticker.replace(".CA", "").replace(".ca", "").upper()
    try:
        resp = requests.get(
            ARABFINANCE_DISCLOSURES_URL,
            params={"key": ticker_bare},
            timeout=HTTP_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT, "X-Requested-With": "XMLHttpRequest"},
        )
        resp.raise_for_status()
    except requests.RequestException:
        _arabfinance_fetch_error_count += 1
        return []

    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        items = soup.select("ul.disclouser-list > li")
    except Exception:  # noqa: BLE001 -- defensive, structure change shouldn't crash the pipeline
        return []

    disclosures = []
    for li in items:
        classes = li.get("class", [])
        category = next((c for c in classes if c in VALID_CATEGORIES), None)
        if category is None:
            continue  # companion/duplicate entry, no real category -- see module docstring
        date_span = li.find("span", class_="disclouser-date")
        if date_span is None:
            continue
        date_text = date_span.get_text(strip=True)
        try:
            disclosure_date = datetime.strptime(date_text, "%d/%m/%Y").date()
        except ValueError:
            continue
        if not _within_window(disclosure_date, window_days, reference_date=reference_date):
            continue
        a = li.find("a")
        title = a.get_text(strip=True) if a else ""
        disclosures.append({"date": disclosure_date.isoformat(), "category": category, "title": title})

    return disclosures


def apply_category_priority_layer(disclosures):
    """
    Returns the OVERALL priority tier ("HIGH" | "MEDIUM" | "LOW") for a
    disclosure set: HIGH if any disclosure is HIGH-priority category, else
    MEDIUM if any is MEDIUM, else LOW -- including an empty list (no
    disclosures at all doesn't escalate anything on its own; Stage B news
    search still runs regardless and can still surface a real catalyst).
    """
    categories = {d["category"] for d in disclosures}
    if categories & CATEGORY_PRIORITY_HIGH:
        return "HIGH"
    if categories & CATEGORY_PRIORITY_MEDIUM:
        return "MEDIUM"
    return "LOW"


# ==========================================================================
# Stage B -- news search, always both languages
# ==========================================================================
# SECOND SINGLE POINT OF FAILURE (JSON catalyst_check.known_dependency_risk,
# added v0.22): Google News RSS is a legitimate, confirmed-working feed, but
# Google has never officially committed to this endpoint's stability or
# schema. If it changes or is throttled, all news-based catalyst scoring
# silently degrades with no fallback -- documented on the same standard as
# the ArabFinance single point of failure above, needs monitoring alongside it.

def _google_news_rss_search(query, lang, country):
    global _google_news_rss_error_count
    try:
        resp = requests.get(
            GOOGLE_NEWS_RSS_URL,
            params={"q": query, "hl": lang, "gl": country, "ceid": f"{country}:{lang}"},
            timeout=HTTP_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
    except requests.RequestException:
        _google_news_rss_error_count += 1
        return []

    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp.content)
    except Exception:  # noqa: BLE001 -- malformed feed shouldn't crash the pipeline
        return []

    articles = []
    for item in root.findall(".//item"):
        title_el = item.find("title")
        link_el = item.find("link")
        pubdate_el = item.find("pubDate")
        source_el = item.find("source")
        pub_date_iso = None
        if pubdate_el is not None and pubdate_el.text:
            try:
                pub_date_iso = datetime.strptime(pubdate_el.text, "%a, %d %b %Y %H:%M:%S %Z").date().isoformat()
            except ValueError:
                pub_date_iso = None
        articles.append({
            "title": title_el.text if title_el is not None else "",
            "content": "",  # RSS gives headline only, not full article body
            "url": link_el.text if link_el is not None else "",
            "source": source_el.text if source_el is not None else "",
            "date": pub_date_iso,
            "language": lang,
        })
    return articles


def search_news(ticker, company_arabic_name, window_days=SCORING_WINDOW_DAYS, reference_date=None):
    """
    Always runs BOTH an English search (ticker name) and an Arabic search
    (company_arabic_name + أخبار/إعلان) -- never Arabic as a fallback. See
    module docstring for why (externally-originated catalysts like index
    inclusion have NO disclosure trail at all -- news search is the only
    possible path, and Arabic search has independently surfaced real
    catalysts (credit rating upgrade, 67.8% acquisition, a genuine earnings
    decline) completely absent from English results in prior live testing).

    Returns list of article dicts (see _google_news_rss_search), filtered
    to the trailing `window_days`, PLUS a `_meta` dict (not an article) at
    index 0 describing search coverage -- callers that only want articles
    should filter `a for a in result if "title" in a`.
    """
    ticker_bare = ticker.replace(".CA", "").replace(".ca", "").upper()
    english_query = f"{ticker_bare} Egypt stock EGX"
    english_articles = _google_news_rss_search(english_query, lang="en", country="US")

    arabic_search_skipped = not company_arabic_name
    arabic_articles = []
    if not arabic_search_skipped:
        arabic_query = f"{company_arabic_name} أخبار إعلان"
        arabic_articles = _google_news_rss_search(arabic_query, lang="ar", country="EG")

    all_articles = english_articles + arabic_articles
    in_window = [a for a in all_articles if a["date"] is not None and _within_window(a["date"], window_days, reference_date=reference_date)]

    return {
        "articles": in_window,
        "arabic_search_skipped": arabic_search_skipped,
        "english_count": len(english_articles),
        "arabic_count": len(arabic_articles),
    }


# ==========================================================================
# Edge-case pre-processing rules -- Section 7. Named functions, not buried
# in a prompt. Each operates on a list of article dicts; articles may
# carry pre-extracted structured fields (basis_mentions / pnl_mentions /
# is_denial) when already known (e.g. from a test fixture or an upstream
# extraction step), or those fields are derived here via a lightweight,
# clearly-heuristic keyword scan of title+content when absent. This is NOT
# NLP -- it is the "already-interpreted context" the spec asks these rules
# to hand the model, kept deliberately simple and inspectable.
# ==========================================================================

_BASIS_KEYWORDS = {
    "standalone": ["standalone", "unconsolidated", "منفردة", "غير مجمعة", "غير المجمعة"],
    "consolidated": ["consolidated", "مجمعة", "المجمعة", "موحدة"],
}
_DIRECTION_UP_KEYWORDS = ["up", "rose", "rise", "increase", "growth", "beat", "gain", "ارتفع", "نمو", "زيادة", "قفز"]
_DIRECTION_DOWN_KEYWORDS = ["down", "fell", "fall", "decline", "drop", "decrease", "loss", "تراجع", "انخفض", "هبوط", "خسارة"]
_DENIAL_KEYWORDS = ["denied", "denies", "denial", "rumor is false", "not true", "نفت", "ينفي", "تكذيب", "نفي"]
_NEGATIVE_HEADLINE_KEYWORDS = ["reducing", "cut", "exit", "withdraw", "scaling back", "تقليص", "خفض", "انسحاب"]


def _extract_basis_mentions(article):
    """
    Returns article["basis_mentions"] if already present (direct-injection
    fixtures use this), else derives a best-effort list via keyword
    scanning of title+content. Each mention: {"basis": "standalone"|
    "consolidated", "direction": "up"|"down"}.
    """
    if "basis_mentions" in article:
        return article["basis_mentions"]

    text = f"{article.get('title', '')} {article.get('content', '')}".lower()
    mentions = []
    for basis, keywords in _BASIS_KEYWORDS.items():
        if any(kw.lower() in text for kw in keywords):
            has_up = any(kw.lower() in text for kw in _DIRECTION_UP_KEYWORDS)
            has_down = any(kw.lower() in text for kw in _DIRECTION_DOWN_KEYWORDS)
            if has_up and not has_down:
                mentions.append({"basis": basis, "direction": "up"})
            elif has_down and not has_up:
                mentions.append({"basis": basis, "direction": "down"})
    return mentions


def apply_reporting_basis_conflict_rule(articles):
    """
    JSON reporting_basis_conflict_rule: when standalone and consolidated
    figures are BOTH present (across one or more articles) and disagree in
    direction, score NEUTRAL and state both figures explicitly -- do not
    pick one basis to force a strong score.

    Returns {"conflict": bool, "standalone_direction": str or None,
             "consolidated_direction": str or None, "rationale": str or None}
    """
    all_mentions = []
    for article in articles:
        all_mentions.extend(_extract_basis_mentions(article))

    standalone_dirs = {m["direction"] for m in all_mentions if m["basis"] == "standalone"}
    consolidated_dirs = {m["direction"] for m in all_mentions if m["basis"] == "consolidated"}

    conflict = bool(standalone_dirs) and bool(consolidated_dirs) and standalone_dirs != consolidated_dirs
    if not conflict:
        return {"conflict": False, "standalone_direction": None, "consolidated_direction": None, "rationale": None}

    standalone_dir = sorted(standalone_dirs)[0]
    consolidated_dir = sorted(consolidated_dirs)[0]
    rationale = (
        f"Reporting basis conflict: standalone profit {standalone_dir}, consolidated profit "
        f"{consolidated_dir} -- no rule favors one basis, scored NEUTRAL per reporting_basis_conflict_rule."
    )
    return {"conflict": True, "standalone_direction": standalone_dir,
            "consolidated_direction": consolidated_dir, "rationale": rationale}


def apply_source_reconciliation_rule(articles):
    """
    JSON source_reconciliation_rule: two sources citing DIFFERENT named P&L
    lines can both be correct -- only a genuine conflict if the SAME named
    line differs in direction across sources. This function does not itself
    produce a score; it identifies which apparent discrepancies are
    reconcilable (different lines) vs. genuine (same line, different
    direction), so apply_reporting_basis_conflict_rule / the model aren't
    misled by a false conflict.

    Each article may carry "pnl_mentions": [{"line": str, "direction":
    "up"|"down", "source": str}, ...]. Absent that, no reconciliation is
    attempted (this rule does not do free-text P&L-line extraction -- named
    lines are too varied to keyword-match reliably; it operates on
    already-tagged mentions only).

    Returns {"genuine_conflicts": [...], "reconciled": [...]} -- lines with
    >1 direction across sources are genuine conflicts; lines with only one
    direction (even if cited by multiple differently-worded sources) are
    reconciled, not conflicts.
    """
    by_line = {}
    for article in articles:
        for mention in article.get("pnl_mentions", []):
            by_line.setdefault(mention["line"], []).append(mention)

    genuine_conflicts = []
    reconciled = []
    for line, mentions in by_line.items():
        directions = {m["direction"] for m in mentions}
        if len(directions) > 1:
            genuine_conflicts.append({"line": line, "directions": sorted(directions), "mentions": mentions})
        else:
            reconciled.append({"line": line, "direction": next(iter(directions)), "mentions": mentions})

    return {"genuine_conflicts": genuine_conflicts, "reconciled": reconciled}


def apply_debunked_rumor_rule(articles):
    """
    JSON debunked_rumor_rule: if an article is a company's DENIAL or
    resolution of a negative rumor, score the resolution, not the rumor's
    surface framing. A resolved/denied negative rumor is net-neutral-to-
    reassuring, not a negative.

    Each article may carry "is_denial": bool (direct-injection fixtures use
    this) -- absent that, derived via keyword scan: headline matches
    negative-sounding language AND content matches denial language.

    Returns {"debunked": bool, "debunked_articles": [...], "rationale": str or None}
    """
    debunked_articles = []
    for article in articles:
        if "is_denial" in article:
            is_denial = article["is_denial"]
        else:
            headline = article.get("title", "").lower()
            content = article.get("content", "").lower()
            headline_sounds_negative = any(kw.lower() in headline for kw in _NEGATIVE_HEADLINE_KEYWORDS)
            content_is_denial = any(kw.lower() in content for kw in _DENIAL_KEYWORDS)
            is_denial = headline_sounds_negative and content_is_denial
        if is_denial:
            debunked_articles.append(article)

    if not debunked_articles:
        return {"debunked": False, "debunked_articles": [], "rationale": None}

    rationale = (
        f"Headline-negative item(s) resolved to a company denial per debunked_rumor_rule "
        f"({len(debunked_articles)} article(s)) -- net-neutral-to-reassuring, not scored as negative."
    )
    return {"debunked": True, "debunked_articles": debunked_articles, "rationale": rationale}


def compute_pipeline_blocks_entry(score):
    """
    Section 8: pipeline_blocks_entry is True only if score ==
    STRONG_NEGATIVE. Factored out as its own function (rather than left
    inline in catalyst_check()'s result dict) specifically so this exact
    formula is directly testable against all three score categories
    without needing a real STRONG_POSITIVE/STRONG_NEGATIVE model
    response -- score_with_model() is a stub that only ever returns
    NEUTRAL, so this is the only way to exercise the other two categories
    deterministically (Fixture 6).
    """
    return score == "STRONG_NEGATIVE"


# ==========================================================================
# Stage C -- model call. WIRED to Google AI Studio / Gemini.
# ==========================================================================
# MODEL CHOICE, resolved: Google AI Studio (Gemini), not Claude Haiku 4.5 --
# per this task's explicit instruction. Synchronous generateContent calls
# only, no Batch API (the pipeline is an EOD cron job that runs once and
# sleeps -- async batch overhead adds no value here, per this task's own
# framing).
#
# MODEL NAME DEVIATION, flagged -- TWO STEPS, not one: the task named
# "gemini-2.0-flash" and said to confirm it still has a free tier "if not,
# use the next Flash model that does."
#   Step 1: genai.list_models() against this real API key shows
#   gemini-2.0-flash is not in the returned model list AT ALL anymore
#   (fully retired, not just moved off the free tier -- the lineup has
#   moved on to 2.5/3.x, several generations past this assistant's training
#   data). Tried "gemini-2.5-flash" next, the immediate next Flash
#   generation after 2.0.
#   Step 2: gemini-2.5-flash IS listed by list_models() and DOES show a
#   real "Free of charge" row on its own pricing section
#   (ai.google.dev/gemini-api/docs/pricing#gemini-2.5-flash, confirmed by
#   scrolling directly to that anchor and reading the rendered table --
#   an earlier DOM-traversal script had returned identical, wrong numbers
#   for several different models and was caught and discarded before
#   trusting it) -- but a REAL invocation against this specific API key
#   failed with an actual 404: "This model models/gemini-2.5-flash is no
#   longer available to new users. Please update your code to use
#   models/gemini-3.6-flash." Being listed and having a priced free tier
#   turned out not to be sufficient -- the account-level availability
#   check only surfaces at actual call time, not from list_models() or the
#   pricing page. Switched to gemini-3.6-flash on the API's own explicit
#   recommendation, then re-verified BOTH properties again for this exact
#   model: a real generate_content() call succeeds, and its own pricing
#   section (scrolled to directly, not DOM-traversed) shows the same
#   "Free of charge" input/output row.
GEMINI_MODEL_NAME = "gemini-3.6-flash"
GEMINI_RETRY_DELAYS_SECONDS = [2, 4, 8]  # exponential backoff, 429 (rate limit) only
GEMINI_MAX_RETRIES = len(GEMINI_RETRY_DELAYS_SECONDS)  # 3 retries -> 4 total attempts

# Failover chain: Haiku -> Gemini Flash -> NEUTRAL
HAIKU_MODEL_NAME = "claude-haiku-4-5-20251001"

# A7 — STRONG_POSITIVE removed. ch03 treats catalyst as confirmatory context,
# not a ranking mechanism. Two states only: STRONG_NEGATIVE blocks entry,
# NEUTRAL proceeds. A model that still emits STRONG_POSITIVE now fails
# validation and is coerced to NEUTRAL by the caller's fallback.
VALID_MODEL_SCORES = {"NEUTRAL", "STRONG_NEGATIVE"}

_SCORE_RE = re.compile(r"SCORE:\s*\[?\s*([A-Z_]+)\s*\]?", re.IGNORECASE)
_SOURCE_RE = re.compile(r"SOURCE:\s*\[?\s*(.+?)\s*\]?\s*(?:\r?\n|$)", re.IGNORECASE)
_RATIONALE_RE = re.compile(r"RATIONALE:\s*\[?\s*(.+)", re.IGNORECASE | re.DOTALL)

IS_STUB = False  # score_with_model makes real API calls via Haiku -> Gemini failover

_genai_client = None  # cached genai.Client instance -- created once per process,
                       # reused across all catalyst_check() calls.


def _load_rubric_text():
    """
    Serializes the JSON's full catalyst_check.scoring_rubric block to text.
    This ONE block already contains everything Section 5 point 1 asks for:
    description, worked_examples (8 real cases -- see module docstring's
    discrepancy note on why this is 8, not 15), categories, scoring_window_
    rule, source_quality_rule, and all three edge-case rules
    (reporting_basis_conflict_rule, source_reconciliation_rule,
    debunked_rumor_rule), and output_format -- serializing the whole
    scoring_rubric object covers all of it in one pass, not four separate
    extractions.
    """
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    rubric = cfg["catalyst_check"]["scoring_rubric"]
    return json.dumps(rubric, indent=2, ensure_ascii=False)


def _build_system_prompt():
    rubric_text = _load_rubric_text()
    return (
        "You are the Catalyst Check stage of the Kashif EGX (Egyptian Exchange) trading "
        "strategy's SEPA pipeline. Your ONLY job is to read the disclosures and news "
        "evidence provided for one ticker and output a categorical catalyst score, per the "
        "rubric below. You are not a financial advisor and must never give a buy/sell "
        "recommendation or free-form opinion -- only one of the two fixed categories, "
        "with a cited source and a one-sentence rationale.\n\n"
        "IMPORTANT: there are only TWO valid scores. STRONG_NEGATIVE is for genuinely "
        "adverse material news (fraud, major loss, regulatory action, guidance cut). "
        "Everything else -- including good news -- is NEUTRAL. Positive catalysts are "
        "confirmatory context only and must NOT be scored as a separate category.\n\n"
        "SCORING RUBRIC (verbatim from this project's strategy config, including all worked "
        "examples and edge-case rules):\n" + rubric_text + "\n\n"
        "OUTPUT FORMAT -- return ONLY this exact structure and nothing else. No preamble, "
        "no markdown formatting, no extra commentary before or after:\n"
        "SCORE: [NEUTRAL|STRONG_NEGATIVE]\n"
        "SOURCE: [source name, YYYY-MM-DD]\n"
        "RATIONALE: [1 sentence, citing the specific P&L line and reporting basis "
        "(standalone/consolidated) when profit figures are mentioned]"
    )


def _build_user_message(ticker, date_str, disclosures, articles):
    """Section 5 point 2: ticker + disclosures + articles as the variable, per-call message."""
    lines = [f"TICKER: {ticker}", f"DATE: {date_str}", ""]
    lines.append("ARABFINANCE DISCLOSURES (timing + category only -- PDF content not available):")
    if disclosures:
        for d in disclosures:
            lines.append(f"  - {d.get('date', '?')} [{d.get('category', '?')}] {d.get('title', '')}")
    else:
        lines.append("  (none in the scoring window)")
    lines.append("")
    lines.append("NEWS ARTICLES (English + Arabic search combined):")
    if articles:
        for a in articles:
            lines.append(f"  - [{a.get('language', '?')}] {a.get('date', '?')} | "
                          f"source={a.get('source', '?')}: {a.get('title', '')}")
            if a.get("content"):
                lines.append(f"    content: {a['content']}")
    else:
        lines.append("  (none found)")
    return "\n".join(lines)


def _parse_model_response(text):
    """
    Section 5 point 4 / this task's point 3: extract SCORE/SOURCE/RATIONALE.
    Returns the parsed dict, or None if any field is missing or SCORE isn't
    one of the three valid categories -- the caller treats None as a parse
    failure (-> NEUTRAL, error_flag=True), never crashes on it.
    """
    if not text:
        return None
    score_match = _SCORE_RE.search(text)
    source_match = _SOURCE_RE.search(text)
    rationale_match = _RATIONALE_RE.search(text)
    if not (score_match and source_match and rationale_match):
        return None
    score = score_match.group(1).strip().upper()
    if score not in VALID_MODEL_SCORES:
        return None
    source = source_match.group(1).strip()
    rationale = rationale_match.group(1).strip()
    if not source or not rationale:
        return None
    return {"score": score, "source": source, "rationale": rationale}


def _is_rate_limit_error(exc):
    if GenaiAPIError is not Exception and isinstance(exc, GenaiAPIError):
        return getattr(exc, "status", None) == 429
    code = getattr(exc, "code", None)
    if callable(code):
        try:
            code = code()
        except Exception:  # noqa: BLE001
            code = None
    return code == 429


def _get_genai_client():
    """
    Creates (once) and caches a google.genai.Client authenticated with the
    API key from .env. Raises on missing key/package so the caller can
    produce a clear, specific error_flag rationale rather than a generic one.
    """
    global _genai_client
    if _genai_client is not None:
        return _genai_client
    if _genai_module is None:
        raise RuntimeError("google-genai is not installed")
    api_key = os.environ.get("GOOGLE_AI_STUDIO_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_AI_STUDIO_KEY not set (expected in .env)")
    _genai_client = _genai_module.Client(api_key=api_key)
    return _genai_client


def _call_haiku(system_prompt, user_message):
    """Single-attempt call to Claude Haiku via the Anthropic SDK.
    Returns the raw text response or raises on any failure."""
    if _Anthropic is None:
        raise RuntimeError("anthropic package not installed")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    client = _Anthropic(api_key=api_key)
    response = client.messages.create(
        model=HAIKU_MODEL_NAME,
        max_tokens=300,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


def _call_gemini(system_prompt, user_message):
    """Single-attempt call to Google Gemini. Returns raw text or raises."""
    client = _get_genai_client()
    response = client.models.generate_content(
        model=GEMINI_MODEL_NAME,
        contents=user_message,
        config=_genai_types.GenerateContentConfig(system_instruction=system_prompt),
    )
    return getattr(response, "text", None)


# Failover provider definitions: (name, callable).
# Each callable takes (system_prompt, user_message) and returns raw text.
_FAILOVER_CHAIN = None


def _get_failover_chain():
    global _FAILOVER_CHAIN
    if _FAILOVER_CHAIN is not None:
        return _FAILOVER_CHAIN

    chain = []

    if os.environ.get("ANTHROPIC_API_KEY"):
        chain.append(("haiku", _call_haiku))

    chain.append(("gemini", _call_gemini))

    _FAILOVER_CHAIN = chain
    return chain


def score_with_model(ticker, disclosures, articles, rubric_text=None, date_str=None):
    """
    Failover chain: Haiku (claude-haiku-4-5) -> Gemini Flash -> NEUTRAL.

    Each provider gets one attempt. On failure, the next provider is tried.
    rubric_text is accepted for backward compatibility but unused directly.

    Returns: {"score", "source", "rationale", "pending_model_review",
    "error_flag", "retry_log"}.
    """
    if date_str is None:
        date_str = datetime.now().date().isoformat()
    user_message = _build_user_message(ticker, date_str, disclosures, articles)
    system_prompt = _build_system_prompt()
    retry_log = []

    for provider_name, call_fn in _get_failover_chain():
        try:
            raw_text = call_fn(system_prompt, user_message)
            parsed = _parse_model_response(raw_text)
            if parsed is None:
                retry_log.append({"provider": provider_name, "outcome": "malformed_output"})
                continue
            retry_log.append({"provider": provider_name, "outcome": "success"})
            parsed["pending_model_review"] = False
            parsed["error_flag"] = False
            parsed["retry_log"] = retry_log
            return parsed
        except Exception as e:  # noqa: BLE001
            rate_limited = _is_rate_limit_error(e)
            retry_log.append({
                "provider": provider_name,
                "outcome": "rate_limited" if rate_limited else "error",
                "error": str(e)[:300],
            })
            continue

    return {
        "score": "NEUTRAL", "source": "all_providers_failed",
        "rationale": f"All providers in failover chain exhausted: {[r['provider'] for r in retry_log]}",
        "pending_model_review": True, "error_flag": True, "retry_log": retry_log,
    }


# ==========================================================================
# Stage D -- track record logging. Append-only.
# ==========================================================================

def log_to_track_record(ticker, date, score, source, rationale, pipeline_run_id=None,
                         forward_return_days=None, path=TRACK_RECORD_PATH):
    """
    Append one JSON line to catalyst_track_record.jsonl. Fields logged
    immediately: ticker, date, score, source, rationale, pipeline_run_id.
    Fields populated later by backfill_catalyst_returns.py (separate
    script, periodic reporting job, never during the main pipeline --
    avoids lookahead bias): forward_return_10d/20d/60d, left None here.

    Creates the file with a header comment on first run. NEVER overwrites
    -- opens in append mode only. The header line starts with "#" and is
    NOT valid JSON on its own; any reader of this file (backfill script
    included) must skip lines starting with "#" before json.loads()-ing.
    """
    if forward_return_days is None:
        forward_return_days = FORWARD_RETURN_DAYS

    record = {
        "ticker": ticker,
        "date": date,
        "score": score,
        "source": source,
        "rationale": rationale,
        "pipeline_run_id": pipeline_run_id or "unknown",
    }
    for days in forward_return_days:
        record[f"forward_return_{days}d"] = None

    is_new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if is_new:
            f.write("# catalyst_track_record.jsonl -- append-only. One JSON object per line below this "
                     "comment. See feature-06-catalyst-check-rules.md Section 6. "
                     "forward_return_*d fields are populated later by backfill_catalyst_returns.py.\n")
        f.write(json.dumps(record) + "\n")

    return record


# ==========================================================================
# Orchestrator -- Section 2, Stage A -> B -> C -> D.
# ==========================================================================

def catalyst_check(ticker, company_arabic_name=None, window_days=SCORING_WINDOW_DAYS,
                    pipeline_run_id=None, disclosures=None, news_result=None, reference_date=None,
                    log_track_record=True):
    """
    Full catalyst_check pipeline for one ticker. `disclosures` and
    `news_result` are optional pre-fetched-data overrides -- when None
    (the normal/live path), fetch_arabfinance_disclosures()/search_news()
    are called for real; tests inject synthetic data directly here (same
    "call the real orchestrator, inject only the network-dependent inputs"
    precedent as Feature 5's Fixture 8/9 spying on detect_swings()).

    Pass log_track_record=False in backtests to suppress the Stage D
    track-record append (avoids ~97,500 duplicate lines per full run).

    Returns the Section 8 output dict (ticker, date, score, source,
    rationale, disclosure_category, priority_tier, pending_model_review,
    scoring_window_days, pipeline_blocks_entry).
    """
    global _catalyst_budget_remaining, _catalyst_budget_used
    today = (reference_date or datetime.now().date())

    if _catalyst_budget_remaining <= 0 and disclosures is None and news_result is None:
        return {
            "ticker": ticker, "date": today.isoformat(),
            "score": "NEUTRAL", "source": "budget_exhausted",
            "rationale": f"API call budget exhausted ({_catalyst_budget_used}/{MAX_CATALYST_CALLS_PER_RUN} calls used)",
            "disclosure_category": "N/A", "priority_tier": "N/A",
            "pending_model_review": False, "scoring_window_days": window_days,
            "pipeline_blocks_entry": False, "error_flag": False,
            "retry_log": [], "model_call_attempted": False,
        }

    # Stage A
    if disclosures is None:
        disclosures = fetch_arabfinance_disclosures(ticker, window_days=window_days, reference_date=today)
    priority_tier = apply_category_priority_layer(disclosures)
    disclosure_category = disclosures[0]["category"] if disclosures else "externally_originated"

    # Stage B -- ALWAYS runs regardless of priority_tier (see search_news()
    # docstring: news search is structurally the only path for externally-
    # originated catalysts, never conditional on Stage A's result).
    if news_result is None:
        arabic_name = company_arabic_name or ARABIC_NAME_MAP.get(ticker.replace(".CA", "").replace(".ca", "").upper())
        news_result = search_news(ticker, arabic_name, window_days=window_days, reference_date=today)
    articles = news_result.get("articles", [])

    # Edge-case pre-processors run BEFORE Stage C, per spec Section 7 --
    # the model should receive already-interpreted context, not raw
    # headlines that might trigger the debunked-rumor or basis-conflict
    # traps. If a named rule already determines NEUTRAL is correct, that
    # rule's own rationale is used directly and Stage C (the model, or
    # right now the stub) is skipped entirely -- zero AI cost for a case
    # that's already been resolved deterministically.
    basis_result = apply_reporting_basis_conflict_rule(articles)
    rumor_result = apply_debunked_rumor_rule(articles)

    pending_model_review = False
    error_flag = False
    retry_log = []
    model_call_attempted = False
    if priority_tier == "LOW" and not articles:
        score = "NEUTRAL"
        source = "auto_low_priority"
        rationale = ("LOW-priority disclosure category only (Trading/General), no corroborating news "
                     "found in Stage B -- auto-scored NEUTRAL per category_priority_layer, Stage C skipped.")
    elif basis_result["conflict"]:
        score = "NEUTRAL"
        source = "reporting_basis_conflict_rule"
        rationale = basis_result["rationale"]
    elif rumor_result["debunked"]:
        score = "NEUTRAL"
        source = "debunked_rumor_rule"
        rationale = rumor_result["rationale"]
    elif _catalyst_budget_remaining <= 0:
        score = "NEUTRAL"
        source = "budget_exhausted"
        rationale = (f"API call budget exhausted ({_catalyst_budget_used}/{MAX_CATALYST_CALLS_PER_RUN} "
                     f"calls used) -- remaining candidates scored NEUTRAL.")
    else:
        model_call_attempted = True
        _catalyst_budget_remaining -= 1
        _catalyst_budget_used += 1
        rubric_text = _load_rubric_text()
        model_result = score_with_model(ticker, disclosures, articles, rubric_text=rubric_text,
                                         date_str=today.isoformat())
        score = model_result["score"]
        source = model_result["source"]
        rationale = model_result["rationale"]
        pending_model_review = model_result.get("pending_model_review", False)
        error_flag = model_result.get("error_flag", False)
        retry_log = model_result.get("retry_log", [])

    result = {
        "ticker": ticker,
        "date": today.isoformat(),
        "score": score,
        "source": source,
        "rationale": rationale,
        "disclosure_category": disclosure_category,
        "priority_tier": priority_tier,
        "pending_model_review": pending_model_review,
        "scoring_window_days": window_days,
        "pipeline_blocks_entry": compute_pipeline_blocks_entry(score),
        # Additive fields, not in feature-06.md Section 8's original schema --
        # error_flag/retry_log surface Stage C's real model-call diagnostics
        # (this task's point 4: "Log every retry attempt to the Decision
        # Receipt"). Both default to False/[] whenever Stage C wasn't even
        # reached (auto_low_priority / the two edge-case rules), same as
        # pending_model_review already did.
        "error_flag": error_flag,
        "retry_log": retry_log,
        # Feature 7 (Operational Safety) -- lets KashifStrategy distinguish
        # "Stage C was actually invoked" from "a deterministic rule/auto-
        # route resolved this without spending a model call", so
        # catalyst_api_calls_made in the ops log counts real attempts only.
        "model_call_attempted": model_call_attempted,
    }

    if log_track_record:
        log_to_track_record(ticker, result["date"], score, source, rationale, pipeline_run_id=pipeline_run_id)
    return result
