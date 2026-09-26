"""Tests for the experiment-3 runner skeleton's real (pure) parts.

    python3 -m pytest -q paper_trading/exp3

Offline: no network, no price cache, no git state changes.
"""
import importlib
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import run_day as R  # noqa: E402


# ---------------------------------------------------------------- canonical JSON
def test_float_format_fixed_and_stripped():
    assert R.fmt_float(1.5) == "1.5"
    assert R.fmt_float(100.0) == "100"
    assert R.fmt_float(-0.0) == "0"
    assert R.fmt_float(-1e-12) == "0"
    assert R.fmt_float(0.1 + 0.2) == "0.3"
    assert R.fmt_float(123.456789014) == "123.45678901"
    with pytest.raises(ValueError):
        R.fmt_float(float("inf"))


def test_canonical_json_sorted_compact_typed():
    obj = {"b": 1, "a": [True, None, 2.50, float("nan")], "c": {"z": "é", "y": np.int64(3), "x": np.bool_(False)}}
    assert R.canonical_json(obj) == '{"a":[true,null,2.5,null],"b":1,"c":{"x":false,"y":3,"z":"é"}}'
    # same value, different key insertion order -> same text
    assert R.canonical_json({"x": 1, "y": 2}) == R.canonical_json({"y": 2, "x": 1})
    with pytest.raises(TypeError):
        R.canonical_json({"s": {"a", "b"}})
    with pytest.raises(TypeError):
        R.canonical_json({1: "non-str key"})


def test_canonical_round_trip_is_stable():
    for x in (0.1, 99_999_999.0 / 3, 12345678.12345678, 1e-9, -2.75):
        s = R.canonical_json({"v": x})
        assert R.canonical_json(json.loads(s)) == s


# ---------------------------------------------------------------- day files and chain
def _header(session, prev_session, prev_sha, seq):
    return R.build_header(session, prev_session, prev_sha, seq, "c" * 40, "a" * 64,
                          {"bars_content_sha256": "s"}, "st", {"python": "3.11"})


def _body(session, equity):
    return [R.make_record("equity", arm="B1", session=session, equity=equity, cash=equity, n_positions=0,
                          peak_equity=equity, drawdown=0.0),
            R.make_record("candidate", arm="B1", session=session, rank=2, ticker="ZZZ", decision="NO_CASH"),
            R.make_record("candidate", arm="B1", session=session, rank=1, ticker="AAA", decision="ORDER_SUBMITTED"),
            R.make_record("equity", arm="A", session=session, equity=equity, cash=equity, n_positions=0,
                          peak_equity=equity, drawdown=0.0)]


def test_render_parse_round_trip_and_order():
    data = R.render_day_file(_header("2026-09-28", "2026-09-25", "g", 1), _body("2026-09-28", 1e5), ["A", "B1"])
    header, body, footer, problems = R.parse_day_file(data)
    assert problems == []
    assert header["session"] == "2026-09-28" and footer["n_lines"] == 5
    assert [(r["arm"], r["record"], r.get("rank")) for r in body] == [
        ("A", "equity", None), ("B1", "candidate", 1), ("B1", "candidate", 2), ("B1", "equity", None)]
    assert data == R.render_day_file(_header("2026-09-28", "2026-09-25", "g", 1),
                                     list(reversed(_body("2026-09-28", 1e5))), ["A", "B1"])


def test_parse_detects_tampering_and_non_canonical_lines():
    data = R.render_day_file(_header("2026-09-28", "2026-09-25", "g", 1), _body("2026-09-28", 1e5), ["A", "B1"])
    tampered = data.replace(b'"equity":100000', b'"equity":100001', 1)
    assert any("body_sha256" in p for p in R.parse_day_file(tampered)[3])
    spaced = data.replace(b'{"arm":"A"', b'{"arm": "A"', 1)
    assert any("canonical" in p for p in R.parse_day_file(spaced)[3])
    assert any("newline" in p for p in R.parse_day_file(data[:-1])[3])


def test_render_rejects_record_from_another_session():
    with pytest.raises(ValueError):
        R.render_day_file(_header("2026-09-28", "2026-09-25", "g", 1), _body("2026-09-29", 1e5), ["A", "B1"])


