#!/usr/bin/env python3
"""Experiment 3: daily forward (paper-trading) runner -- SKELETON. Virtual money only.

Design: paper_trading/exp3/DESIGN.md. Each NYSE session D, after the close:
fetch D's bars into a write-once snapshot, update the forward fundamentals
store per ticker, replay EVERY arm over [Day 1, D] with frozen code, compare
the replay with every published session (divergence alarm), write
log/D.jsonl (canonical JSON, SHA-256 chain), commit and push.

    python3 paper_trading/exp3/run_day.py --help
    python3 paper_trading/exp3/run_day.py --dry-run --session 2026-09-28
    python3 paper_trading/exp3/run_day.py --dry-run --demo-dir /tmp/x   # synthetic 2-session chain
    python3 paper_trading/exp3/run_day.py --verify-chain

Real, unit-tested code (test_run_day.py): canonical JSON, record builders,
day-file render/parse, hash chain, divergence comparison, run-dir -> records,
snapshot validation + write-once partitions, genesis-basis price frames,
split detection, append-only fundamentals merge, atomic partition write,
NYSE session helpers (DRAFT table), arms.json validation, git command plan.

Stubs (raise NotImplementedError, marked TODO): Yahoo fetch, EDGAR poll,
per-ticker SEC re-extraction, genesis fetch, the replay subprocess, running
the git commands.

HARD RULE: there is no order-routing path, no broker SDK, and no credential,
API key or token anywhere in this file -- not even a placeholder. Network is
limited to Yahoo (yfinance) and SEC EDGAR with the repo's existing SEC_UA.

Importing this module has no side effects: no network, no file writes, no
sys.path edits. pandas/pyarrow are imported inside the functions that use them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

ARMS_FILE = HERE / "arms.json"
GENESIS_FILE = HERE / "GENESIS.json"
UNIVERSE_FILE = HERE / "universe.txt"
AMENDMENTS_FILE = HERE / "AMENDMENTS.jsonl"
LOG_DIR = HERE / "log"
SNAP_DIR = HERE / "snapshot"
STORE_DIR = HERE / "fundamentals_store"
STORE_STAGING = HERE / "fundamentals_store.staging"
STORE_LOG_DIR = HERE / "store_log"
RATINGS_DIR = HERE / "ratings"
WORK_DIR = HERE / "work"

SCHEMA = "exp3-journal/1"
GENESIS_SESSION = "2026-09-25"
DAY1 = "2026-09-28"
FLOAT_DECIMALS = 8
BENCHMARKS = ("MDY", "IJR", "SPY")
REFETCH_SESSIONS = 10
MIN_COVERAGE = 0.99
SETTLE_AGREEMENT = 0.995
EPS_NULL_TICKERS = ("FIZZ",)          # merged_pipeline.XBRL_EPS_UNRELIABLE, checked by store_integrity()
QUARTER_MATCH_DAYS = 5                # merged_pipeline.DATE_TOL

# Record types in file order; COMPARED are re-derived by every replay and
# checked against the published files (header/arm_status carry timings).
RECORD_ORDER = ("header", "arm_status", "benchmark", "candidate", "order", "fill", "dividend",
                "trade_closed", "position", "equity", "event", "divergence", "footer")
COMPARED = frozenset({"candidate", "order", "fill", "dividend", "trade_closed", "position", "equity", "event"})
REQUIRED = {
    "header": ("schema", "session", "prev_session", "seq", "prev_file_sha256", "code_commit", "arms_sha256",
               "snapshot", "store_sha256", "env", "status"),
    "arm_status": ("arm", "session", "state"),
    "benchmark": ("session",),
    "candidate": ("arm", "session", "rank", "ticker", "decision"),
    "order": ("arm", "session", "for_session", "ticker", "side", "type"),
    "fill": ("arm", "session", "ticker", "side", "shares_adj", "price_adj", "commission", "slippage", "reason"),
    "dividend": ("arm", "session", "ticker", "shares_adj", "per_share_adj", "amount"),
    "trade_closed": ("arm", "session", "ticker", "entry_session", "net_pnl", "exit_reason"),
    "position": ("arm", "session", "ticker", "shares_adj", "cost_adj"),
    "equity": ("arm", "session", "equity", "cash", "n_positions", "peak_equity", "drawdown"),
    "event": ("arm", "session", "event"),
    "divergence": ("arm", "session", "first_session"),
    "footer": ("session", "n_lines", "body_sha256"),
}

# --------------------------------------------------------------------------
# NYSE calendar. UNCERTAIN / DRAFT: written from NYSE holiday rules, NOT copied
# from nyse.com -- verify before freezing. Valid through CALENDAR_VALID_THROUGH;
# past it, is_session() raises so the table must be extended in time.
# --------------------------------------------------------------------------
CALENDAR_VALID_FROM = "2026-01-01"
CALENDAR_VALID_THROUGH = "2027-12-31"
NYSE_HOLIDAYS_DRAFT = frozenset({
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
    "2026-09-07", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05",
    "2027-09-06", "2027-11-25", "2027-12-24",
})
NYSE_EARLY_CLOSES_DRAFT = frozenset({"2026-11-27", "2026-12-24", "2027-11-26"})   # 13:00 ET close


def _as_date(d) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d)[:10])


def is_session(d) -> bool:
    d = _as_date(d)
    if not (date.fromisoformat(CALENDAR_VALID_FROM) <= d <= date.fromisoformat(CALENDAR_VALID_THROUGH)):
        raise ValueError(f"{d} is outside the NYSE calendar table ({CALENDAR_VALID_FROM}..{CALENDAR_VALID_THROUGH})")
    return d.weekday() < 5 and d.isoformat() not in NYSE_HOLIDAYS_DRAFT


def is_early_close(d) -> bool:
    return is_session(d) and _as_date(d).isoformat() in NYSE_EARLY_CLOSES_DRAFT


def next_session(d) -> str:
    d = _as_date(d) + timedelta(days=1)
    while not is_session(d):
        d += timedelta(days=1)
    return d.isoformat()


def previous_session(d) -> str:
    d = _as_date(d) - timedelta(days=1)
    while not is_session(d):
        d -= timedelta(days=1)
    return d.isoformat()


def sessions_between(first, last) -> list[str]:
    out, d = [], _as_date(first)
    while d <= _as_date(last):
        if is_session(d):
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


# --------------------------------------------------------------------------
# Canonical JSON (DESIGN.md 4.3)
# --------------------------------------------------------------------------
def fmt_float(x: float) -> str:
    """Fixed 8-decimal text, trailing zeros stripped, -0 -> 0. Raises on +-inf/NaN."""
    if math.isnan(x) or math.isinf(x):
        raise ValueError(f"non-finite float {x!r} has no canonical form")
    s = f"{x:.{FLOAT_DECIMALS}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _is_missing(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    return type(v).__name__ in ("NAType", "NaTType")


def _canon(v) -> str:
    if _is_missing(v):
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return fmt_float(v)
    if isinstance(v, Decimal):
        return fmt_float(float(v))
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, datetime):
        return json.dumps(v.isoformat())
    if isinstance(v, date):
        return json.dumps(v.isoformat())
    if isinstance(v, dict):
        for k in v:
            if not isinstance(k, str):
                raise TypeError(f"canonical JSON keys must be str, got {k!r}")
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + _canon(v[k]) for k in sorted(v)) + "}"
    if isinstance(v, (list, tuple)):
        return "[" + ",".join(_canon(x) for x in v) + "]"
    if isinstance(v, (set, frozenset)):
        raise TypeError("sets have no defined order; pass a sorted list")
    if hasattr(v, "item") and callable(v.item):          # numpy scalar
        return _canon(v.item())
    raise TypeError(f"no canonical form for {type(v).__name__}")


def canonical_json(obj) -> str:
    """Sorted keys, no whitespace, fixed float formatting, UTF-8 text."""
    return _canon(obj)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_text(s: str) -> str:
    return sha256_bytes(s.encode("utf-8"))


def sha256_file(p) -> str:
    return sha256_bytes(Path(p).read_bytes())


# --------------------------------------------------------------------------
# Records and day files (DESIGN.md 4.2, 4.4)
# --------------------------------------------------------------------------
def make_record(kind: str, **fields) -> dict:
    if kind not in REQUIRED:
        raise ValueError(f"unknown record type {kind!r}")
    missing = [k for k in REQUIRED[kind] if k not in fields]
    if missing:
        raise ValueError(f"{kind} record missing {missing}")
    return {"record": kind, **fields}


def _sort_key(r: dict, arm_order: list[str]):
    arm = r.get("arm")
    arm_i = arm_order.index(arm) if arm in arm_order else (-1 if arm is None else len(arm_order))
    rank = r.get("rank") if r["record"] == "candidate" and isinstance(r.get("rank"), int) else 0
    return (arm_i, RECORD_ORDER.index(r["record"]), str(r.get("session", "")), rank,
            str(r.get("ticker", "")), canonical_json(r))


def sort_body(records: list[dict], arm_order: list[str]) -> list[dict]:
    return sorted(records, key=lambda r: _sort_key(r, arm_order))


def build_header(session, prev_session, prev_file_sha256, seq, code_commit, arms_sha256, snapshot,
                 store_sha256, env, status="ON_TIME", **extra) -> dict:
    return make_record("header", schema=SCHEMA, session=session, prev_session=prev_session, seq=seq,
                       prev_file_sha256=prev_file_sha256, code_commit=code_commit, arms_sha256=arms_sha256,
                       snapshot=snapshot, store_sha256=store_sha256, env=env, status=status, **extra)


def render_day_file(header: dict, body: list[dict], arm_order: list[str]) -> bytes:
    """header + sorted body + footer, one canonical line each."""
    if header.get("record") != "header":
        raise ValueError("first record must be the header")
    for r in body:
        if r["record"] in ("header", "footer"):
            raise ValueError("body may not hold header/footer records")
        if r.get("session") != header["session"]:
            raise ValueError(f"record for {r.get('session')} in the {header['session']} file")
    lines = [canonical_json(header)] + [canonical_json(r) for r in sort_body(body, arm_order)]
    head = "".join(ln + "\n" for ln in lines).encode("utf-8")
    footer = make_record("footer", session=header["session"], n_lines=len(lines), body_sha256=sha256_bytes(head))
    return head + (canonical_json(footer) + "\n").encode("utf-8")


def parse_day_file(data: bytes):
    """-> (header, body, footer, problems). Rejects non-canonical lines and footer mismatches."""
    problems = []
    if not data.endswith(b"\n"):
        problems.append("file does not end with a newline (truncated?)")
    raw_lines = data.decode("utf-8").split("\n")
    if raw_lines and raw_lines[-1] == "":
        raw_lines = raw_lines[:-1]
    recs = []
    for i, ln in enumerate(raw_lines, 1):
        try:
            r = json.loads(ln)
        except json.JSONDecodeError as e:
            problems.append(f"line {i}: not JSON ({e})")
            continue
        if canonical_json(r) != ln:
            problems.append(f"line {i}: not in canonical form")
        recs.append(r)
    if not recs or recs[0].get("record") != "header":
        return None, [], None, problems + ["first line is not a header"]
    if recs[-1].get("record") != "footer":
        return recs[0], recs[1:], None, problems + ["last line is not a footer"]
    header, body, footer = recs[0], recs[1:-1], recs[-1]
    head_bytes = "".join(ln + "\n" for ln in raw_lines[:-1]).encode("utf-8")
    if footer.get("n_lines") != len(raw_lines) - 1:
        problems.append(f"footer n_lines {footer.get('n_lines')} != {len(raw_lines) - 1}")
    if footer.get("body_sha256") != sha256_bytes(head_bytes):
        problems.append("footer body_sha256 does not match the file")
    return header, body, footer, problems


def verify_chain(log_dir=LOG_DIR, genesis_path=GENESIS_FILE) -> list[str]:
    """Every file canonical and self-consistent, sessions increasing, each
    header's prev_file_sha256 == SHA-256 of the previous file (GENESIS.json for
    the first). Empty list = sound."""
    log_dir, genesis_path = Path(log_dir), Path(genesis_path)
    problems = []
    files = sorted(p for p in log_dir.glob("*.jsonl") if len(p.stem) == 10)
    if not files:
        return problems
    if not genesis_path.exists():
        return [f"chain root {genesis_path.name} missing"]
    prev_sha, prev_session, prev_seq = sha256_file(genesis_path), None, 0
    for f in files:
        data = f.read_bytes()
        header, _, _, probs = parse_day_file(data)
        problems += [f"{f.name}: {p}" for p in probs]
        if header is None:
            break
        if header.get("session") != f.stem:
            problems.append(f"{f.name}: header session {header.get('session')} != file name")
        if header.get("prev_file_sha256") != prev_sha:
            problems.append(f"{f.name}: prev_file_sha256 does not match the previous file (chain broken)")
        if prev_session is not None and header.get("prev_session") != prev_session:
            problems.append(f"{f.name}: prev_session {header.get('prev_session')} != {prev_session}")
        if prev_session is not None and str(header.get("session")) <= prev_session:
            problems.append(f"{f.name}: sessions not increasing")
        if header.get("seq") != prev_seq + 1:
            problems.append(f"{f.name}: seq {header.get('seq')} != {prev_seq + 1}")
        prev_sha, prev_session, prev_seq = sha256_bytes(data), header.get("session"), header.get("seq", prev_seq)
    return problems


# --------------------------------------------------------------------------
# Divergence alarm (DESIGN.md 1.6)
# --------------------------------------------------------------------------
def digests_by_arm_session(records) -> dict:
    groups = defaultdict(list)
    for r in records:
        if r.get("record") in COMPARED:
            groups[(r["arm"], r["session"])].append(canonical_json(r))
    return {k: (sha256_text("\n".join(sorted(v))), sorted(v)) for k, v in groups.items()}


def compare_replay(published, replayed, sessions, max_lines=20) -> list[dict]:
    """Per (arm, session) in `sessions`: published vs replayed compared records.
    Returns one mismatch dict per (arm, session) that differs; [] = no divergence."""
    sessions = set(sessions)
    pub = {k: v for k, v in digests_by_arm_session(published).items() if k[1] in sessions}
    rep = {k: v for k, v in digests_by_arm_session(replayed).items() if k[1] in sessions}
    out = []
    for key in sorted(set(pub) | set(rep)):
        a, b = pub.get(key, (None, [])), rep.get(key, (None, []))
        if a[0] == b[0]:
            continue
        sa, sb = set(a[1]), set(b[1])
        out.append({"arm": key[0], "session": key[1],
                    "published_only": sorted(sa - sb)[:max_lines], "replayed_only": sorted(sb - sa)[:max_lines]})
    return out


# --------------------------------------------------------------------------
# Engine run directory -> journal records (DESIGN.md 4.2)
# --------------------------------------------------------------------------
def _d(x) -> str:
    return str(x)[:10]


def _f(x):
    return None if _is_missing(x) else float(x)


def records_from_run_dir(run_dir, arm: str, next_session_fn=next_session) -> list[dict]:
    """Journal records for EVERY session of one engine run (engine.run outputs:
    equity.csv, candidates.csv, fills.csv, dividends.csv, trades.csv, events.csv).
    All are end-independent, so a run ending at D reproduces D-1's records.
    Exit/stop ORDERS need the proposed engine order log (P6): TODO."""
    import pandas as pd
    run_dir = Path(run_dir)

    def csv(name):
        p = run_dir / name
        return pd.read_csv(p) if p.exists() and p.stat().st_size > 2 else pd.DataFrame()

    recs = []
    eq = csv("equity.csv")
    sessions = [_d(x) for x in eq.iloc[:, 0]] if len(eq) else []
    peak = None
    for s, r in zip(sessions, eq.to_dict("records")):
        e = float(r["equity"])
        peak = e if peak is None else max(peak, e)
        recs.append(make_record("equity", arm=arm, session=s, equity=e, cash=float(r["cash"]),
                                n_positions=int(r["n_positions"]), peak_equity=peak, drawdown=e / peak - 1.0))

    cands = csv("candidates.csv")
    rank = defaultdict(int)
    for r in cands.to_dict("records"):
        s = _d(r["date"])
        rank[s] += 1
        recs.append(make_record("candidate", arm=arm, session=s, rank=rank[s], ticker=r["ticker"],
                                decision=None if _is_missing(r.get("decision")) else str(r["decision"]),
                                rank_score=_f(r.get("rank_score")), rs_pct=_f(r.get("rs_pct")),
                                volume_ratio=_f(r.get("volume_ratio")), vcp_quality=_f(r.get("vcp_quality")),
                                pivot=_f(r.get("pivot")), order_value=_f(r.get("order_value")),
                                catalyst=None if _is_missing(r.get("catalyst")) else str(r["catalyst"]),
                                reason=None if _is_missing(r.get("reason")) else str(r["reason"])))
        if r.get("decision") == "ORDER_SUBMITTED":
            recs.append(make_record("order", arm=arm, session=s, for_session=next_session_fn(s),
                                    ticker=r["ticker"], side="BUY", type="MARKET_ON_OPEN",
                                    est_value=_f(r.get("order_value"))))

    fills = csv("fills.csv")
    by_session = defaultdict(list)
    for r in fills.to_dict("records"):
        s = _d(r["date"])
        by_session[s].append(r)
        recs.append(make_record("fill", arm=arm, session=s, ticker=r["ticker"], side=r["side"],
                                shares_adj=float(r["shares"]), price_adj=float(r["price"]),
                                shares_raw=_f(r.get("raw_shares")), price_raw=_f(r.get("raw_price")),
                                commission=float(r["commission"]), slippage=float(r["slippage"]),
                                reason=str(r["reason"]), stop_level=_f(r.get("order_level"))))
    held = {}                                      # ticker -> [shares_adj, cost_adj, entry_session]
    for s in sessions:
        for r in by_session.get(s, []):
            t, q, p = r["ticker"], float(r["shares"]), float(r["price"])
            if r["side"] == "BUY":
                h = held.setdefault(t, [0.0, 0.0, s])
                h[0] += q
                h[1] += q * p
            else:
                h = held[t]
                h[1] -= h[1] * q / h[0]
                h[0] -= q
                if h[0] <= 1e-9:
                    del held[t]
        for t in sorted(held):
            recs.append(make_record("position", arm=arm, session=s, ticker=t, shares_adj=held[t][0],
                                    cost_adj=held[t][1], entry_session=held[t][2]))

    for r in csv("dividends.csv").to_dict("records"):
        recs.append(make_record("dividend", arm=arm, session=_d(r["date"]), ticker=r["ticker"],
                                shares_adj=float(r["shares"]), per_share_adj=float(r["per_share"]),
                                amount=float(r["amount"])))
    for r in csv("trades.csv").to_dict("records"):
        recs.append(make_record("trade_closed", arm=arm, session=_d(r["exit_date"]), ticker=r["ticker"],
                                entry_session=_d(r["entry_date"]), entry_price_adj=_f(r.get("entry_price")),
                                exit_price_adj=_f(r.get("exit_price")), shares_adj=_f(r.get("shares")),
                                net_pnl=float(r["net_pnl"]), return_pct=_f(r.get("return_pct")),
                                exit_reason=str(r["exit_reason"]), bars_held=_f(r.get("bars_held"))))
    for r in csv("events.csv").to_dict("records"):
        detail = {k: v for k, v in r.items() if k not in ("date", "event", "ticker") and not _is_missing(v)}
        recs.append(make_record("event", arm=arm, session=_d(r["date"]), event=str(r["event"]),
                                ticker=None if _is_missing(r.get("ticker")) else str(r["ticker"]),
                                detail=detail))
    return recs


# --------------------------------------------------------------------------
# Bar snapshot (DESIGN.md 5.1, 5.2)
# --------------------------------------------------------------------------
BAR_COLUMNS = ("ticker", "session", "open", "high", "low", "close", "volume", "adj_close",
               "dividends", "splits", "status", "fetched_utc", "source")


def validate_partition(df, session: str, expected_tickers, must_have=()) -> list[str]:
    """A session partition is complete or it is not written (DESIGN.md 2.5)."""
    problems = []
    cols = [c for c in BAR_COLUMNS if c not in df.columns]
    if cols:
        return [f"missing columns {cols}"]
    if (df["session"].astype(str) != session).any():
        problems.append(f"rows dated other than {session}")
    dup = df["ticker"][df["ticker"].duplicated()]
    if len(dup):
        problems.append(f"duplicate tickers {sorted(dup)[:5]}")
    have = set(df["ticker"])
    missing = sorted(set(expected_tickers) - have)
    if missing:
        problems.append(f"{len(missing)} expected tickers unaccounted for (need a bar or NO_BAR): {missing[:10]}")
    extra = sorted(have - set(expected_tickers))
    if extra:
        problems.append(f"tickers outside the frozen universe: {extra[:10]}")
    ok = df[df["status"] == "OK"]
    bad_status = sorted(set(df["status"]) - {"OK", "NO_BAR"})
    if bad_status:
        problems.append(f"unknown status values {bad_status}")
    if len(ok):
        px = ok[["open", "high", "low", "close"]]
        if px.isna().any().any() or (px <= 0).any().any():
            problems.append("non-positive or missing prices on OK rows")
        if ((ok["high"] < ok[["open", "close"]].max(axis=1)) | (ok["low"] > ok[["open", "close"]].min(axis=1))).any():
            problems.append("high/low inconsistent with open/close")
        if (ok["volume"] < 0).any():
            problems.append("negative volume")
    n_expected = len(set(expected_tickers))
    if n_expected and len(ok) / n_expected < MIN_COVERAGE:
        problems.append(f"coverage {len(ok)}/{n_expected} below {MIN_COVERAGE:.0%}")
    no_bar_required = sorted(set(must_have) & set(df.loc[df["status"] != "OK", "ticker"]))
    if no_bar_required:
        problems.append(f"no bar for required names (benchmarks/held/ordered): {no_bar_required}")
    return problems


def frame_content_sha256(df, columns=BAR_COLUMNS) -> str:
    """Hash of canonical rows sorted by ticker: independent of parquet bytes and pyarrow version."""
    rows = df[list(columns)].sort_values("ticker").to_dict("records")
    return sha256_text("\n".join(canonical_json(r) for r in rows))


def write_partition_once(df, snap_dir, session: str):
    """Write snapshot/bars/<session>.parquet exactly once. os.link from a fsynced
    temp file: fails if the partition exists, so a partition is never rewritten.
    -> (path, content_sha256)."""
    out_dir = Path(snap_dir) / "bars"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{session}.parquet"
    if path.exists():
        raise FileExistsError(f"{path} exists: snapshot partitions are write-once")
    df = df[list(BAR_COLUMNS)].sort_values("ticker").reset_index(drop=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{session}.", suffix=".tmp", dir=out_dir)
    os.close(fd)
    try:
        df.to_parquet(tmp, index=False)
        with open(tmp, "rb") as fh:
            os.fsync(fh.fileno())
        os.link(tmp, path)                       # atomic create-if-absent
    finally:
        os.unlink(tmp)
    return path, frame_content_sha256(df)


def snapshot_chain_sha256(genesis_sha: str, partitions) -> str:
    """H(prev | session | content_sha256) over (session, content_sha256) in session order."""
    h = genesis_sha
    for session, sha in sorted(partitions):
        h = sha256_text(f"{h}|{session}|{sha}")
    return h


# --------------------------------------------------------------------------
# Genesis basis and corporate actions (DESIGN.md 5.3, 5.4)
# --------------------------------------------------------------------------
PRICE_COLUMNS = ["Open", "High", "Low", "Close", "AdjClose", "Volume", "Dividends", "Splits"]   # prices.COLUMNS


def anchor_multiplier(index, splits, genesis_session=GENESIS_SESSION):
    """C(t) = product of ratios (new per old) of splits with genesis < ex_date <= t."""
    import pandas as pd
    g0 = pd.Timestamp(genesis_session)
    c = pd.Series(1.0, index=index)
    for s in sorted(splits, key=lambda s: s["ex_date"]):
        ex, r = pd.Timestamp(s["ex_date"]), float(s["ratio"])
        if ex <= g0:
            raise ValueError(f"split {s} is on or before genesis: it is already in Yahoo's genesis basis")
        if not r > 0:
            raise ValueError(f"bad split ratio {s}")
        c[c.index >= ex] *= r
    return c


def anchor_frame(genesis, forward, splits=(), late_dividends=(), genesis_session=GENESIS_SESSION):
    """Price frame on the GENESIS basis, in prices.COLUMNS, ready to materialize
    as kashif_data/prices/US/<T>.parquet (DESIGN.md 5.3, 5.5).

    genesis: Yahoo history (split-adjusted as of genesis), dates <= genesis_session.
    forward: raw bars as first fetched, dates > genesis_session (NO_BAR rows dropped).
    splits: [{ex_date, ratio}] from the actions log (ex_date > genesis).
    late_dividends: [{ex_date, per_share_raw, first_seen}] booked on first_seen.

    Forward OHLC x C(t), volume / C(t), dividends x C(t); Splits = 0 on forward
    bars so add_raw_columns keeps SplitFactor = 1 there; AdjClose chained forward
    as total return. Appending a later split never changes an earlier row."""
    import pandas as pd
    g0 = pd.Timestamp(genesis_session)
    g = genesis[PRICE_COLUMNS].astype(float).copy()
    if g.empty:
        raise ValueError("empty genesis history")
    if g.index.max() > g0:
        raise ValueError("genesis holds bars after the genesis session")
    f = forward.copy()
    if len(f) and f.index.min() <= g0:
        raise ValueError("forward bars must be after the genesis session")
    f = f.sort_index()
    c = anchor_multiplier(f.index, splits, genesis_session)
    out = pd.DataFrame(index=f.index)
    for col in ("Open", "High", "Low", "Close"):
        out[col] = f[col].astype(float) * c
    out["Volume"] = f["Volume"].astype(float) / c
    div = f["Dividends"].fillna(0.0).astype(float) * c if "Dividends" in f else pd.Series(0.0, index=f.index)
    for d in late_dividends:
        first = pd.Timestamp(d["first_seen"])
        book = f.index[f.index >= first]
        if len(book) == 0:
            continue                               # not yet a session in this frame
        ex = pd.Timestamp(d["ex_date"])
        c_ex = float(anchor_multiplier(pd.DatetimeIndex([ex]), splits, genesis_session).iloc[0])
        div.loc[book[0]] += float(d["per_share_raw"]) * c_ex
    out["Dividends"] = div
    out["Splits"] = 0.0
    prev_close = out["Close"].shift(1)
    prev_close.iloc[:1] = g["Close"].iloc[-1]
    ratio = (out["Close"] + out["Dividends"]) / prev_close
    out["AdjClose"] = g["AdjClose"].iloc[-1] * ratio.cumprod()
    res = pd.concat([g, out[PRICE_COLUMNS]])
    res.index.name = "Date"
    return res


SIMPLE_RATIOS = sorted({Fraction(a, b) for a in range(1, 21) for b in range(1, 21) if a != b})


def snap_ratio(r: float, tol: float):
    best = min(SIMPLE_RATIOS, key=lambda f: abs(math.log(r / float(f))))
    return best if abs(math.log(r / float(best))) <= tol else None


def detect_splits(first_fetched: dict, refetched: dict, known_splits, today: str, tol=0.005) -> list[dict]:
    """Compare a re-fetch (Yahoo Close, split-adjusted as of today) with the
    raw closes as first fetched (DESIGN.md 5.4). q(t) = refetched / expected,
    expected = raw / prod(known ratios with t < ex <= today).
      all q ~ 1                         -> []
      q ~ k before a boundary, ~1 after -> SPLIT ratio 1/k, ex_date = boundary
                                           (boundary = today: normal; earlier: late=True)
      anything else                     -> UNEXPLAINED (stop, NEEDS_REVIEW)"""
    dates = sorted(set(first_fetched) & set(refetched))
    if not dates:
        return []
    q = []
    for d in dates:
        k = 1.0
        for s in known_splits:
            if d < s["ex_date"] <= today:
                k *= float(s["ratio"])
        q.append(refetched[d] / (first_fetched[d] / k))

    def one(x):
        return abs(math.log(x)) <= tol

    if all(one(x) for x in q):
        return []
    last_off = max(i for i, x in enumerate(q) if not one(x))
    head, tail = q[:last_off + 1], q[last_off + 1:]
    k = head[-1]
    if all(abs(math.log(x / k)) <= tol for x in head) and all(one(x) for x in tail):
        ratio = snap_ratio(1.0 / k, tol)
        ex = dates[last_off + 1] if tail else today
        if ratio is not None:
            return [{"kind": "SPLIT", "ex_date": ex, "ratio": float(ratio),
                     "ratio_text": f"{ratio.numerator}:{ratio.denominator}", "late": ex < today,
                     "evidence": "refetch_ratio"}]
    return [{"kind": "UNEXPLAINED", "dates": dates, "q": [round(x, 6) for x in q]}]


# --------------------------------------------------------------------------
# Forward fundamentals store (DESIGN.md 6.3 - 6.5)
# --------------------------------------------------------------------------
FUND_VALUE_COLS = ("revenue", "net_income", "eps")


def _same_num(a, b, rel=1e-9) -> bool:
    if _is_missing(a) and _is_missing(b):
        return True
    if _is_missing(a) or _is_missing(b):
        return False
    return abs(float(a) - float(b)) <= rel * max(1.0, abs(float(a)))


def merge_ticker_partition(existing, extracted, session: str, accession=None):
    """Append-only merge of a fresh per-ticker extraction into its stored rows.

    New quarter (no stored quarter within +-5 days): appended with
      sec_filing_date = extracted SEC date, earnings_release_date = first_seen = session,
      release_date_source = FORWARD_FIRST_SEEN, accession.
    Stored quarter: kept verbatim; changed values -> REVISION_IGNORED log entry.
    Stored quarter absent from the extraction: kept -> ROW_ABSENT_IGNORED.
    -> (merged DataFrame sorted by quarter_end_date, log entries)."""
    import pandas as pd
    sess = pd.Timestamp(session)
    ex = existing.copy() if existing is not None and len(existing) else pd.DataFrame(columns=extracted.columns)
    stored = [pd.Timestamp(q) for q in ex.get("quarter_end_date", [])]

    def match(q):
        near = [s for s in stored if abs((s - q).days) <= QUARTER_MATCH_DAYS]
        return min(near, key=lambda s: abs((s - q).days)) if near else None

    log, new_rows, seen = [], [], set()
    by_q = {pd.Timestamp(r["quarter_end_date"]): r for r in ex.to_dict("records")}
    for r in extracted.to_dict("records"):
        q = pd.Timestamp(r["quarter_end_date"])
        filed = pd.Timestamp(r["earnings_release_date"])
        if filed > sess:
            raise ValueError(f"{q.date()}: filing date {filed.date()} is after session {session} (lookahead)")
        m = match(q)
        if m is not None:
            seen.add(m)
            old = by_q[m]
            diffs = {c: [_f(old.get(c)), _f(r.get(c))] for c in FUND_VALUE_COLS if not _same_num(old.get(c), r.get(c))}
            if diffs:
                log.append({"action": "REVISION_IGNORED", "quarter_end_date": _d(m), "diffs": diffs})
            continue
        row = dict(r)
        row.update({"sec_filing_date": filed, "earnings_release_date": sess, "first_seen": sess,
                    "release_date_source": "FORWARD_FIRST_SEEN", "accession": accession})
        new_rows.append(row)
        log.append({"action": "ADD_QUARTER", "quarter_end_date": _d(q), "fiscal_quarter": r.get("fiscal_quarter"),
                    "eps": _f(r.get("eps")), "revenue": _f(r.get("revenue")),
                    "net_income": _f(r.get("net_income")), "earnings_release_date": session})
    for m in sorted(set(stored) - seen):
        log.append({"action": "ROW_ABSENT_IGNORED", "quarter_end_date": _d(m)})
    parts = [p for p in (ex, pd.DataFrame(new_rows)) if len(p)]
    merged = pd.concat(parts, ignore_index=True) if parts else ex
    if len(merged):
        merged["quarter_end_date"] = pd.to_datetime(merged["quarter_end_date"])
        merged = merged.sort_values("quarter_end_date").reset_index(drop=True)
        if merged["quarter_end_date"].duplicated().any():
            raise ValueError("merge produced a duplicate quarter_end_date")
    return merged, log


def append_only_problems(before, after) -> list[str]:
    """Earlier rows survive unchanged; new rows are dated at first sight."""
    import pandas as pd
    problems = []
    key = "quarter_end_date"
    b = {pd.Timestamp(r[key]): r for r in _records(before)}
    a_recs = {pd.Timestamp(r[key]): r for r in _records(after)}
    for q, old in b.items():
        if q not in a_recs:
            problems.append(f"{q.date()}: stored row removed")
            continue
        new = a_recs[q]
        if canonical_json({k: new.get(k) for k in old}) != canonical_json(old):
            problems.append(f"{q.date()}: stored row changed")
        if any(not _is_missing(new[k]) for k in set(new) - set(old)):
            problems.append(f"{q.date()}: stored row gained non-null values")
    for q, r in a_recs.items():
        if q in b:
            continue
        rel, first, filed = (r.get("earnings_release_date"), r.get("first_seen"), r.get("sec_filing_date"))
        if _is_missing(first) or pd.Timestamp(rel) != pd.Timestamp(first):
            problems.append(f"{q.date()}: new row's earnings_release_date is not its first_seen session")
        if not _is_missing(filed) and pd.Timestamp(rel) < pd.Timestamp(filed):
            problems.append(f"{q.date()}: new row usable before its SEC filing")
    return problems


def _records(df):
    import pandas as pd
    if df is None or not len(df):
        return []
    out = []
    for r in df.to_dict("records"):
        out.append({k: (_d(v) if isinstance(v, (pd.Timestamp, datetime, date)) else v) for k, v in r.items()})
    return out


def write_partition_atomic(df, store_root, staging_root, ticker: str, schema=None) -> str:
    """Replace ticker=<T>/ with a single part-0.parquet (DESIGN.md 6.4).
    Never write_to_dataset (it appends uuid-named files). Built in a staging dir
    OUTSIDE the store root, fsynced, then swapped in by rename. -> SHA-256 of the file."""
    import uuid
    import pyarrow as pa
    import pyarrow.parquet as pq
    store_root, staging_root = Path(store_root), Path(staging_root)
    staging_root.mkdir(parents=True, exist_ok=True)
    store_root.mkdir(parents=True, exist_ok=True)
    nonce = uuid.uuid4().hex[:12]
    live = store_root / f"ticker={ticker}"
    new = staging_root / f"ticker={ticker}.new-{nonce}"
    old = staging_root / f"ticker={ticker}.old-{nonce}"
    new.mkdir()
    body = df.drop(columns=["ticker"], errors="ignore")
    table = pa.Table.from_pandas(body, preserve_index=False)
    if schema is not None:
        table = table.cast(schema)
    target = new / "part-0.parquet"
    pq.write_table(table, target)
    with open(target, "rb") as fh:
        os.fsync(fh.fileno())
    if live.exists():
        os.rename(live, old)
    os.rename(new, live)
    if old.exists():
        shutil.rmtree(old)
    return sha256_file(live / "part-0.parquet")


def recover_staging(store_root, staging_root) -> list[str]:
    """After a crash mid-swap: restore .old when the live partition is missing,
    drop leftover .new dirs. Runs at preflight."""
    store_root, staging_root = Path(store_root), Path(staging_root)
    actions = []
    if not staging_root.exists():
        return actions
    for p in sorted(staging_root.iterdir()):
        name, _, tag = p.name.rpartition(".")
        live = store_root / name
        if tag.startswith("old-"):
            if not live.exists():
                os.rename(p, live)
                actions.append(f"restored {name} from {p.name}")
            else:
                shutil.rmtree(p)
                actions.append(f"removed stale {p.name}")
        elif tag.startswith("new-"):
            shutil.rmtree(p)
            actions.append(f"removed unfinished {p.name}")
    return actions


def store_problems(store_root, eps_null_tickers=EPS_NULL_TICKERS) -> list[str]:
    """Mirror of kashif_engine.data.fingerprint.store_integrity() for any store
    root (that function hard-codes the backtest store; proposal P5). In the real
    run the frozen worktree's store_integrity() also runs on the synced copy."""
    import pandas as pd
    store_root = Path(store_root)
    problems = []
    for part in sorted(store_root.iterdir()):
        if not (part.is_dir() and part.name.startswith("ticker=")):
            problems.append(f"stray entry {part.name} in the store root")
            continue
        files = list(part.glob("*.parquet"))
        if len(files) != 1:
            problems.append(f"{part.name}: {len(files)} parquet files")
            continue
        df = pd.read_parquet(files[0])
        if df["quarter_end_date"].duplicated().any():
            problems.append(f"{part.name}: duplicate quarter_end_date")
        t = part.name.split("=", 1)[1]
        if t in eps_null_tickers and df["eps"].notna().any():
            problems.append(f"{t} has non-null EPS (XBRL_EPS_UNRELIABLE not applied)")
    return problems


