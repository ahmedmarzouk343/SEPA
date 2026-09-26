"""Experiment 4: build the batches an AI chart judge sees, and score its answers.

    python kashif_engine/scripts/ai_judge_batches.py build     # writes batch text files (no labels)
    python kashif_engine/scripts/ai_judge_batches.py score     # reads the judge's JSON answers, scores them

Batches (anonymised: no ticker, no dates, prices rescaled so the first close is
100, volume as a multiple of its previous 50-bar average):
  step0  -- 60 SYNTHETIC charts generated here (30 textbook VCP bases, 30 non-bases:
            downtrends, loose widening ranges, extended runs). No real stock, no outcome.
  step2  -- First Trial's Minervini set (23 of his buys + 115 matched controls), shown
            up to the EVENING BEFORE the buy day (bars 0..248), ids shuffled.
The judge prompt is frozen in backtest_results/experiment4/JUDGE_PROMPT_v1.md.
Labels stay in files the judge never sees.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "kashif_data" / "experiment4" / "judge"
KEYS = ROOT / "kashif_data" / "experiment4" / "judge_keys"   # labels: never in the judge's folder
MEVAL = ROOT / "kashif_data" / "experiment4" / "minervini_eval"
# Amendments 1-2 (JUDGE_PROMPT_v1.md): the Read tool refuses files over 25k tokens and
# truncates its output after ~39k characters (line 1188 of a 6-chart batch), so a batch
# must fit well inside one read or the judge silently sees only part of it.
BATCH = 3
READ_CAP_CHARS = 35_000                                      # incl. the tool's "N<tab>" line prefixes


def _fmt(df: pd.DataFrame) -> str:
    lines = ["bar,high,low,close,relvol"]
    for i, r in enumerate(df.itertuples(index=False)):
        lines.append(f"{i},{r.h:.2f},{r.l:.2f},{r.c:.2f},{r.v:.2f}")
    return "\n".join(lines)


def _synthetic(rng, kind: str, n=249) -> pd.DataFrame:
    """One anonymised synthetic chart (bars of h/l/c/relvol)."""
    closes, vols = [], []
    p = 100.0
    if kind == "vcp":
        up = rng.integers(90, 130)
        for i in range(up):                                  # prior uptrend (+50..90%)
            p *= 1 + rng.normal(0.0045, 0.012)
            closes.append(p); vols.append(rng.uniform(0.9, 1.4))
        top = p
        depths = sorted(rng.uniform([0.18, 0.08, 0.03], [0.30, 0.14, 0.06]), reverse=True)
        for k, d in enumerate(depths):                       # contractions, each shallower
            seg = rng.integers(12, 30)
            low = top * (1 - d)
            for j in range(seg):
                frac = j / seg
                target = top - (top - low) * np.sin(np.pi * frac)
                p = target * (1 + rng.normal(0, 0.004 + 0.006 * d))
                closes.append(p); vols.append(max(0.3, rng.normal(1.0 - 0.22 * k, 0.12)))
            top = top * rng.uniform(0.985, 1.0)
        while len(closes) < n:                               # tight final area, dry volume
            p = top * (1 - rng.uniform(0.0, 0.03))
            closes.append(p); vols.append(max(0.25, rng.normal(0.55, 0.08)))
    elif kind == "downtrend":
        for i in range(n):
            p *= 1 + rng.normal(-0.002, 0.018)
            closes.append(p); vols.append(rng.uniform(0.7, 1.6))
    elif kind == "loose":
        for i in range(n):                                   # widening, sloppy range
            p *= 1 + rng.normal(0.0003, 0.012 + 0.00012 * i)
            closes.append(p); vols.append(rng.uniform(0.6, 2.0))
    else:                                                    # extended: steep run, no base
        for i in range(n):
            p *= 1 + rng.normal(0.006 if i > n - 60 else 0.002, 0.013)
            closes.append(p); vols.append(rng.uniform(1.0, 2.2) if i > n - 60 else rng.uniform(0.7, 1.3))
    c = np.array(closes[:n]); c = c / c[0] * 100
    rngr = np.abs(rng.normal(0.012, 0.004, n))
    return pd.DataFrame({"h": c * (1 + rngr), "l": c * (1 - rngr), "c": c, "v": np.array(vols[:n])})


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    KEYS.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("step*_batch*.txt"):                   # no stale batches of another size
        f.unlink()
    rng = np.random.default_rng(51)
    items, labels = [], []
    kinds = ["vcp"] * 30 + ["downtrend"] * 10 + ["loose"] * 10 + ["extended"] * 10
    order = rng.permutation(len(kinds))
    for n, i in enumerate(order):
        sid = f"S{n:03d}"
        items.append((sid, _fmt(_synthetic(rng, kinds[i]))))
        labels.append({"id": sid, "kind": kinds[i], "is_vcp": kinds[i] == "vcp"})
    _write("step0", items)
    pd.DataFrame(labels).to_csv(KEYS / "step0_labels.csv", index=False)

    w = pd.read_parquet(MEVAL / "windows.parquet")
    items = []
    for sid, g in w.groupby("id"):
        g = g.sort_values("bar")
        g = g[g["bar"] <= 248]                               # evening before (review: entry-day bar leaks)
        items.append((f"M{sid}", _fmt(g[["h", "l", "c", "v"]])))
    rng.shuffle(items)
    _write("step2", items)
    print(f"step0: 60 synthetic windows; step2: {len(items)} Minervini-set windows (bars 0..248)")


def _write(name, items):
    for b in range(0, len(items), BATCH):
        chunk = items[b:b + BATCH]
        txt = "\n\n".join(f"### CHART {sid}\n{body}" for sid, body in chunk)
        shown = sum(len(str(n)) + 1 + len(ln) + 1 for n, ln in enumerate(txt.splitlines(), 1))
        if shown > READ_CAP_CHARS:
            raise ValueError(f"{name} batch {b // BATCH}: ~{shown} chars in one read > {READ_CAP_CHARS}")
        (OUT / f"{name}_batch{b // BATCH:02d}.txt").write_text(txt, encoding="utf-8")


def _auc(pos, neg):
    pos, neg = np.asarray(pos, float), np.asarray(neg, float)
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    return float(((pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum())
                 / (len(pos) * len(neg)))


def score():
    ans = []
    for f in sorted(OUT.glob("answers_*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("{"):
                ans.append(json.loads(line))
    a = pd.DataFrame(ans)
    dup = a["id"][a["id"].duplicated()].tolist()
    if dup:
        raise ValueError(f"ids answered twice: {dup}")
    s0 = pd.read_csv(KEYS / "step0_labels.csv").merge(a, on="id", how="left")
    if s0["valid_base"].notna().any():
        acc = (s0["valid_base"].astype("boolean") == s0["is_vcp"]).mean()
        print(f"STEP 0 (synthetic): judged {s0['valid_base'].notna().sum()}/60; accuracy {acc:.0%}; "
              f"AUC readiness VCP vs not {_auc(s0[s0.is_vcp].buy_readiness, s0[~s0.is_vcp].buy_readiness):.2f}")
        print(s0.groupby("kind")[["valid_base"]].mean())
    key = pd.read_csv(MEVAL / "key.csv")
    key["jid"] = "M" + key["id"].astype(str)
    k = key.merge(a, left_on="jid", right_on="id", how="left", suffixes=("", "_a"))
    if k["buy_readiness"].notna().any():
        b, c = k[k.label == "MINERVINI_BUY"], k[k.label == "CONTROL"]
        print(f"STEP 2 (Minervini set, evening before): judged {k['buy_readiness'].notna().sum()}/{len(k)}")
        print(f"  AUC his buys vs controls (readiness): {_auc(b.buy_readiness.dropna(), c.buy_readiness.dropna()):.2f}")
        print(f"  valid_base rate: his buys {b.valid_base.astype('boolean').mean():.0%}, controls {c.valid_base.astype('boolean').mean():.0%}")
        passing = b[b.get("passes_tt_core", True).astype(bool) & (b.get("rs_pct", 100) >= 70)] if "passes_tt_core" in b else b
        print(f"  AUC on buys that pass our filters ({len(passing)}): "
              f"{_auc(passing.buy_readiness.dropna(), c.buy_readiness.dropna()):.2f}")


# ---------------------------------------------------------------- Step 3 (STEP3_PREREG.md)
MBOOK = ROOT / "kashif_data" / "experiment4" / "modelbook_eval"
CLEAN_FROM = "2025-09-01"          # Haiku 4.5: training data to Jul 2025, plus a one-month buffer
STATS8 = ["atr14_pct", "ret20", "depth60", "ret60", "ret250", "dist_high", "vol_bo", "dryup10"]


def _stats8(g: pd.DataFrame) -> dict:
    """The README's 8 judge-free window statistics, from bars 0..249 (249 = breakout day)."""
    h, l, c, v = (g[x].to_numpy(float) for x in ("high", "low", "close", "vol_rel"))
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    return {"atr14_pct": tr[-14:].mean() / c[-1], "ret20": c[-1] / c[-21] - 1,
            "depth60": (h[-60:].max() - l[-60:].min()) / h[-60:].max(), "ret60": c[-1] / c[-61] - 1,
            "ret250": c[-1] / c[0] - 1, "dist_high": c[-1] / h.max() - 1,
            "vol_bo": v[-1], "dryup10": v[-11:-1].mean()}