def test_make_record_requires_fields():
    with pytest.raises(ValueError):
        R.make_record("fill", arm="A", session="2026-09-28", ticker="X")
    with pytest.raises(ValueError):
        R.make_record("not_a_type", arm="A")


def test_hash_chain_verifies_and_breaks(tmp_path):
    assert R.demo_chain(tmp_path, sessions=("2026-09-28", "2026-09-29", "2026-09-30"), arms=("A", "B1")) == []
    assert R.verify_chain(tmp_path / "log", tmp_path / "GENESIS.json") == []
    # Rewriting day 2 (even as a perfectly valid file) breaks day 3's link.
    d2 = tmp_path / "log" / "2026-09-29.jsonl"
    header, body, _, _ = R.parse_day_file(d2.read_bytes())
    body[0]["state"] = "INVALID"
    d2.write_bytes(R.render_day_file(header, body, ["A", "B1"]))
    problems = R.verify_chain(tmp_path / "log", tmp_path / "GENESIS.json")
    assert problems == ["2026-09-30.jsonl: prev_file_sha256 does not match the previous file (chain broken)"]
    # A changed genesis breaks day 1.
    (tmp_path / "GENESIS.json").write_text("{}\n")
    assert any(p.startswith("2026-09-28.jsonl: prev_file_sha256") for p in
               R.verify_chain(tmp_path / "log", tmp_path / "GENESIS.json"))


def test_chain_rejects_missing_genesis(tmp_path):
    R.demo_chain(tmp_path)
    (tmp_path / "GENESIS.json").unlink()
    assert R.verify_chain(tmp_path / "log", tmp_path / "GENESIS.json") == ["chain root GENESIS.json missing"]


# ---------------------------------------------------------------- divergence
def test_compare_replay_flags_only_the_changed_arm_session():
    pub = _body("2026-09-28", 1e5) + _body("2026-09-29", 1e5)
    rep = _body("2026-09-28", 1e5) + _body("2026-09-29", 1e5)
    assert R.compare_replay(pub, rep, ["2026-09-28", "2026-09-29"]) == []
    rep[-1] = dict(rep[-1], equity=99_000.0)                 # arm A, 09-29
    diff = R.compare_replay(pub, rep, ["2026-09-28", "2026-09-29"])
    assert [(d["arm"], d["session"]) for d in diff] == [("A", "2026-09-29")]
    assert '"equity":99000' in diff[0]["replayed_only"][0]
    assert R.compare_replay(pub, rep, ["2026-09-28"]) == []   # outside the compared sessions


def test_compare_ignores_non_compared_records():
    a = [R.make_record("arm_status", arm="A", session="2026-09-28", state="ACTIVE", replay={"seconds": 1.0})]
    b = [R.make_record("arm_status", arm="A", session="2026-09-28", state="ACTIVE", replay={"seconds": 9.0})]
    assert R.compare_replay(a, b, ["2026-09-28"]) == []


# ---------------------------------------------------------------- run dir -> records
def _run_dir(path, last):
    """Engine-style outputs for sessions 2026-09-28..`last` (a replay ending at `last`)."""
    days = [d for d in ("2026-09-28", "2026-09-29", "2026-09-30") if d <= last]
    path.mkdir(parents=True, exist_ok=True)
    eq = pd.DataFrame({"date": days, "equity": [100000.0, 100250.5, 99900.0][:len(days)],
                       "cash": [100000.0, 90250.5, 89900.0][:len(days)], "n_positions": [0, 1, 1][:len(days)]})
    eq.to_csv(path / "equity.csv", index=False)
    cands = pd.DataFrame([
        {"ticker": "AAA", "date": "2026-09-28", "rank_score": 0.9, "rs_pct": 97.0, "volume_ratio": 1.5,
         "vcp_quality": np.nan, "pivot": 20.0, "decision": "ORDER_SUBMITTED", "order_value": 10000.0,
         "catalyst": np.nan, "reason": "HIGH50_BREAKOUT"},
        {"ticker": "BBB", "date": "2026-09-28", "rank_score": 0.5, "rs_pct": 96.0, "volume_ratio": 1.3,
         "vcp_quality": np.nan, "pivot": 50.0, "decision": "QUEUED_INSUFFICIENT_SLOTS", "order_value": np.nan,
         "catalyst": np.nan, "reason": "HIGH50_BREAKOUT"}])
    cands.to_csv(path / "candidates.csv", index=False)
    fills = [{"date": "2026-09-29", "ticker": "AAA", "side": "BUY", "shares": 500.0, "price": 19.5,
              "commission": 2.5, "slippage": 1.5, "raw_shares": 500.0, "raw_price": 19.5, "reason": "ENTRY",
              "order_level": np.nan}]
    pd.DataFrame(fills if last >= "2026-09-29" else []).to_csv(path / "fills.csv", index=False)
    for name in ("dividends.csv", "trades.csv", "events.csv"):
        pd.DataFrame().to_csv(path / name, index=False)


