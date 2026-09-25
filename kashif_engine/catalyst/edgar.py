"""SEC EDGAR 8-K events for the catalyst tracker (legitimate, official API).

Source: https://data.sec.gov/submissions/CIK##########.json (+ the older
"files" pages it links). Every 8-K / 8-K/A carries its item codes and an
acceptanceDateTime -- the timestamp the filing became public.

Knowledge timing: an 8-K accepted before 16:00 America/New_York on day D is
usable at the close of D; later than that, from D+1's close. Nothing earlier.

Fair access: <= 10 requests/second with a descriptive User-Agent (the same
one the fundamentals pipeline uses); no scraping of anything else.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "kashif_data" / "edgar"
sys.path.insert(0, str(ROOT / "us_fundamentals"))
SEC_UA = "KashifBacktest/1.0 (ahmed.marzouk@sprints.ai)"   # same UA as merged_pipeline.SEC_UA
DELAY = 0.12

# Code-only priority layer: which 8-K items deserve a model read at all.
ITEM_TIER = {
    "1.01": "high", "1.02": "high", "1.03": "high", "1.05": "high", "2.01": "high", "2.02": "high",
    "2.05": "high", "2.06": "high", "3.01": "high", "4.01": "high", "4.02": "high", "5.01": "high",
    "5.02": "high",
    "2.03": "medium", "2.04": "medium", "3.02": "medium", "3.03": "medium", "5.03": "medium",
    "7.01": "medium", "8.01": "medium",
    "5.04": "low", "5.05": "low", "5.06": "low", "5.07": "low", "5.08": "low", "6.01": "low",
    "9.01": "low",
}
# Items whose direction is unambiguous from the code alone (rubric v0.3:
# bankruptcy, restatement / auditor concerns, listing-standard failure).
CODE_ONLY_SCORE = {"1.03": "STRONG_NEGATIVE", "4.02": "STRONG_NEGATIVE", "3.01": "STRONG_NEGATIVE"}
TIER_ORDER = {"high": 0, "medium": 1, "low": 2, "none": 3}


def _get(url):
    for attempt in range(6):
        try:
            r = requests.get(url, headers={"User-Agent": SEC_UA}, timeout=30)
        except requests.exceptions.RequestException:
            time.sleep(2 ** attempt)
            continue
        time.sleep(DELAY)
        if r.status_code in (403, 429, 500, 502, 503, 504):
            time.sleep(2 ** attempt * 3)
            continue
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"SEC request failed repeatedly: {url}")


def cik_map():
    p = CACHE / "company_tickers.json"
    if not p.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(_get("https://www.sec.gov/files/company_tickers.json")))
    d = json.loads(p.read_text())
    return {v["ticker"].upper().replace(".", "-"): str(v["cik_str"]).zfill(10) for v in d.values()}


def submissions(cik: str) -> list[dict]:
    """All filings (recent + older pages) for a CIK, cached."""
    out_p = CACHE / "submissions" / f"{cik}.json"
    if out_p.exists():
        return json.loads(out_p.read_text())
    out_p.parent.mkdir(parents=True, exist_ok=True)
    main = _get(f"https://data.sec.gov/submissions/CIK{cik}.json")
    if main is None:
        out_p.write_text("[]")
        return []
    pages = [main["filings"]["recent"]]
    for f in main["filings"].get("files", []):
        if f.get("filingTo", "9999") >= "2019-06-01":
            pg = _get(f"https://data.sec.gov/submissions/{f['name']}")
            if pg:
                pages.append(pg)
    rows = []
    for pg in pages:
        n = len(pg.get("accessionNumber", []))
        for i in range(n):
            form = pg["form"][i]
            if form not in ("8-K", "8-K/A"):
                continue
            rows.append({"accession": pg["accessionNumber"][i], "form": form,
                         "filing_date": pg["filingDate"][i],
                         "accepted": pg["acceptanceDateTime"][i],
                         "items": pg.get("items", [""] * n)[i],
                         "primary_doc": pg["primaryDocument"][i]})
    out_p.write_text(json.dumps(rows))
    return rows


def usable_from(accepted_iso: str) -> pd.Timestamp:
    """Date at whose close the filing is known (16:00 New York cutoff)."""
    t = pd.Timestamp(accepted_iso)
    t = t.tz_localize("UTC") if t.tzinfo is None else t
    ny = t.tz_convert("America/New_York")
    d = ny.normalize().tz_localize(None)
    return d if (ny.hour, ny.minute) < (16, 0) else d + pd.Timedelta(days=1)


def events(tickers, since="2020-06-01", log=print) -> pd.DataFrame:
    cm = cik_map()
    rows, missing = [], []
    for i, t in enumerate(tickers):
        cik = cm.get(t.upper().replace(".", "-"))
        if not cik:
            missing.append(t)
            continue
        for r in submissions(cik):
            if r["filing_date"] < since:
                continue
            items = [x.strip() for x in (r["items"] or "").split(",") if x.strip()]
            tier = min((ITEM_TIER.get(x, "low") for x in items), key=TIER_ORDER.get, default="none")
            code = next((CODE_ONLY_SCORE[x] for x in items if x in CODE_ONLY_SCORE), None)
            rows.append({"ticker": t, "cik": cik, **r, "items": ",".join(items), "tier": tier,
                         "code_only_score": code})
        if (i + 1) % 100 == 0:
            log(f"  edgar: {i + 1}/{len(tickers)} tickers")
    df = pd.DataFrame(rows)
    df["usable_from"] = [usable_from(a) for a in df["accepted"]]
    if missing:
        log(f"  edgar: no CIK for {len(missing)} tickers: {missing[:20]}")
    return df


def doc_url(cik: str, accession: str, primary_doc: str) -> str:
    return (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
            f"{accession.replace('-', '')}/{primary_doc}")


def filing_index(cik: str, accession: str):
    return _get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/index.json")


EX99 = re.compile(r"(ex|exhibit|dex)[-_]?99|ex991|ex-991|pressrelease|press_release|earningsrelease", re.I)
ITEM_RE = re.compile(r"Item\s+\d\.\d\d", re.I)


MAX_DOC_BYTES = 1_500_000      # an 8-K press release is ~50-300 KB; bigger files are data dumps


def _get_html_text(url):
    from bs4 import BeautifulSoup
    for attempt in range(5):
        try:
            r = requests.get(url, headers={"User-Agent": SEC_UA}, timeout=30, stream=True)
            time.sleep(DELAY)
            if r.status_code == 200:
                raw = r.raw.read(MAX_DOC_BYTES, decode_content=True)   # cap the download, never parse a 20 MB dump
                r.close()
                return " ".join(BeautifulSoup(raw, "lxml").get_text(" ", strip=True).split())
            if r.status_code in (403, 429, 503):
                time.sleep(2 ** attempt * 3)
                continue
            return ""
        except requests.exceptions.RequestException:
            time.sleep(2 ** attempt)
    return ""


TEXT_CAP = 16_000
SUBMISSION_MAX_BYTES = 12_000_000


def _html_to_text(html: str) -> str:
    from bs4 import BeautifulSoup
    return " ".join(BeautifulSoup(html, "lxml").get_text(" ", strip=True).split())


def _submission_docs(cik: str, accession: str) -> list[tuple[str, str]]:
    """[(TYPE, html/text)] from the COMPLETE submission file <accession>.txt.

    One request per filing, and every document carries its declared <TYPE>
    (8-K, EX-99.1, ...), so nothing depends on how a filing agent names files.
    """
    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{accession}.txt"
    for attempt in range(5):
        try:
            r = requests.get(url, headers={"User-Agent": SEC_UA}, timeout=60, stream=True)
            time.sleep(DELAY)
            if r.status_code == 200:
                raw = r.raw.read(SUBMISSION_MAX_BYTES, decode_content=True).decode("utf-8", "replace")
                r.close()
                docs = []
                for chunk in raw.split("<DOCUMENT>")[1:]:
                    m = re.search(r"<TYPE>([^\n<]+)", chunk)
                    body = chunk.split("<TEXT>", 1)[1] if "<TEXT>" in chunk else chunk
                    body = body.split("</TEXT>", 1)[0]
                    docs.append(((m.group(1).strip().upper() if m else ""), body))
                return docs
            if r.status_code in (403, 429, 500, 502, 503, 504):
                time.sleep(2 ** attempt * 3)
                continue
            return []
        except Exception:                 # requests errors AND urllib3 IncompleteRead mid-stream
            time.sleep(2 ** attempt)
    return []


def _cut(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    cut = text[:n]
    return cut[:cut.rfind(" ")] + " [...]"


def fetch_text(cik: str, accession: str, primary_doc: str = "", max_chars: int = TEXT_CAP) -> str:
    """What the rater reads: the press release (EX-99.1 by declared TYPE) first,
    then the 8-K's Item sections (cover page cut), capped at a word boundary.

    v1 fed 4,000 chars of cover-page boilerplate. v2 guessed exhibit files by
    name, sometimes used the folder index as the body, and cut releases at
    5,000 chars before their prior-year tables (found by the two research
    sessions while scoring). v3 reads the complete submission instead.
    """
    p = CACHE / "docs_v3" / f"{accession}.txt"
    if p.exists():
        return p.read_text(encoding="utf-8")
    p.parent.mkdir(parents=True, exist_ok=True)
    docs = _submission_docs(cik, accession)
    body = next((t for ty, t in docs if ty in ("8-K", "8-K/A")), "")
    ex = next((t for ty, t in docs if ty == "EX-99.1"), None)
    if ex is None:
        ex = next((t for ty, t in docs if ty.startswith("EX-99")), "")
    body_txt = _html_to_text(body) if body else ""
    m = ITEM_RE.search(body_txt)
    items = body_txt[m.start():] if m else body_txt
    cut = re.search(r"Item\s+9\.01", items, re.I)
    if cut and cut.start() > 0:
        items = items[:cut.start()]
    ex_txt = _html_to_text(ex) if ex else ""
    if not docs:
        text = "[SUBMISSION UNAVAILABLE FROM SEC]"
    else:
        head = f"PRESS RELEASE / EXHIBIT 99: {_cut(ex_txt, max_chars - 1500)}\n\n" if ex_txt else \
            "PRESS RELEASE / EXHIBIT 99: [none filed with this 8-K]\n\n"
        text = head + f"8-K ITEM TEXT: {_cut(items, 1500)}"
    p.write_text(text, encoding="utf-8")
    return text


FIGURES_RE = re.compile(r"net income|net loss|per diluted share|diluted (?:eps|earnings)|earnings per share|"
                        r"\bEPS\b|operating income|adjusted ebitda", re.I)


def needs_letter(text: str) -> bool:
    """An earnings 8-K whose press-release section carries no profit figure."""
    pr = text.split("8-K ITEM TEXT:")[0]
    return not FIGURES_RE.search(pr)


def fetch_text_with_letter(cik: str, accession: str, max_chars: int = TEXT_CAP) -> str:
    """v3.1: EX-99.1 followed by EX-99.2 -- for companies that publish results in a
    shareholder letter filed as EX-99.2 (APP, FOUR). Separate cache: v3 texts
    already scored stay byte-identical."""
    p = CACHE / "docs_v31" / f"{accession}.txt"
    if p.exists():
        return p.read_text(encoding="utf-8")
    p.parent.mkdir(parents=True, exist_ok=True)
    docs = _submission_docs(cik, accession)
    ex = [t for ty, t in docs if ty in ("EX-99.1", "EX-99.2")]
    body = next((t for ty, t in docs if ty in ("8-K", "8-K/A")), "")
    body_txt = _html_to_text(body) if body else ""
    m = ITEM_RE.search(body_txt)
    items = body_txt[m.start():] if m else body_txt
    ex_txt = " ".join(_html_to_text(t) for t in ex)
    text = (f"PRESS RELEASE / EXHIBITS 99.1 + 99.2: {_cut(ex_txt, max_chars - 1500)}\n\n"
            f"8-K ITEM TEXT: {_cut(items, 1500)}") if docs else "[SUBMISSION UNAVAILABLE FROM SEC]"
    p.write_text(text, encoding="utf-8")
    return text