def _logit_fit(X, y, lam=1e-3, iters=50):
    mu, sd = X.mean(0), X.std(0) + 1e-12
    Z = np.c_[np.ones(len(X)), (X - mu) / sd]
    b = np.zeros(Z.shape[1])
    for _ in range(iters):                                   # Newton / IRLS with a small ridge
        p = 1 / (1 + np.exp(-Z @ b))
        H = Z.T @ (Z * (p * (1 - p))[:, None]) + lam * np.eye(len(b))
        b -= np.linalg.solve(H, Z.T @ (p - y) + lam * b)
    return lambda Xn: 1 / (1 + np.exp(-np.c_[np.ones(len(Xn)), (Xn - mu) / sd] @ b))


def step3_frame() -> pd.DataFrame:
    """Key + window statistics + the frozen out-of-sample logistic score (fit before CLEAN_FROM)."""
    key = pd.read_csv(MBOOK / "key.csv", parse_dates=["date"])
    w = pd.read_parquet(MBOOK / "windows.parquet").sort_values(["sample_id", "bar"])
    st = pd.DataFrame({sid: _stats8(g) for sid, g in w.groupby("sample_id")}).T
    k = key.merge(st, left_on="sample_id", right_index=True)
    k["y"] = (k.label == "WINNER").astype(float)
    pre, clean = k[k.date < CLEAN_FROM], k.date >= CLEAN_FROM
    k["logit8"] = _logit_fit(pre[STATS8].to_numpy(float), pre.y.to_numpy())(k[STATS8].to_numpy(float))
    k["clean"] = clean
    return k


