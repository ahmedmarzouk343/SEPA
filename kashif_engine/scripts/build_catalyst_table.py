"""Merge every catalyst source into the table the strategy ranks with.

    python kashif_engine/scripts/build_catalyst_table.py tune

Sources (all cached, so later runs only add new work):
  8-K  SEC filings on the shortlist. Rater priority: Claude subagent score
       (agent_scores/8k_*.json) > free-tier API score (llm_cache, gpt-oss-20b /
       gemini flash-lite) > code-only rule (1.03/4.02/3.01 negative, low tier
       neutral). usable_from = the 8-K acceptance rule (16:00 New York).
  news web news found by research sessions (agent_scores/news_<window>_*.json).
       usable_from = publication date + 1 day (time of day unknown).
Checks enforced in code, not trusted from the agents: valid rubric label,
publication date inside the searched window, one row per item.

Outputs kashif_data/catalyst/catalyst_scores_<window>.parquet (read by the
strategy), a track record with 10/20/60-day forward returns per item, and a
rater-agreement table for filings scored twice.
"""
import glob
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kashif_engine.catalyst.scorer import PROMPT_VERSION  # noqa: E402
from kashif_engine.scripts.build_catalysts import forward_returns, shortlist_filings  # noqa: E402

CAT = ROOT / "kashif_data" / "catalyst"
VALID = {"STRONG_POSITIVE", "NEUTRAL", "STRONG_NEGATIVE"}
LOCK = ROOT / "kashif_data" / "tuning" / "HOLDOUT_LOCK"


def holdout_finished():
    return LOCK.exists() and "finished_utc" in json.loads(LOCK.read_text())


def main(window):
    events = pd.read_parquet(ROOT / "kashif_data" / "edgar" / "events_8k.parquet")
    f, _ = shortlist_filings(ROOT / "kashif_data" / "signals" / f"bundle_{window}.pkl", events)
    agent = {}
    # First-pass files, then rescore files: a rescore (made on the v3 full-text
    # extraction) always replaces the first-pass score for the same accession.
    paths = sorted(glob.glob(str(CAT / "agent_scores" / "8k_*.json")), key=lambda p: ("rescore" in p, p))
    for p in paths:
        for r in json.loads(Path(p).read_text()):
            if str(r.get("rationale", "")).startswith("TEXT_UNUSABLE"):
                agent.pop(r["accession"], None)     # a non-answer is not a NEUTRAL verdict
            elif r.get("score") in VALID:
                agent[r["accession"]] = r
    rows, agree = [], []
    for r in f.to_dict("records"):
        base = {"ticker": r["ticker"], "usable_from": pd.Timestamp(r["usable_from"]), "source_type": "8-K",
                "ref": r["accession"], "items": r["items"], "tier": r["tier"],
                "source": f"SEC {r['form']} {r['accession']} items {r['items']} filed {r['filing_date']}"}
        api_p = ROOT / "kashif_data" / "llm_cache" / f"{r['accession']}_{PROMPT_VERSION}.json"
        api = json.loads(api_p.read_text()) if api_p.exists() else None
        if isinstance(r["code_only_score"], str):
            rows.append(base | {"score": r["code_only_score"], "rater": "code_only",
                                "rationale": f"item(s) {r['items']} (code-only rule)"})
        elif r["tier"] in ("low", "none"):
            rows.append(base | {"score": "NEUTRAL", "rater": "code_only", "rationale": "routine items only"})
        elif r["accession"] in agent:
            a = agent[r["accession"]]
            rows.append(base | {"score": a["score"], "rater": "claude_subagent", "rationale": a.get("rationale", "")})
            if api and api.get("score") in VALID:
                agree.append({"accession": r["accession"], "agent": a["score"], "api": api["score"],
                              "api_model": api.get("model")})
        elif api and api.get("score") in VALID and api.get("model"):
            rows.append(base | {"score": api["score"], "rater": api["model"], "rationale": api.get("rationale", "")})
        else:
            rows.append(base | {"score": "NOT_SCORED", "rater": "none", "rationale": "no rater reached it"})

    rejected = 0
    for p in glob.glob(str(CAT / "agent_scores" / f"news_{window}_*.json")):
        for n in json.loads(Path(p).read_text()):
            if n.get("score") not in VALID or not n.get("published"):
                continue                        # NONE_FOUND rows carry no signal
            pub = pd.Timestamp(n["published"])
            if not (pd.Timestamp(n["window_start"]) <= pub <= pd.Timestamp(n["window_end"])):
                rejected += 1
                continue
            rows.append({"ticker": n["ticker"], "usable_from": pub + pd.Timedelta(days=1), "source_type": "news",
                         "ref": n.get("url"), "items": None, "tier": None, "score": n["score"],
                         "rater": "claude_research_session",
                         "source": f"{str(n.get('outlet', '')).strip()} {n['published']}: {n.get('headline', '')}",
                         "rationale": n.get("rationale", "")})
    cat = pd.DataFrame(rows).drop_duplicates(subset=["ticker", "ref"])
    cat.to_parquet(CAT / f"catalyst_scores_{window}.parquet")
    print(f"{window}: {len(cat)} catalyst rows | news window-date rejections: {rejected}")
    print(cat.groupby(["source_type", "score"]).size().to_string())
    if window == "holdout" and not holdout_finished():
        # Outcome statistics for the holdout would be seen BEFORE the one holdout
        # run -- exactly what the holdout protocol forbids. Scores only until then.
        print("holdout: forward returns withheld until run_holdout.py has finished")
        return
    fr = forward_returns(cat.rename(columns={"ref": "accession"}).assign(accession=cat["ref"]))
    tr = cat.merge(fr.rename(columns={"accession": "ref"}), on="ref", how="left")
    tr.to_csv(CAT / f"catalyst_track_record_{window}.csv", index=False)
    ag = pd.DataFrame(agree)
    ag.to_csv(CAT / f"rater_agreement_{window}.csv", index=False)
    print("raters:", cat["rater"].value_counts().to_dict())
    if len(ag):
        print(f"rater agreement (agent vs API) on {len(ag)} filings: {(ag.agent == ag.api).mean():.1%}")
        print(pd.crosstab(ag.agent, ag.api).to_string())
    summ = tr[tr["score"].isin(VALID)].groupby(["source_type", "score"])[
        ["fwd_20d", "fwd_60d", "fwd_20d_vs_mdy", "fwd_60d_vs_mdy"]].agg(["count", "mean", "median"])
    print(summ.round(4).to_string())


if __name__ == "__main__":
    main(sys.argv[1])
