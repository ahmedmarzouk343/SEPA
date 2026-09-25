"""Class-level EPS from each filing's own XBRL instance.

Dual-class and Up-C filers (MC, PJT, COKE, GEF, ...) tag EPS, diluted shares and
NI-to-common only per share class (StatementClassOfStockAxis). SEC companyfacts
drops dimensional facts, so the pipeline sees no EPS for them. This script reads
the instance document of every 10-Q/10-K, keeps only the filing's own current
period (as-filed, never comparatives), picks the class that trades under the
ticker, and derives Q4 per class the same way the pipeline does (Q4 NI / Q4
shares). Output: class_eps_supplement.json, used only where EPS is missing.

    python class_eps.py TICKER [TICKER ...]     # or no args: tickers with missing EPS
"""
import json, sys, time, xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from merged_pipeline import cik_for, SEC_UA

HERE = Path(__file__).parent
CACHE = HERE / "xbrl_instance_cache"
OUT = HERE / "class_eps_supplement.json"
H = {"User-Agent": SEC_UA}
START = "2019-07-01"
NS = {"xbrli": "http://www.xbrl.org/2003/instance", "xbrldi": "http://xbrl.org/2006/xbrldi"}
AXIS = "us-gaap:StatementClassOfStockAxis"
EPS_TAGS = ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"]
SH_TAGS = ["WeightedAverageNumberOfDilutedSharesOutstanding",
           "WeightedAverageNumberOfShareOutstandingBasicAndDiluted"]
NI_TAGS = ["NetIncomeLossAvailableToCommonStockholdersDiluted",
           "NetIncomeLossAvailableToCommonStockholdersBasic", "NetIncomeLoss"]
# The class that trades under each ticker, where a filer reports several.
# Everything else defaults to the only class present, or Class A.
TRADED_CLASS = {"COKE": "coke:CommonClassUndefinedMember",  # "Common Stock" (Class B is unlisted)
                "CWEN": "us-gaap:CommonClassCMember",
                "JEF": "jef:VotingCommonStockMember",   # listed shares; non-voting is unlisted
                "ADT": "us-gaap:CommonStockMember"}     # listed; Class B is unlisted


def _get(url):
    # SEC answers bursts with 429/503 or drops large downloads mid-stream;
    # back off and retry both.
    for attempt in range(6):
        try:
            r = requests.get(url, headers=H, timeout=60)
            _ = r.content
        except requests.exceptions.RequestException:
            if attempt == 5:
                raise
            time.sleep(2 ** attempt)
            continue
        time.sleep(0.12)
        if r.status_code not in (429, 500, 502, 503, 504):
            break
        time.sleep(2 ** attempt)
    r.raise_for_status()
    return r


def filings(cik):
    r = _get(f"https://data.sec.gov/submissions/CIK{cik}.json").json()["filings"]["recent"]
    return [(r["form"][i], r["accessionNumber"][i], r["reportDate"][i], r["filingDate"][i])
            for i in range(len(r["form"]))
            if r["form"][i] in ("10-Q", "10-K") and (r["reportDate"][i] or "") >= START]


def parse_filing(cik, acc, report_date):
    """Class-dimensioned facts for the filing's own current periods."""
    cf = CACHE / f"{acc}.json"
    if cf.exists():
        return json.loads(cf.read_text())
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}"
    names = [x["name"] for x in _get(f"{base}/index.json").json()["directory"]["item"]]
    inst = [n for n in names if n.endswith("_htm.xml")] or \
           [n for n in names if n.endswith(".xml") and n != "FilingSummary.xml"
            and not n.endswith(("_cal.xml", "_def.xml", "_lab.xml", "_pre.xml"))]
    out = []
    if inst:
        root = ET.fromstring(_get(f"{base}/{inst[0]}").content)
        ctx = {}
        for c in root.findall("xbrli:context", NS):
            p = c.find("xbrli:period", NS)
            s, e = p.find("xbrli:startDate", NS), p.find("xbrli:endDate", NS)
            dims = [(m.get("dimension"), m.text) for m in c.findall(".//xbrldi:explicitMember", NS)]
            if s is not None and e is not None and len(dims) == 1 and dims[0][0] == AXIS:
                ctx[c.get("id")] = (s.text, e.text, dims[0][1])
        seen = set()
        for el in root:
            tag = el.tag.split("}")[1]
            if tag not in EPS_TAGS + SH_TAGS + NI_TAGS or el.get("contextRef") not in ctx:
                continue
            s, e, member = ctx[el.get("contextRef")]
            if e != report_date or not el.text:
                continue  # comparatives are not as-filed for that period
            key = (tag, s, e, member)
            if key in seen:
                continue
            seen.add(key)
            out.append({"tag": tag, "start": s, "end": e, "member": member, "val": float(el.text)})
    CACHE.mkdir(exist_ok=True)
    cf.write_text(json.dumps(out))
    return out