def build_step3():
    k = step3_frame()
    c = k[k.clean]
    w = pd.read_parquet(MBOOK / "windows.parquet").sort_values(["sample_id", "bar"])
    w = w[w.sample_id.isin(c.sample_id)].rename(columns={"high": "h", "low": "l", "close": "c", "vol_rel": "v"})
    items = [(f"B{sid}", _fmt(g[["h", "l", "c", "v"]])) for sid, g in w.groupby("sample_id")]
    np.random.default_rng(61).shuffle(items)
    for f in OUT.glob("step3_batch*.txt"):
        f.unlink()
    _write("step3", items)
    print(f"step3: {len(items)} clean windows ({c.label.value_counts().to_dict()}), "
          f"{(len(items) + BATCH - 1) // BATCH} batches")


def _top_third(s: pd.Series) -> pd.Series:
    return s.rank(method="first", ascending=False) <= len(s) / 3


def step3_baselines(k: pd.DataFrame | None = None) -> dict:
    """Judge-free numbers on the clean samples; fixed before any judging."""
    k = step3_frame() if k is None else k
    c = k[k.clean]
    top = _top_third(c.logit8)
    mech = c.vcp_ready_x1_2.astype(bool)
    return {"n": len(c), "winners": int(c.y.sum()),
            "logit8_auc": _auc(c[c.y == 1].logit8, c[c.y == 0].logit8),
            "logit8_top3_fwd60_mean": c[top].fwd_ret60.mean(), "logit8_rest_fwd60_mean": c[~top].fwd_ret60.mean(),
            "mech_yes_n": int(mech.sum()), "mech_yes_fwd60_mean": c[mech].fwd_ret60.mean(),
            "mech_no_fwd60_mean": c[~mech].fwd_ret60.mean(), "all_fwd60_mean": c.fwd_ret60.mean()}