# --------------------------------------------------------------------------
# arms.json (DESIGN.md 7)
# --------------------------------------------------------------------------
def load_arms(path=ARMS_FILE) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _tbd_paths(obj, path="") -> list[str]:
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not k.startswith("_"):
                out += _tbd_paths(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += _tbd_paths(v, f"{path}[{i}]")
    elif isinstance(obj, str) and "TBD" in obj:
        out.append(path)
    return out


def validate_arms(cfg: dict, require_frozen=False) -> list[str]:
    problems = []
    ids = [a.get("id") for a in cfg.get("arms", [])]
    if len(ids) != len(set(ids)):
        problems.append("duplicate arm ids")
    if cfg.get("primary_arm") not in ids:
        problems.append(f"primary_arm {cfg.get('primary_arm')!r} is not an arm")
    for a in cfg.get("arms", []):
        if a.get("inherits") is not None and a["inherits"] not in ids:
            problems.append(f"{a['id']}: inherits unknown arm {a['inherits']!r}")
        try:
            resolve_params(cfg, a["id"])
        except ValueError as e:
            problems.append(str(e))
    if require_frozen:
        if cfg.get("status") != "FROZEN":
            problems.append(f"status is {cfg.get('status')!r}, not FROZEN")
        problems += [f"TBD at {p}" for p in _tbd_paths(cfg)]
        for a in cfg.get("arms", []):
            if a.get("uncertain"):
                problems.append(f"{a['id']}: unresolved {a['uncertain']}")
            if not isinstance(a.get("enabled"), bool):
                problems.append(f"{a['id']}: enabled must be true/false")
    return problems


def resolve_params(cfg: dict, arm_id: str) -> dict:
    """Walk `inherits` from the root: B arms and C inherit every non-entry setting of A."""
    arms = {a["id"]: a for a in cfg.get("arms", [])}
    chain, cur = [], arm_id
    while cur is not None:
        if cur in chain:
            raise ValueError(f"inheritance cycle at {cur}")
        if cur not in arms:
            raise ValueError(f"unknown arm {cur!r}")
        chain.append(cur)
        cur = arms[cur].get("inherits")
    params = {}
    for a in reversed(chain):
        params.update(arms[a].get("params", {}))
    return params


def arms_sha256(path=ARMS_FILE) -> str:
    return sha256_file(path)


# --------------------------------------------------------------------------
# Environment, git (read-only helpers + a publish PLAN; running it is a stub)
# --------------------------------------------------------------------------
def env_versions() -> dict:
    from importlib import metadata
    out = {"python": sys.version.split()[0]}
    for pkg in ("pandas", "numpy", "pyarrow", "backtrader", "yfinance"):
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            out[pkg] = None
    return out


def git_head(root=ROOT):
    import subprocess
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True)
    return r.stdout.strip() or None


