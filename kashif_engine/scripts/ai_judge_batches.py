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
    {"build": build, "score": score, "check": check}[sys.argv[1]]()