def test_records_from_run_dir_and_prefix_property(tmp_path):
    _run_dir(tmp_path / "d2", "2026-09-29")
    _run_dir(tmp_path / "d3", "2026-09-30")
    r2 = R.records_from_run_dir(tmp_path / "d2", "B1")
    r3 = R.records_from_run_dir(tmp_path / "d3", "B1")
    kinds = sorted({r["record"] for r in r3})
    assert kinds == ["candidate", "equity", "fill", "order", "position"]
    order = [r for r in r3 if r["record"] == "order"][0]
    assert (order["ticker"], order["session"], order["for_session"]) == ("AAA", "2026-09-28", "2026-09-29")
    pos = [r for r in r3 if r["record"] == "position"]
    assert [(p["session"], p["shares_adj"], p["cost_adj"]) for p in pos] == [
        ("2026-09-29", 500.0, 9750.0), ("2026-09-30", 500.0, 9750.0)]
    eq = [r for r in r3 if r["record"] == "equity"]
    assert eq[-1]["peak_equity"] == 100250.5 and eq[-1]["drawdown"] < 0
    # The longer replay reproduces every earlier session exactly: no divergence.
    assert R.compare_replay(r2, r3, ["2026-09-28", "2026-09-29"]) == []


# ---------------------------------------------------------------- snapshot partitions
def _bars(session, tickers=("AAA", "BBB", "SPY")):
    rows = []
    for i, t in enumerate(tickers):
        rows.append({"ticker": t, "session": session, "open": 10.0 + i, "high": 11.0 + i, "low": 9.5 + i,
                     "close": 10.5 + i, "volume": 1e6, "adj_close": 10.5 + i, "dividends": 0.0, "splits": 0.0,
                     "status": "OK", "fetched_utc": "2026-09-28T22:30:00Z", "source": "yahoo"})
    return pd.DataFrame(rows)


def test_validate_partition():
    exp = ["AAA", "BBB", "SPY"]
    assert R.validate_partition(_bars("2026-09-28"), "2026-09-28", exp, must_have=["SPY"]) == []
    short = _bars("2026-09-28", ("AAA", "SPY"))
    assert any("unaccounted" in p for p in R.validate_partition(short, "2026-09-28", exp))
    bad = _bars("2026-09-28")
    bad.loc[0, "high"] = 5.0
    assert any("high/low" in p for p in R.validate_partition(bad, "2026-09-28", exp))
    assert any("rows dated" in p for p in R.validate_partition(_bars("2026-09-29"), "2026-09-28", exp))
    nobar = _bars("2026-09-28")
    nobar.loc[nobar["ticker"] == "SPY", ["open", "high", "low", "close"]] = np.nan
    nobar.loc[nobar["ticker"] == "SPY", "status"] = "NO_BAR"
    probs = R.validate_partition(nobar, "2026-09-28", exp, must_have=["SPY"])
    assert any("required names" in p for p in probs) and any("coverage" in p for p in probs)