def git_publish_commands(paths, session: str, remote="origin") -> list[list[str]]:
    """The exact commands step 9 runs (DESIGN.md 4.5); -f because the repo root
    ignores *.jsonl. Only the listed paths are committed."""
    rel = [str(Path(p)) for p in paths]
    return [["git", "add", "-f", "--", *rel],
            ["git", "-c", "commit.gpgsign=false", "commit", "-m", f"exp3 {session}: journal + snapshot", "--", *rel],
            ["git", "push", remote, "HEAD"],
            ["git", "ls-remote", remote]]


def publish(paths, session):
    # TODO: run git_publish_commands() from a dedicated clone (never the shared
    # working tree), using the operator's existing credential helper (as
    # run_validation2.py does via `gh auth git-credential`); verify ls-remote
    # shows the commit. Store no credentials.
    raise NotImplementedError("git publish is a stub in the skeleton")


# --------------------------------------------------------------------------
# Network and replay stubs (signatures are the contract)
# --------------------------------------------------------------------------
def sec_user_agent() -> str:
    """The repo's existing SEC User-Agent (no credentials involved)."""
    from kashif_engine.catalyst.edgar import SEC_UA      # same string as merged_pipeline.SEC_UA
    return SEC_UA


def fetch_yahoo_bars(tickers, first_session: str, last_session: str):
    """-> long DataFrame (ticker, date, Open, High, Low, Close, AdjClose, Volume, Dividends, Splits).
    TODO: yfinance.download(symbols, start, end+1d, auto_adjust=False, actions=True,
    group_by="ticker", threads=True) in chunks of 40 with backoff, exactly as
    kashif_engine.data.prices.download does (symbol '.' -> '-'); never raise on
    one ticker: return what arrived and let validate_partition decide."""
    raise NotImplementedError("Yahoo fetch is a stub in the skeleton")


