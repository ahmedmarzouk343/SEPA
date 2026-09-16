"""
Known-answer regression test for Feature 6 (Catalyst Check): catalyst_check.py.

Tests: LOW-priority routing, scoring window, reporting basis conflict rule,
debunked rumor rule, track record append-only logging, pipeline_blocks_entry.
"""

import json
import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import catalyst_check as cc  # noqa: E402

REF_DATE = date(2026, 8, 26)
SCRATCH_TRACK_RECORD_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "scratch_track_record_fixture5.jsonl"
)


@pytest.fixture(autouse=True)
def _restore_score_with_model():
    real = cc.score_with_model
    yield
    cc.score_with_model = real


@pytest.fixture(autouse=True)
def _protect_track_record():
    path = cc.TRACK_RECORD_PATH
    snapshot = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            snapshot = f.readlines()
    yield
    if snapshot is None:
        if os.path.exists(path):
            os.remove(path)
    else:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(snapshot)


def _make_spy():
    real = cc.score_with_model
    counter = {"n": 0}

    def spy(*args, **kwargs):
        counter["n"] += 1
        return real(*args, **kwargs)

    return spy, counter


def test_fixture1_low_priority_routing():
    spy, counter = _make_spy()
    cc.score_with_model = spy
    result = cc.catalyst_check(
        "COMI",
        disclosures=[{"date": "2026-08-20", "category": "Trading", "title": "Routine trading notice"}],
        news_result={"articles": [], "arabic_search_skipped": False, "english_count": 0, "arabic_count": 0},
        pipeline_run_id="fixture1",
        reference_date=REF_DATE,
    )
    assert result["score"] == "NEUTRAL"
    assert result["source"] == "auto_low_priority"
    assert result["priority_tier"] == "LOW"
    assert result["pending_model_review"] is False
    assert counter["n"] == 0


def test_fixture2_scoring_window():
    date_95_ago = (REF_DATE - timedelta(days=95)).isoformat()
    date_89_ago = (REF_DATE - timedelta(days=89)).isoformat()
    assert cc._within_window(date_95_ago, 90, reference_date=REF_DATE) is False
    assert cc._within_window(date_89_ago, 90, reference_date=REF_DATE) is True


def test_fixture3_reporting_basis_conflict_direct():
    article_a = {"title": "Company reports standalone profit down",
                 "basis_mentions": [{"basis": "standalone", "direction": "down"}]}
    article_b = {"title": "Consolidated profit rises sharply",
                 "basis_mentions": [{"basis": "consolidated", "direction": "up"}]}
    result = cc.apply_reporting_basis_conflict_rule([article_a, article_b])
    assert result["conflict"] is True
    assert result["standalone_direction"] == "down"
    assert result["consolidated_direction"] == "up"


def test_fixture3_reporting_basis_conflict_orchestrator():
    spy, counter = _make_spy()
    cc.score_with_model = spy
    article_a = {"title": "Company reports standalone profit down",
                 "basis_mentions": [{"basis": "standalone", "direction": "down"}]}
    article_b = {"title": "Consolidated profit rises sharply",
                 "basis_mentions": [{"basis": "consolidated", "direction": "up"}]}
    result = cc.catalyst_check(
        "EAST",
        disclosures=[{"date": "2026-08-17", "category": "FinancialResults", "title": "H1 results"}],
        news_result={"articles": [article_a, article_b], "arabic_search_skipped": False,
                     "english_count": 1, "arabic_count": 1},
        pipeline_run_id="fixture3",
        reference_date=REF_DATE,
    )
    assert result["score"] == "NEUTRAL"
    assert result["source"] == "reporting_basis_conflict_rule"
    assert counter["n"] == 0


def test_fixture4_debunked_rumor_direct():
    article = {
        "title": "Company reducing operations in America",
        "content": "The company officially denied the rumor about reducing operations, calling it inaccurate.",
    }
    result = cc.apply_debunked_rumor_rule([article])
    assert result["debunked"] is True
    assert len(result["debunked_articles"]) == 1


def test_fixture4_debunked_rumor_orchestrator():
    spy, counter = _make_spy()
    cc.score_with_model = spy
    article = {
        "title": "Company reducing operations in America",
        "content": "The company officially denied the rumor about reducing operations, calling it inaccurate.",
    }
    result = cc.catalyst_check(
        "ORWE",
        disclosures=[{"date": "2026-08-12", "category": "Corporate", "title": "Company statement"}],
        news_result={"articles": [article], "arabic_search_skipped": False,
                     "english_count": 1, "arabic_count": 0},
        pipeline_run_id="fixture4",
        reference_date=REF_DATE,
    )
    assert result["score"] == "NEUTRAL"
    assert result["source"] == "debunked_rumor_rule"
    assert counter["n"] == 0


def test_fixture5_track_record_append_only():
    if os.path.exists(SCRATCH_TRACK_RECORD_PATH):
        os.remove(SCRATCH_TRACK_RECORD_PATH)

    cc.log_to_track_record("COMI", "2026-08-20", "STRONG_POSITIVE", "BigGo Finance",
                           "CBE approval for digital bank", pipeline_run_id="run1",
                           path=SCRATCH_TRACK_RECORD_PATH)
    with open(SCRATCH_TRACK_RECORD_PATH, encoding="utf-8") as f:
        lines1 = f.readlines()
    assert len(lines1) == 2
    assert lines1[0].startswith("#")

    cc.log_to_track_record("TMGH", "2026-08-12", "STRONG_POSITIVE", "Daily News Egypt",
                           "H1 net profit +23% YoY", pipeline_run_id="run2",
                           path=SCRATCH_TRACK_RECORD_PATH)
    with open(SCRATCH_TRACK_RECORD_PATH, encoding="utf-8") as f:
        lines2 = f.readlines()
    assert len(lines2) == 3
    assert lines2[0] == lines1[0]

    record1 = json.loads(lines2[1])
    record2 = json.loads(lines2[2])
    assert record1["ticker"] == "COMI"
    assert record2["ticker"] == "TMGH"
    for field in ("forward_return_10d", "forward_return_20d", "forward_return_60d"):
        assert record1[field] is None

    os.remove(SCRATCH_TRACK_RECORD_PATH)


def test_fixture6_pipeline_blocks_entry():
    assert cc.compute_pipeline_blocks_entry("STRONG_POSITIVE") is False
    assert cc.compute_pipeline_blocks_entry("NEUTRAL") is False
    assert cc.compute_pipeline_blocks_entry("STRONG_NEGATIVE") is True