def test_partition_is_write_once_and_hash_is_order_free(tmp_path):
    df = _bars("2026-09-28")
    path, sha = R.write_partition_once(df, tmp_path, "2026-09-28")
    assert path.exists() and sha == R.frame_content_sha256(df.iloc[::-1])
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        R.write_partition_once(_bars("2026-09-28", ("AAA",)), tmp_path, "2026-09-28")
    assert path.read_bytes() == before
    assert [p.name for p in (tmp_path / "bars").iterdir()] == ["2026-09-28.parquet"]   # no temp left behind
    assert len(pd.read_parquet(path)) == 3


def test_snapshot_chain_depends_on_every_partition():
    a = R.snapshot_chain_sha256("g", [("2026-09-28", "x"), ("2026-09-29", "y")])
    assert a == R.snapshot_chain_sha256("g", [("2026-09-29", "y"), ("2026-09-28", "x")])
    assert a != R.snapshot_chain_sha256("g", [("2026-09-28", "x"), ("2026-09-29", "z")])


# ---------------------------------------------------------------- genesis basis
def _genesis():
    idx = pd.bdate_range("2026-09-21", "2026-09-25")
    return pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0, "AdjClose": 98.0,
                         "Volume": 1e6, "Dividends": 0.0, "Splits": 0.0}, index=idx)


def _forward():
    idx = pd.to_datetime(["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01"])
    # raw as first fetched: a 2-for-1 split with ex-date 2026-09-30
    return pd.DataFrame({"Open": [100.0, 102.0, 51.0, 52.0], "High": [101.0, 103.0, 52.0, 53.0],
                         "Low": [99.0, 101.0, 50.0, 51.0], "Close": [100.0, 102.0, 51.5, 52.0],
                         "Volume": [1e6, 1e6, 2e6, 2e6], "Dividends": [0.0, 0.0, 0.0, 0.25],
                         "Splits": [0.0, 0.0, 2.0, 0.0]}, index=idx)


SPLIT = [{"ex_date": "2026-09-30", "ratio": 2.0, "first_seen": "2026-09-30"}]


def test_anchor_frame_is_continuous_across_a_split():
    f = R.anchor_frame(_genesis(), _forward(), SPLIT)
    assert list(f.columns) == R.PRICE_COLUMNS
    fwd = f.loc["2026-09-28":]
    assert list(fwd["Close"]) == [100.0, 102.0, 103.0, 104.0]          # raw x C(t)
    assert list(fwd["Volume"]) == [1e6, 1e6, 1e6, 1e6]                  # raw / C(t)
    assert list(fwd["Splits"]) == [0.0] * 4                             # add_raw_columns factor stays 1
    assert fwd.loc["2026-10-01", "Dividends"] == 0.5                    # per genesis-basis share
    # total-return chain: adj ratio == (close + div) / prev close
    adj = f["AdjClose"]
    assert adj.loc["2026-09-28"] == pytest.approx(98.0 * 100.0 / 100.0)
    assert adj.loc["2026-10-01"] / adj.loc["2026-09-30"] == pytest.approx((104.0 + 0.5) / 103.0)
    assert (f.loc[:"2026-09-25"] == _genesis()[R.PRICE_COLUMNS]).all().all()


def test_anchor_frame_invariance_when_later_split_is_appended():
    """The replay property: appending a split (and bars) never changes earlier rows."""
    early = R.anchor_frame(_genesis(), _forward().loc[:"2026-09-29"], [])
    late = R.anchor_frame(_genesis(), _forward(), SPLIT)
    pd.testing.assert_frame_equal(early, late.loc[:"2026-09-29"])


def test_anchor_frame_books_late_dividend_on_first_seen():
    late = [{"ex_date": "2026-09-29", "per_share_raw": 0.30, "first_seen": "2026-10-01"}]
    f = R.anchor_frame(_genesis(), _forward(), SPLIT, late_dividends=late)
    assert f.loc["2026-09-29", "Dividends"] == 0.0
    assert f.loc["2026-10-01", "Dividends"] == pytest.approx(0.5 + 0.30)   # ex-date pre-split: C(ex) = 1


def test_anchor_frame_rejects_pre_genesis_split_and_overlap():
    with pytest.raises(ValueError):
        R.anchor_frame(_genesis(), _forward(), [{"ex_date": "2026-09-24", "ratio": 2.0}])
    with pytest.raises(ValueError):
        R.anchor_frame(_genesis(), _genesis(), [])