def fetch_genesis(tickers, start="2019-06-01", end=GENESIS_SESSION):
    """TODO: full history per ticker via fetch_yahoo_bars -> snapshot/genesis/<T>.parquet + MANIFEST.json."""
    raise NotImplementedError("genesis fetch is a stub in the skeleton")


@dataclass
class Filing:
    ticker: str
    cik: str
    accession: str
    form: str
    accepted_utc: str
    items: str


def poll_edgar(ciks: dict, known_accessions: set, since: str) -> list[Filing]:
    """TODO: GET https://data.sec.gov/submissions/CIK##########.json per CIK
    (headers={"User-Agent": sec_user_agent()}, <= 10 req/s, retry 403/429/5xx
    like edgar._get), UNCACHED (edgar.submissions() caches forever); return
    10-Q/10-K(/A, T), 8-K(/A), NT 10-Q/K filings accepted since `since` whose
    accession is not in known_accessions."""
    raise NotImplementedError("EDGAR poll is a stub in the skeleton")


def extract_ticker(ticker: str):
    """TODO: scaled_pipeline.process_ticker(ticker, *merged_pipeline.load_cached())
    then merged_pipeline.sanity_check(rows) -> DataFrame in the store's columns,
    earnings_release_date = SEC filing date. One companyfacts call."""
    raise NotImplementedError("SEC re-extraction is a stub in the skeleton")


