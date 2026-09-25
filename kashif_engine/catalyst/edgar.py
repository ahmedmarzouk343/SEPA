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


def fetch_text(cik: str, accession: str, primary_doc: str, max_chars=12000) -> str:
    """Plain text of the 8-K body plus its EX-99.1 press release if present (cached)."""
    p = CACHE / "docs" / f"{accession}.txt"
    if p.exists():
        return p.read_text(encoding="utf-8")
    p.parent.mkdir(parents=True, exist_ok=True)
    from bs4 import BeautifulSoup
    texts = []
    urls = [doc_url(cik, accession, primary_doc)]
    idx = filing_index(cik, accession)
    if idx:
        for it in idx.get("directory", {}).get("item", []):
            n = it.get("name", "").lower()
            if ("ex99" in n or "ex-99" in n or "exhibit99" in n) and n.endswith((".htm", ".html", ".txt")):
                urls.append(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                            f"{accession.replace('-', '')}/{it['name']}")
    for u in urls[:3]:
        for attempt in range(5):
            try:
                r = requests.get(u, headers={"User-Agent": SEC_UA}, timeout=30)
                time.sleep(DELAY)
                if r.status_code == 200:
                    txt = BeautifulSoup(r.content, "html.parser").get_text(" ", strip=True)
                    texts.append(txt)
                    break
                if r.status_code in (403, 429, 503):
                    time.sleep(2 ** attempt * 3)
                    continue
                break
            except requests.exceptions.RequestException:
                time.sleep(2 ** attempt)
    text = "\n\n".join(texts)
    text = " ".join(text.split())[:max_chars]
    p.write_text(text, encoding="utf-8")
    return text
