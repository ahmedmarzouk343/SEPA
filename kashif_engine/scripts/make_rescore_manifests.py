"""Rescore manifests after the v3 text fix: only accessions whose text changed
in a way that matters, assigned back to the session that scored them first.

    python kashif_engine/scripts/make_rescore_manifests.py tune
"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kashif_engine.catalyst import edgar  # noqa: E402
from kashif_engine.scripts.build_catalysts import shortlist_filings  # noqa: E402

BD = ROOT / "kashif_data" / "catalyst" / "agent_batches"
SD = ROOT / "kashif_data" / "catalyst" / "agent_scores"
# Borderline first-pass calls named by the raters themselves, re-read under the
# consistency rule (earnings positive only with an explicit YoY profit gain).
FLAGGED = {"0001562762-22-000381", "0001558370-24-001524", "0001433642-24-000061",
           "0001698990-22-000003", "0000893538-22-000016", "0001753926-23-000072"}


def main(window):
    events = pd.read_parquet(ROOT / "kashif_data" / "edgar" / "events_8k.parquet")
    f, _ = shortlist_filings(ROOT / "kashif_data" / "signals" / f"bundle_{window}.pkl", events)
    todo = f[f["tier"].isin(["high", "medium"]) & f["code_only_score"].isna()]
    first = {}
    for side in ("A", "B"):
        p = SD / f"8k_{window}_p1_{side}.json"
        if p.exists():
            for r in json.loads(p.read_text()):
                first[r["accession"]] = (side, r)
    out = {"A": [], "B": []}
    reasons = {}
    new = []
    for r in todo.itertuples(index=False):
        v2 = edgar.CACHE / "docs_v2" / f"{r.accession}.txt"
        v3 = edgar.CACHE / "docs_v3" / f"{r.accession}.txt"
        row = {"accession": r.accession, "ticker": r.ticker, "filing_date": r.filing_date,
               "items": r.items, "text_file": str(v3)}
        if r.accession not in first:
            new.append(row)
            reasons[r.accession] = "never scored"
            continue
        side, prev = first[r.accession]
        t2 = v2.read_text(encoding="utf-8") if v2.exists() else ""
        why = []
        if str(prev.get("rationale", "")).startswith("TEXT_UNUSABLE"):
            why.append("text unusable in v2")
        if len(t2) >= 4990:
            why.append("v2 cut at 5,000 chars")
        if "2.02" in str(r.items).split(",") and "PRESS RELEASE" not in t2:
            why.append("earnings 8-K without press release in v2")
        if r.accession in FLAGGED:
            why.append("borderline call flagged by rater")
        if why:
            out[side].append(row)
            reasons[r.accession] = "; ".join(why)
    for i, row in enumerate(new):
        out["A" if i % 2 == 0 else "B"].append(row)
    for side, rows in out.items():
        for row in rows:
            row["reason"] = reasons[row["accession"]]
        (BD / f"8k_{window}_rescore_{side}.json").write_text(json.dumps(rows, indent=1))
        print(f"8k_{window}_rescore_{side}: {len(rows)} accessions")
    print("reasons:", pd.Series(list(reasons.values())).value_counts().to_dict())


if __name__ == "__main__":
    main(sys.argv[1])