@dataclass
class ReplayResult:
    arm: str
    start: str
    end: str
    run_dir: Path
    seconds: float


def replay_arm(arm_id: str, params: dict, session: str, worktree: Path, work_dir: Path) -> ReplayResult:
    """TODO: subprocess in the frozen worktree with PYTHONHASHSEED=0, TZ=UTC,
    KASHIF_KILL_SWITCH unset: load_strategy(config, params, US);
    prepare(frozen_universe, DAY1, session); engine.run(..., capital=100000,
    out_dir=work_dir/runs/<arm>); auditor.audit(run_dir). run_one is bypassed
    only because its experiment-1 holdout-lock check needs a gitignored file."""
    raise NotImplementedError("replay is a stub in the skeleton")


# --------------------------------------------------------------------------
# Dry run and CLI
# --------------------------------------------------------------------------
PLAN = (
    ("0 preflight: calendar, chain, worktree, env, kill-switch inputs, arms FROZEN", "REAL (partly)"),
    ("1 fetch Yahoo bars x2 (settle check), last 10 sessions", "STUB fetch_yahoo_bars"),
    ("2 validate partition (complete or nothing)", "REAL validate_partition"),
    ("3 corporate actions: split/dividend detection from the re-fetch", "REAL detect_splits"),
    ("4 write snapshot/bars/D.parquet once", "REAL write_partition_once"),
    ("5 EDGAR poll + per-ticker append-only store update + checks", "STUB poll/extract; REAL merge/write/checks"),
    ("6 materialize genesis-basis prices; replay every arm [Day1, D]", "REAL anchor_frame; STUB replay_arm"),
    ("7 divergence check vs every published session", "REAL compare_replay"),
    ("8 write log/D.jsonl (canonical, hash-chained)", "REAL render_day_file"),
    ("9 git add -f / commit / push / ls-remote", "PLAN git_publish_commands; STUB publish"),
)