def step3_report():
    k = step3_frame()
    ans = [json.loads(ln) for f in sorted(OUT.glob("answers_step3_*.jsonl"))
           for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
    a = pd.DataFrame(ans)
    a["sample_id"] = a["id"].str[1:].astype(k.sample_id.dtype)
    c = k[k.clean].merge(a.drop(columns="id"), on="sample_id", how="left")
    print(f"STEP 3: judged {c.buy_readiness.notna().sum()}/{len(c)} clean breakouts")
    base = step3_baselines(k)
    yes = c.valid_base.astype("boolean").fillna(False).astype(bool)
    top = _top_third(c.buy_readiness.fillna(-1))
    r = {"ai_auc": _auc(c[c.y == 1].buy_readiness.dropna(), c[c.y == 0].buy_readiness.dropna()),
         "ai_yes_n": int(yes.sum()), "ai_yes_fwd60_mean": c[yes].fwd_ret60.mean(),
         "ai_no_fwd60_mean": c[~yes].fwd_ret60.mean(),
         "ai_top3_fwd60_mean": c[top].fwd_ret60.mean(), "ai_rest_fwd60_mean": c[~top].fwd_ret60.mean()}
    rng = np.random.default_rng(97)
    wins = 0
    for _ in range(2000):                                    # paired bootstrap: P(AI AUC > logit8 AUC)
        s = c.iloc[rng.integers(0, len(c), len(c))]
        pos, neg = s[s.y == 1], s[s.y == 0]
        wins += _auc(pos.buy_readiness, neg.buy_readiness) > _auc(pos.logit8, neg.logit8)
    r["p_ai_auc_beats_logit8"] = wins / 2000
    for d in (base, r):
        for key_, val in d.items():
            print(f"  {key_:28s} {val:.3f}" if isinstance(val, float) else f"  {key_:28s} {val}")
    reject = [why for why, bad in [
        ("AI AUC <= statistics baseline", r["ai_auc"] <= base["logit8_auc"]),
        ("AI-yes fwd60 <= AI-no fwd60", r["ai_yes_fwd60_mean"] <= r["ai_no_fwd60_mean"]),
        ("AI top-third fwd60 <= statistics top-third", r["ai_top3_fwd60_mean"] <= base["logit8_top3_fwd60_mean"]),
        ("AI top-third fwd60 <= mechanical-yes fwd60", r["ai_top3_fwd60_mean"] <= base["mech_yes_fwd60_mean"])] if bad]
    print("VERDICT:", "REJECTED: " + "; ".join(reject) if reject else "SURVIVES SCREENING (not proof; see prereg)")
    return c


def _group_auc(k: pd.DataFrame, col: str) -> float:
    """Mean over match groups of P(buy scores above its own controls), ties 1/2
    (the eval set's README: score within groups, not pooled)."""
    vals = []
    for _, g in k.groupby("match_group"):
        b, c = g[g.label == "MINERVINI_BUY"][col].dropna(), g[g.label == "CONTROL"][col].dropna()
        if len(b) and len(c):
            vals.append(_auc(b, c))
    return float(np.mean(vals)) if vals else float("nan")


def step2_report():
    """Step 2 in full: the judge vs his buys, next to baselines computed live on the
    same evening-before windows (bars 0..248) the judge saw."""
    ans = [json.loads(ln) for f in sorted(OUT.glob("answers_step2_*.jsonl"))
           for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
    a = pd.DataFrame(ans).rename(columns={"id": "jid"})
    key = pd.read_csv(MEVAL / "key.csv")
    key["jid"] = "M" + key["id"].astype(str)
    w = pd.read_parquet(MEVAL / "windows.parquet")
    w = w[w["bar"] <= 248].sort_values(["id", "bar"])
    last = w.groupby("id").tail(1).set_index("id")
    prev = w[w["bar"] == 247].set_index("id")
    hi = w.groupby("id")["h"].max()
    base = pd.DataFrame({"last_relvol": last["v"], "last_ret": last["c"] / prev["c"] - 1,
                         "near_high": last["c"] / hi})
    k = key.merge(a, on="jid", how="left").merge(base, left_on="id", right_index=True, how="left")
    k["valid"] = k["valid_base"].astype("boolean").astype(float)
    print(f"STEP 2: judged {k['buy_readiness'].notna().sum()}/{len(k)} windows (bars 0..248, the evening before)")
    filt = k[(k.label == "CONTROL") | (k.passes_tt_core.astype(bool) & (k.rs_pct >= 70))]
    rows = []
    for name, col in [("AI buy_readiness", "buy_readiness"), ("AI valid_base", "valid"),
                      ("baseline: last-bar relvol", "last_relvol"), ("baseline: last-bar return", "last_ret"),
                      ("baseline: close / 249-bar high", "near_high")]:
        rows.append({"score": name,
                     "within-group AUC (23 buys)": _group_auc(k, col),
                     "within-group AUC (18 filtered)": _group_auc(filt, col),
                     "pooled AUC (23)": _auc(k[k.label == "MINERVINI_BUY"][col].dropna(),
                                             k[k.label == "CONTROL"][col].dropna())})
    print(pd.DataFrame(rows).round(2).to_string(index=False))
    b, c = k[k.label == "MINERVINI_BUY"], k[k.label == "CONTROL"]
    print(f"valid_base: his buys {b.valid.mean():.0%} ({int(b.valid.sum())}/{len(b)}), "
          f"controls {c.valid.mean():.0%} ({int(c.valid.sum())}/{len(c)})")
    print(f"mean readiness: his buys {b.buy_readiness.mean():.0f}, controls {c.buy_readiness.mean():.0f}")
    return k


def extract(batch_name: str, transcript: str) -> bool:
    """Apply the delivery rule to one judge's transcript (Amendment 2) and, only if it
    passes, save its answers. Rule: exactly one Read, of this batch file, with no
    offset/limit, whose result reaches the file's last line (nothing truncated); no
    tool other than that Read and the SubagentHandback that returns the reply; answers
    for exactly this batch's charts. The FIRST answer given for a chart is kept."""
    text = (OUT / f"{batch_name}.txt").read_text(encoding="utf-8")
    want = [ln[len("### CHART "):].strip() for ln in text.splitlines() if ln.startswith("### CHART ")]
    last = text.rstrip("\n").splitlines()[-1]
    reads, others, results, texts = [], [], {}, []
    for line in open(transcript, encoding="utf-8"):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        content = (e.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            t = b.get("type")
            if t == "tool_use" and b.get("name") == "Read":
                reads.append((b.get("id"), b.get("input") or {}))
            elif t == "tool_use" and b.get("name") == "SubagentHandback":
                texts.append((b.get("input") or {}).get("message", ""))
            elif t == "tool_use":
                others.append(b.get("name"))
            elif t == "tool_result":
                body = b.get("content")
                results[b.get("tool_use_id")] = body if isinstance(body, str) else "".join(
                    x.get("text", "") for x in body or [] if isinstance(x, dict))
            elif t == "text" and e.get("type") == "assistant":
                texts.append(b.get("text", ""))
    problems = []
    if len(reads) != 1:
        problems.append(f"{len(reads)} Read calls")
    else:
        rid, inp = reads[0]
        if Path(inp.get("file_path", "")).name != f"{batch_name}.txt":
            problems.append(f"read {inp.get('file_path')}")
        if inp.get("offset") or inp.get("limit"):
            problems.append("offset/limit used")
        if last not in results.get(rid, ""):
            problems.append("read result truncated (last line missing)")
    if others:
        problems.append(f"other tools: {others}")
    answers, revised, extra = {}, set(), set()
    for t in texts:
        for ln in t.splitlines():
            ln = ln.strip().strip("`").rstrip(",")
            if not ln.startswith("{"):
                continue
            try:
                o = json.loads(ln)
            except ValueError:
                continue
            i = o.get("id")
            if i not in want:
                extra.add(i)
            elif i not in answers:
                answers[i] = o
            elif answers[i] != o:
                revised.add(i)
    if extra:
        problems.append(f"answers for unknown ids {sorted(map(str, extra))}")
    if set(answers) != set(want):
        problems.append(f"answered {len(answers)}/{len(want)}")
    ok = not problems
    print(f"{batch_name}: {'ACCEPTED' if ok else 'DISCARDED: ' + '; '.join(problems)}"
          + (f" (later revisions ignored: {sorted(revised)})" if revised else ""))
    dest = OUT / f"answers_{batch_name}.jsonl"
    if ok:
        dest.write_text("\n".join(json.dumps(answers[i]) for i in want) + "\n", encoding="utf-8")
    else:
        dest.unlink(missing_ok=True)                         # never keep answers a re-check rejects
    return ok


def check():
    """Each saved answer file must cover exactly the charts of its batch file."""
    bad = 0
    for f in sorted(OUT.glob("answers_*.jsonl")):
        batch = OUT / (f.stem.removeprefix("answers_") + ".txt")
        want = {ln[len("### CHART "):].strip() for ln in batch.read_text(encoding="utf-8").splitlines()
                if ln.startswith("### CHART ")}
        got = [json.loads(ln)["id"] for ln in f.read_text(encoding="utf-8").splitlines()
               if ln.strip().startswith("{")]
        miss, extra = want - set(got), set(got) - want
        ok = not miss and not extra and len(got) == len(want)
        bad += not ok
        print(f"{f.name}: {len(got)}/{len(want)} {'OK' if ok else f'MISSING {sorted(miss)} EXTRA {sorted(extra)}'}")
    print("ALL OK" if bad == 0 else f"{bad} answer file(s) incomplete")


if __name__ == "__main__":
    if sys.argv[1] == "extract":                             # extract <batch_name> <transcript>
        sys.exit(0 if extract(sys.argv[2], sys.argv[3]) else 1)
    if sys.argv[1] == "step3_baselines":
        for kk, vv in step3_baselines().items():
            print(f"{kk:28s} {vv:.4f}" if isinstance(vv, float) else f"{kk:28s} {vv}")
        sys.exit(0)
    {"build": build, "score": score, "check": check, "step2": step2_report,
     "build_step3": build_step3, "step3": step3_report}[sys.argv[1]]()