def test_raw_reconstruction_matches_engine_convention():
    """engine: raw_shares = adj_shares / SplitFactor; journal: shares_raw = shares_adj x C(t)."""
    c = R.anchor_multiplier(_forward().index, SPLIT)
    assert list(c) == [1.0, 1.0, 2.0, 2.0]
    anchor_close = R.anchor_frame(_genesis(), _forward(), SPLIT).loc["2026-09-30", "Close"]
    assert anchor_close / c.loc["2026-09-30"] == _forward().loc["2026-09-30", "Close"]


# ---------------------------------------------------------------- split detection
FIRST = {"2026-09-24": 100.0, "2026-09-25": 102.0, "2026-09-28": 104.0}


def test_detect_no_split():
    assert R.detect_splits(FIRST, dict(FIRST), [], "2026-09-29") == []


def test_detect_split_on_its_ex_date():
    ref = {d: v / 2 for d, v in FIRST.items()}
    out = R.detect_splits(FIRST, ref, [], "2026-09-29")
    assert out == [{"kind": "SPLIT", "ex_date": "2026-09-29", "ratio": 2.0, "ratio_text": "2:1",
                    "late": False, "evidence": "refetch_ratio"}]


def test_detect_late_reverse_split_and_known_split():
    first = {"2026-09-24": 1.0, "2026-09-25": 1.1, "2026-09-28": 12.0}    # 1-for-10 took effect 09-28
    ref = {"2026-09-24": 10.0, "2026-09-25": 11.0, "2026-09-28": 12.0}
    out = R.detect_splits(first, ref, [], "2026-09-29")
    assert out[0]["kind"] == "SPLIT" and out[0]["ex_date"] == "2026-09-28" and out[0]["late"]
    assert out[0]["ratio_text"] == "1:10"
    known = [{"ex_date": "2026-09-28", "ratio": 0.1}]
    assert R.detect_splits(first, ref, known, "2026-09-29") == []


def test_detect_unexplained_revision():
    ref = dict(FIRST, **{"2026-09-25": 97.0})
    assert R.detect_splits(FIRST, ref, [], "2026-09-29")[0]["kind"] == "UNEXPLAINED"


# ---------------------------------------------------------------- fundamentals store
def _stored():
    return pd.DataFrame({
        "fiscal_quarter": ["Q1 2026", "Q2 2026"],
        "quarter_end_date": pd.to_datetime(["2026-03-31", "2026-06-30"]),
        "revenue": [100.0, 110.0], "net_income": [10.0, 12.0], "eps": [0.50, 0.60],
        "earnings_release_date": pd.to_datetime(["2026-04-28", "2026-07-28"]),
        "sec_filing_date": pd.to_datetime(["2026-05-01", "2026-08-01"]),
        "release_date_source": ["8-K 2.02", "8-K 2.02"],
        "first_seen": pd.to_datetime([None, None]), "accession": [None, None]})


def _extracted():
    return pd.DataFrame({
        "fiscal_quarter": ["Q1 2026", "Q2 2026", "Q3 2026"],
        "quarter_end_date": pd.to_datetime(["2026-03-31", "2026-06-29", "2026-09-30"]),   # 06-29: 52/53-week drift
        "revenue": [100.0, 111.0, 120.0], "net_income": [10.0, 12.0, 15.0], "eps": [0.50, 0.60, 0.75],
        "earnings_release_date": pd.to_datetime(["2026-05-01", "2026-08-01", "2026-10-30"])})


def test_merge_appends_new_quarter_dated_at_first_sight():
    merged, log = R.merge_ticker_partition(_stored(), _extracted(), "2026-11-02", accession="0000000000-26-000001")
    assert len(merged) == 3
    new = merged.iloc[-1]
    assert new["earnings_release_date"] == pd.Timestamp("2026-11-02") == new["first_seen"]
    assert new["sec_filing_date"] == pd.Timestamp("2026-10-30")
    assert new["release_date_source"] == "FORWARD_FIRST_SEEN"
    actions = [e["action"] for e in log]
    assert actions == ["REVISION_IGNORED", "ADD_QUARTER"]
    assert log[0]["diffs"] == {"revenue": [110.0, 111.0]}
    assert merged.iloc[1]["revenue"] == 110.0                       # the stored value wins
    assert R.append_only_problems(_stored(), merged) == []