def default_session(now=None) -> str:
    """Latest session whose close is at least 2.5 h old in New York."""
    from zoneinfo import ZoneInfo
    now = now or datetime.now(ZoneInfo("America/New_York"))
    d = now.date()
    if is_session(d):
        close_h = 13 if is_early_close(d) else 16
        if now.hour + now.minute / 60 >= close_h + 2.5:
            return d.isoformat()
    return previous_session(d)


def _demo_records(session: str, arms: list[str], equity: float) -> list[dict]:
    out = []
    for a in arms:
        out.append(make_record("arm_status", arm=a, session=session, state="ACTIVE",
                               replay={"start": DAY1, "end": session, "seconds": 0.0}))
        out.append(make_record("equity", arm=a, session=session, equity=equity, cash=equity, n_positions=0,
                               peak_equity=equity, drawdown=0.0))
    return out


def demo_chain(out_dir, sessions=(DAY1, "2026-09-29"), arms=("B1",)) -> list[str]:
    """Write a synthetic GENESIS.json + N day files into out_dir and verify the chain.
    Offline; exercises header/footer/canonical/chain code end to end."""
    out_dir = Path(out_dir)
    log_dir = out_dir / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    genesis = out_dir / "GENESIS.json"
    genesis.write_bytes((canonical_json({"schema": "exp3-genesis/1", "genesis_session": GENESIS_SESSION,
                                         "day1": DAY1, "demo": True}) + "\n").encode())
    prev_sha, prev_session = sha256_file(genesis), GENESIS_SESSION
    for i, s in enumerate(sessions, 1):
        header = build_header(s, prev_session, prev_sha, i, "0" * 40, "demo", {"demo": True}, "demo",
                              {"python": sys.version.split()[0]})
        data = render_day_file(header, _demo_records(s, list(arms), 100000.0), list(arms))
        (log_dir / f"{s}.jsonl").write_bytes(data)
        prev_sha, prev_session = sha256_bytes(data), s
    return verify_chain(log_dir, genesis)