def _days(s, e):
    return (datetime.strptime(e, "%Y-%m-%d") - datetime.strptime(s, "%Y-%m-%d")).days


def _first(facts, tags, member, kind, with_tag=False):
    for t in tags:
        for f in facts:
            if f["tag"] == t and f["member"] == member and _kind(f) == kind:
                return (f["val"], t) if with_tag else f["val"]
    return (None, None) if with_tag else None


def _kind(f):
    d = _days(f["start"], f["end"])
    return "Q" if 60 <= d <= 120 else ("FY" if d >= 300 else None)


def ticker_supplement(tk):
    cik = cik_for(tk)
    per_filing = []
    for form, acc, rep, filed in filings(cik):
        facts = parse_filing(cik, acc, rep)
        if facts:
            per_filing.append((form, acc, rep, filed, facts))
    per_filing.sort(key=lambda f: (f[2], f[0] == "10-K"))  # a year's 10-Qs before its 10-K
    members = {f["member"] for *_, facts in per_filing for f in facts if f["tag"] in EPS_TAGS}
    if not members:
        return {}, "no class-level EPS in any filing"
    member = TRADED_CLASS.get(tk) or (next(iter(members)) if len(members) == 1 else
                                      "us-gaap:CommonClassAMember" if "us-gaap:CommonClassAMember" in members
                                      else None)
    if member not in members:
        return {}, f"ambiguous classes {sorted(members)}"

    rows = {}
    quarters = []  # (end, ni, sh) for Q4 derivation
    for form, acc, rep, filed, facts in per_filing:
        q_eps = _first(facts, EPS_TAGS, member, "Q")
        q_sh = _first(facts, SH_TAGS, member, "Q")
        q_ni, q_ni_tag = _first(facts, NI_TAGS, member, "Q", with_tag=True)
        if form == "10-Q" and q_eps is not None:
            rows[rep] = {"eps": q_eps, "source": f"{form} {acc}", "filed": filed, "class": member}
            quarters.append((rep, q_ni, q_sh, q_ni_tag))
        if form == "10-K":
            if q_eps is not None:  # 10-K reports Q4 directly
                rows[rep] = {"eps": q_eps, "source": f"{form} {acc} (Q4 as filed)",
                             "filed": filed, "class": member}
                continue
            fy_ni, fy_ni_tag = _first(facts, NI_TAGS, member, "FY", with_tag=True)
            fy_sh = _first(facts, SH_TAGS, member, "FY")
            prior = [q for q in quarters if 0 < _days(q[0], rep) < 300]
            if fy_ni is None or fy_sh is None or len(prior) != 3 \
                    or any(q[1] is None or q[2] is None for q in prior):
                continue
            # Up-C filers switch dilution method by period (RYAN: if-converted
            # in Q2-Q3 on ~271M shares, anti-dilutive for the year on 133M),
            # so FY - Q1..Q3 is only valid when all four sit on one basis.
            if {q[3] for q in prior} != {fy_ni_tag} \
                    or any(not 0.8 <= q[2] / fy_sh <= 1.25 for q in prior):
                continue
            q4_ni = fy_ni - sum(q[1] for q in prior)
            q4_sh = 4 * fy_sh - sum(q[2] for q in prior)
            if not (0 < q4_sh < 2 * fy_sh):
                continue
            rows[rep] = {"eps": round(q4_ni / q4_sh, 2),
                         "source": f"{form} {acc} (Q4 = class NI / class shares)",
                         "filed": filed, "class": member}
    return rows, f"class {member}"


def main():
    tickers = sys.argv[1:]
    if not tickers:
        import pandas as pd
        df = pd.read_csv(HERE / "scaled_fundamentals.csv")
        tickers = sorted(df[df.eps.isna() & df.net_income.notna()].ticker.unique())
    sup = json.loads(OUT.read_text()) if OUT.exists() else {}
    for tk in tickers:
        try:
            rows, how = ticker_supplement(tk)
        except Exception as ex:  # one bad filing must not stop the batch
            rows, how = {}, f"error: {str(ex)[:80]}"
        sup[tk] = {"how": how, "rows": rows}
        print(f"{tk:<6} {len(rows):>3} periods  {how}", flush=True)
        OUT.write_text(json.dumps(sup, indent=1))


if __name__ == "__main__":
    main()