def test_merge_refuses_future_filing_and_logs_absent_rows():
    with pytest.raises(ValueError):
        R.merge_ticker_partition(_stored(), _extracted(), "2026-10-29")
    merged, log = R.merge_ticker_partition(_stored(), _extracted().iloc[:1], "2026-11-02")
    assert [e["action"] for e in log] == ["ROW_ABSENT_IGNORED"] and len(merged) == 2


def test_append_only_problems_catch_rewrites():
    after = _stored()
    after.loc[0, "eps"] = 0.55
    assert R.append_only_problems(_stored(), after) == ["2026-03-31: stored row changed"]
    merged, _ = R.merge_ticker_partition(_stored(), _extracted(), "2026-11-02")
    merged.loc[2, "earnings_release_date"] = pd.Timestamp("2026-10-15")      # backdated
    assert any("first_seen" in p for p in R.append_only_problems(_stored(), merged))


def test_atomic_partition_write_and_store_checks(tmp_path):
    store, staging = tmp_path / "store", tmp_path / "staging"
    R.write_partition_atomic(_stored(), store, staging, "AAA")
    merged, _ = R.merge_ticker_partition(_stored(), _extracted(), "2026-11-02")
    sha = R.write_partition_atomic(merged, store, staging, "AAA")
    files = list((store / "ticker=AAA").glob("*.parquet"))
    assert [f.name for f in files] == ["part-0.parquet"] and sha == R.sha256_file(files[0])
    assert list(staging.iterdir()) == []
    assert "ticker" not in pq.read_schema(files[0]).names                 # partition column lives in the dir name
    assert len(pq.read_table(str(store)).to_pandas()) == 3               # dataset discovery sees one version
    assert R.store_problems(store) == []
    # write_to_dataset-style leftovers (a second file) are caught
    (store / "ticker=AAA" / "f00-0.parquet").write_bytes(files[0].read_bytes())
    assert R.store_problems(store) == ["ticker=AAA: 2 parquet files"]


def test_store_checks_fizz_eps_must_be_null(tmp_path):
    R.write_partition_atomic(_stored(), tmp_path / "store", tmp_path / "stg", "FIZZ")
    assert R.store_problems(tmp_path / "store") == ["FIZZ has non-null EPS (XBRL_EPS_UNRELIABLE not applied)"]


def test_recover_staging_after_crash_mid_swap(tmp_path):
    store, staging = tmp_path / "store", tmp_path / "staging"
    R.write_partition_atomic(_stored(), store, staging, "BRK.B")
    # crash after "rename live -> .old", before ".new -> live"
    os.rename(store / "ticker=BRK.B", staging / "ticker=BRK.B.old-abc")
    (staging / "ticker=BRK.B.new-abc").mkdir()
    actions = R.recover_staging(store, staging)
    assert sorted(actions) == ["removed unfinished ticker=BRK.B.new-abc", "restored ticker=BRK.B from ticker=BRK.B.old-abc"]
    assert (store / "ticker=BRK.B" / "part-0.parquet").exists() and list(staging.iterdir()) == []


# ---------------------------------------------------------------- calendar
def test_calendar_draft():
    assert R.is_session("2026-09-28") and not R.is_session("2026-09-26")
    assert not R.is_session("2026-11-26") and R.is_early_close("2026-11-27")
    assert R.previous_session("2026-09-28") == "2026-09-25"
    assert R.next_session("2026-11-25") == "2026-11-27"
    assert R.next_session("2026-12-31") == "2027-01-04"
    assert R.sessions_between("2026-09-24", "2026-09-30") == [
        "2026-09-24", "2026-09-25", "2026-09-28", "2026-09-29", "2026-09-30"]
    with pytest.raises(ValueError):
        R.is_session("2028-01-03")