def dry_run(session: str, arms_path=ARMS_FILE, demo_dir=None, out=print) -> int:
    out(f"exp3 run_day DRY RUN for session {session} (no network, nothing written"
        f"{'' if demo_dir is None else ' except the demo dir'})")
    try:
        sess = is_session(session)
    except ValueError as e:
        out(f"  calendar: {e}")
        return 2
    out(f"  calendar: is_session={sess} early_close={sess and is_early_close(session)} "
        f"prev={previous_session(session)} next={next_session(session)} (DRAFT table, verify vs nyse.com)")
    cfg = load_arms(arms_path)
    probs = validate_arms(cfg)
    frozen = validate_arms(cfg, require_frozen=True)
    out(f"  arms.json: status={cfg.get('status')} sha256={arms_sha256(arms_path)[:16]} "
        f"structure problems={len(probs)} freeze blockers={len(frozen)}")
    for p in probs + frozen:
        out(f"    - {p}")
    for a in cfg.get("arms", []):
        out(f"    {a['id']:<3} enabled={a.get('enabled')!s:<5} params={canonical_json(resolve_params(cfg, a['id']))}")
    out(f"  outputs for {session}: {LOG_DIR.relative_to(ROOT)}/{session}.jsonl, "
        f"{SNAP_DIR.relative_to(ROOT)}/bars/{session}.parquet, {STORE_LOG_DIR.relative_to(ROOT)}/{session}.jsonl")
    out("  plan:")
    for step, status in PLAN:
        out(f"    {step:<78} [{status}]")
    out(f"  env: {canonical_json(env_versions())}")
    if demo_dir:
        problems = demo_chain(demo_dir)
        out(f"  demo chain in {demo_dir}: {'OK' if not problems else problems}")
        if problems:
            return 1
    return 0


