"""Score SEC 8-K catalysts for the entry shortlist and log a track record.

    python kashif_engine/scripts/build_catalysts.py tune [--max-llm N]

Shortlist = ticker-days that reached entry timing with a price-ready VCP
breakout under the loosest grid (the only days on which a catalyst can change
a ranking). Filings considered = 8-Ks usable within the 90 days up to each
shortlist day. Code-only layer first; the model reads high/medium-tier
filings only, newest-relative-to-candidate first, until the budget or the
free-tier quota runs out. Coverage is reported, never hidden.

Track record: every scored filing's forward total return over 10/20/60
trading days from its usable date's close, raw and minus MDY.
"""
import argparse
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kashif_engine.catalyst import edgar  # noqa: E402
from kashif_engine.catalyst.scorer import Scorer, BudgetExceeded, _spent  # noqa: E402
from kashif_engine.data import prices as P  # noqa: E402

OUT = ROOT / "kashif_data" / "catalyst"


def shortlist_filings(bundle_path, events):
    b = pickle.load(open(bundle_path, "rb"))
    v = b["vcp"]
    ready = v[v["price_ready_min"].fillna(False).astype(bool)][["ticker", "date"]]
    ev = events.copy()
    ev["usable_from"] = pd.to_datetime(ev["usable_from"])
    rows = []
    for t, g in ready.groupby("ticker"):
        e = ev[ev["ticker"] == t]
        for d in g["date"]:
            w = e[(e["usable_from"] <= d) & (e["usable_from"] > d - pd.Timedelta(days=90))]
            for r in w.itertuples(index=False):
                rows.append({"accession": r.accession, "cand_date": d, "gap_days": (d - r.usable_from).days})
    sl = pd.DataFrame(rows)
    if sl.empty:
        return ev.iloc[0:0], ready
    first = sl.groupby("accession").agg(nearest_gap=("gap_days", "min"), n_cand_days=("cand_date", "count"))
    f = ev.set_index("accession").join(first, how="inner").reset_index()
    return f, ready


def forward_returns(f):
    out = []
    mdy = P.load("MDY")["AdjClose"]
    for r in f.itertuples(index=False):
        px = P.load(r.ticker)
        if px is None:
            continue
        s = px["AdjClose"]
        d0 = s.index[s.index >= pd.Timestamp(r.usable_from)]
        if len(d0) == 0:
            continue
        i = s.index.get_loc(d0[0])
        j = mdy.index.get_indexer([d0[0]], method="bfill")[0]
        rec = {"accession": r.accession}
        for h in (10, 20, 60):
            if i + h < len(s) and j + h < len(mdy):
                ret = s.iloc[i + h] / s.iloc[i] - 1
                rec[f"fwd_{h}d"] = ret
                rec[f"fwd_{h}d_vs_mdy"] = ret - (mdy.iloc[j + h] / mdy.iloc[j] - 1)
        out.append(rec)
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("window")
    ap.add_argument("--max-llm", type=int, default=2500)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    events = pd.read_parquet(ROOT / "kashif_data" / "edgar" / "events_8k.parquet")
    f, ready = shortlist_filings(ROOT / "kashif_data" / "signals" / f"bundle_{a.window}.pkl", events)
    print(f"shortlist: {len(ready)} candidate ticker-days, {len(f)} 8-K filings within 90 days")
    print("tiers:", f["tier"].value_counts().to_dict())

    scorer = Scorer(log=print)
    recs, n_llm = [], 0
    # newest-relative-to-a-candidate first, so a quota cut drops the least relevant filings
    f = f.sort_values(["tier", "nearest_gap"], key=lambda s: s.map({"high": 0, "medium": 1, "low": 2, "none": 3})
                      if s.name == "tier" else s)
    stop_reason = None
    for r in f.to_dict("records"):
        src = f"SEC {r['form']} {r['accession']} items {r['items']} filed {r['filing_date']}"
        base = {"ticker": r["ticker"], "accession": r["accession"], "usable_from": r["usable_from"],
                "filing_date": r["filing_date"], "items": r["items"], "tier": r["tier"], "source": src}
        if isinstance(r["code_only_score"], str) and r["code_only_score"]:   # NaN is truthy -- be explicit
            recs.append(base | {"score": r["code_only_score"], "method": "code_only",
                                "rationale": f"Item(s) {r['items']}: code-only rule (bankruptcy / restatement / "
                                             f"listing deficiency)."})
            continue
        if r["tier"] in ("low", "none"):
            recs.append(base | {"score": "NEUTRAL", "method": "code_only",
                                "rationale": f"Only routine items ({r['items'] or 'none'}); not read by the model."})
            continue
        if stop_reason or n_llm >= a.max_llm:
            recs.append(base | {"score": "NOT_SCORED", "method": "skipped",
                                "rationale": stop_reason or "per-run model call cap reached"})
            continue
        try:
            text = edgar.fetch_text(r["cik"], r["accession"], r["primary_doc"], max_chars=5000)
            res = scorer.score(r, text)
        except BudgetExceeded as e:
            stop_reason = str(e)
            recs.append(base | {"score": "NOT_SCORED", "method": "skipped", "rationale": stop_reason})
            continue
        if res["score"] == "NOT_SCORED" and res.get("rationale") == "all providers exhausted":
            stop_reason = "free-tier quota exhausted on every provider"
        n_llm += res.get("model") is not None
        recs.append(base | {"score": res["score"], "method": res.get("model") or "none",
                            "event": res.get("event"), "rationale": res.get("rationale")})
        if len(recs) % 50 == 0:
            print(f"  {len(recs)}/{len(f)} filings, model calls {scorer.calls}, notional ${_spent():.3f}")
    cat = pd.DataFrame(recs)
    cat["usable_from"] = pd.to_datetime(cat["usable_from"])
    cat.to_parquet(OUT / f"catalyst_scores_{a.window}.parquet")
    if a.window == "holdout":
        print("holdout: forward returns withheld (see build_catalyst_table.holdout_finished)")
        return
    tr = cat.merge(forward_returns(cat), on="accession", how="left")
    tr.to_csv(OUT / f"catalyst_track_record_{a.window}.csv", index=False)
    summ = tr.groupby("score")[["fwd_10d", "fwd_20d", "fwd_60d", "fwd_20d_vs_mdy", "fwd_60d_vs_mdy"]] \
        .agg(["count", "mean", "median"])
    print(summ.to_string())
    print(f"model calls this run {scorer.calls}; notional spend to date ${_spent():.4f}; stop: {stop_reason}")
    json.dump({"filings": len(cat), "by_score": cat["score"].value_counts().to_dict(),
               "by_method": cat["method"].value_counts().to_dict(), "model_calls": scorer.calls,
               "notional_usd_total": _spent(), "stop_reason": stop_reason},
              open(OUT / f"catalyst_summary_{a.window}.json", "w"), indent=2, default=str)


if __name__ == "__main__":
    main()