def test_default_session_waits_for_the_close():
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    assert R.default_session(pd.Timestamp("2026-09-28 17:00", tz=ny).to_pydatetime()) == "2026-09-25"
    assert R.default_session(pd.Timestamp("2026-09-28 18:31", tz=ny).to_pydatetime()) == "2026-09-28"
    assert R.default_session(pd.Timestamp("2026-11-27 15:31", tz=ny).to_pydatetime()) == "2026-11-27"


# ---------------------------------------------------------------- arms.json
def test_shipped_arms_json_is_consistent():
    cfg = R.load_arms()
    assert R.validate_arms(cfg) == []
    assert cfg["primary_arm"] == "B1" and cfg["status"] in ("DRAFT", "FROZEN")
    blockers = R.validate_arms(cfg, require_frozen=True)
    if cfg["status"] == "DRAFT":
        assert "status is 'DRAFT', not FROZEN" in blockers and any(b.startswith("TBD at") for b in blockers)
    else:
        assert blockers == []
    b3 = R.resolve_params(cfg, "B3")
    # B3 = B2 + H5 = B1 + H3 + H5, with every non-entry setting from A
    assert b3["early_path"] is True and b3["rs_threshold"] == 95
    assert (b3["stop_max_pct"], b3["max_positions"], b3["defensive_mode"]) == (0.10, 4, "off")
    c = R.resolve_params(cfg, "C")
    assert c["use_catalyst"] is True and "early_path" not in c


def test_arms_validation_catches_structure_errors():
    cfg = {"primary_arm": "X", "status": "FROZEN", "arms": [
        {"id": "A", "inherits": "B", "params": {}, "enabled": True, "uncertain": []},
        {"id": "B", "inherits": "A", "params": {}, "enabled": True, "uncertain": []}]}
    probs = R.validate_arms(cfg, require_frozen=True)
    assert any("primary_arm" in p for p in probs) and any("cycle" in p for p in probs)


# ---------------------------------------------------------------- CLI and hygiene
def test_git_publish_plan_is_scoped_and_forced():
    cmds = R.git_publish_commands(["paper_trading/exp3/log/2026-09-28.jsonl"], "2026-09-28")
    assert cmds[0] == ["git", "add", "-f", "--", "paper_trading/exp3/log/2026-09-28.jsonl"]
    assert cmds[1][-2:] == ["--", "paper_trading/exp3/log/2026-09-28.jsonl"] and cmds[2][:2] == ["git", "push"]
    with pytest.raises(NotImplementedError):
        R.publish([], "2026-09-28")


def test_dry_run_and_help_are_offline(tmp_path, capsys):
    assert R.main(["--dry-run", "--session", "2026-09-28"]) == 0
    assert R.main(["--dry-run", "--session", "2026-09-28", "--demo-dir", str(tmp_path / "demo")]) == 0
    assert "demo chain" in capsys.readouterr().out
    draft = dict(R.load_arms(), status="DRAFT")
    (tmp_path / "arms.json").write_text(json.dumps(draft))
    assert R.main(["--session", "2026-09-28", "--arms", str(tmp_path / "arms.json")]) == 2   # refuses a DRAFT
    with pytest.raises(SystemExit) as e:
        R.main(["--help"])
    assert e.value.code == 0


def test_stubs_raise_not_implemented():
    for fn, args in ((R.fetch_yahoo_bars, ([], "2026-09-25", "2026-09-28")), (R.fetch_genesis, ([],)),
                     (R.poll_edgar, ({}, set(), "2026-09-24")), (R.extract_ticker, ("AAA",)),
                     (R.replay_arm, ("B1", {}, "2026-09-28", Path("."), Path(".")))):
        with pytest.raises(NotImplementedError):
            fn(*args)


def test_import_has_no_side_effects():
    before = sorted(p.name for p in HERE.iterdir())
    importlib.reload(R)
    assert sorted(p.name for p in HERE.iterdir()) == before
    src = (HERE / "run_day.py").read_text()
    for banned in ("alpaca", "ib_insync", "ibapi", "api_key", "API_KEY", "secret", "password", "token="):
        assert banned not in src, banned