def live_run(session: str, arms_path=ARMS_FILE, out=print) -> int:
    cfg = load_arms(arms_path)
    blockers = validate_arms(cfg, require_frozen=True)
    if blockers:
        out("REFUSED: arms.json is not frozen:")
        for p in blockers:
            out(f"  - {p}")
        return 2
    if not is_session(session):
        out(f"NOT_A_SESSION {session}")
        return 0
    chain = verify_chain()
    if chain:
        out("REFUSED: journal chain does not verify:")
        for p in chain:
            out(f"  - {p}")
        return 2
    out(f"live run for {session}: the fetch, EDGAR, replay and publish steps are stubs in this skeleton")
    try:
        fetch_yahoo_bars([], previous_session(session), session)
    except NotImplementedError as e:
        out(f"STOPPED (nothing written): {e}")
        return 3
    return 3


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="run_day.py",
        description="Experiment 3 daily forward runner (SKELETON; virtual money only). See DESIGN.md.")
    ap.add_argument("--session", help="YYYY-MM-DD NYSE session (default: latest session closed >= 2.5 h ago, New York)")
    ap.add_argument("--dry-run", action="store_true", help="offline: validate config, print the plan; writes nothing")
    ap.add_argument("--demo-dir", help="with --dry-run: write and verify a synthetic 2-session chain in this directory")
    ap.add_argument("--verify-chain", action="store_true", help="verify log/*.jsonl against GENESIS.json and exit")
    ap.add_argument("--arms", default=str(ARMS_FILE), help="arms config (default: %(default)s)")
    a = ap.parse_args(argv)
    if a.verify_chain:
        problems = verify_chain()
        print("chain OK" if not problems else "\n".join(problems))
        return 0 if not problems else 1
    session = a.session or default_session()
    if a.dry_run:
        return dry_run(session, a.arms, a.demo_dir)
    if a.demo_dir:
        ap.error("--demo-dir needs --dry-run")
    return live_run(session, a.arms)


if __name__ == "__main__":
    sys.exit(main())
