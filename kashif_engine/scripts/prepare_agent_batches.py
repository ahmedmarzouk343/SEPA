"""Cut catalyst work into batch manifests for Claude subagents.

    python kashif_engine/scripts/prepare_agent_batches.py tune

Two kinds of batch, both written to kashif_data/catalyst/agent_batches/:
  8k_<window>_<i>.json    high/medium-tier 8-K filings on the shortlist; the
                          filing text is downloaded here (SEC, rate-limited)
                          so the agent only reads local files;
  news_<window>_<i>.json  one entry per shortlisted ticker with the date
                          windows (90 days before each run of candidate days)
                          in which news may be searched.
Agents write results to kashif_data/catalyst/agent_scores/<batch name>.json.
Already-scored items are skipped, so reruns only do new work.
"""
import json
import pickle
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kashif_engine.catalyst import edgar  # noqa: E402
from kashif_engine.scripts.build_catalysts import shortlist_filings  # noqa: E402

CAT = ROOT / "kashif_data" / "catalyst"
BATCH_DIR = CAT / "agent_batches"
SCORE_DIR = CAT / "agent_scores"


def done_accessions():
    s = set()
    for p in SCORE_DIR.glob("8k_*.json"):
        for r in json.loads(p.read_text()):
            s.add(r["accession"])
    return s


def windows_for(dates, pad_days=90):
    """Merge [d - 90d, d] windows of a ticker's candidate days."""
    out = []
    for d in sorted(dates):
        s, e = d - pd.Timedelta(days=pad_days), d
        if out and s <= out[-1][1] + pd.Timedelta(days=1):
            out[-1][1] = e
        else:
            out.append([s, e])
    return [[str(a.date()), str(b.date())] for a, b in out]


def main(window, per_8k=35, per_news=8):
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    SCORE_DIR.mkdir(parents=True, exist_ok=True)
    events = pd.read_parquet(ROOT / "kashif_data" / "edgar" / "events_8k.parquet")
    f, ready = shortlist_filings(ROOT / "kashif_data" / "signals" / f"bundle_{window}.pkl", events)
    todo = f[f["tier"].isin(["high", "medium"]) & f["code_only_score"].isna()]
    todo = todo[~todo["accession"].isin(done_accessions())]
    rows = []
    for i, r in enumerate(todo.itertuples(index=False)):
        edgar.fetch_text(r.cik, r.accession, r.primary_doc, max_chars=5000)
        rows.append({"accession": r.accession, "ticker": r.ticker, "filing_date": r.filing_date,
                     "items": r.items, "text_file": str(edgar.CACHE / "docs_v2" / f"{r.accession}.txt")})
        if (i + 1) % 50 == 0:
            print(f"  texts {i + 1}/{len(todo)}")
    for k in range(0, len(rows), per_8k):
        (BATCH_DIR / f"8k_{window}_{k // per_8k:02d}.json").write_text(json.dumps(rows[k:k + per_8k], indent=1))

    names = {v["ticker"].upper(): v["title"] for v in
             json.loads((edgar.CACHE / "company_tickers.json").read_text()).values()}
    news = []
    for t, g in ready.groupby("ticker"):
        if (SCORE_DIR / f"news_{window}_{t}.json").exists():
            continue
        news.append({"ticker": t, "company": names.get(t.replace("-", "."), names.get(t, t)),
                     "windows": windows_for(pd.to_datetime(g["date"]))})
    for k in range(0, len(news), per_news):
        (BATCH_DIR / f"news_{window}_{k // per_news:02d}.json").write_text(json.dumps(news[k:k + per_news], indent=1))
    print(f"{window}: {len(rows)} 8-K filings in {-(-len(rows) // per_8k)} batches; "
          f"{len(news)} tickers for news in {-(-len(news) // per_news)} batches")


if __name__ == "__main__":
    main(sys.argv[1])
