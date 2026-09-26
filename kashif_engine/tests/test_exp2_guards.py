"""Guards from the Amendment-3 code review: the one-shot validation window,
the history-break table and break event dates."""
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kashif_engine import experiment2 as X  # noqa: E402
from kashif_engine.data import price_corrections as PC  # noqa: E402


def test_validation_window_needs_the_live_lock_nonce(tmp_path, monkeypatch):
    lock = tmp_path / "VALIDATION_LOCK"
    monkeypatch.setattr(X, "LOCK", lock)
    X.assert_window_allowed("2022-01-03", "2026-09-24")                 # dev window: always fine
    with pytest.raises(PermissionError):
        X.assert_window_allowed("2017-01-03", "2021-12-31")             # no lock
    with pytest.raises(PermissionError):
        X.assert_window_allowed("2017-01-03", "2021-12-31", True)       # a bare flag is not a token
    lock.write_text(json.dumps({"nonce": "abc"}))
    with pytest.raises(PermissionError):
        X.assert_window_allowed("2017-01-03", "2021-12-31", "wrong")
    X.assert_window_allowed("2017-01-03", "2021-12-31", "abc")          # the runner's own nonce
    lock.write_text(json.dumps({"nonce": "abc", "finished_utc": "x"}))
    with pytest.raises(PermissionError):
        X.assert_window_allowed("2019-01-02", "2019-06-28", "abc")      # finished: never again


def test_run_one_refuses_the_window_without_a_token():
    from kashif_engine.run_backtest import run_one
    with pytest.raises(PermissionError):
        run_one("2018-01-02", "2018-03-30", allow_validation2=True, do_audit=False)


def test_history_break_table_fails_loudly(tmp_path, monkeypatch):
    bad = tmp_path / "b.csv"
    for body in ("ticker,date,kind,evidence,note\nAA,,price_cut,x,\n",            # blank date
                 "ticker,date,kind,evidence,note\n,2020-01-02,price_cut,x,\n",    # blank ticker
                 "ticker,date,kind,evidence,note\nAA,2020-01-02,price_cut,x,\nAA,2020-01-02,price_cut,y,\n"):
        bad.write_text(body)
        monkeypatch.setattr(PC, "BREAKS_FILE", bad)
        monkeypatch.setattr(PC, "_breaks", None)
        with pytest.raises(Exception):
            PC.history_breaks()
    monkeypatch.setattr(PC, "BREAKS_FILE", tmp_path / "missing.csv")
    monkeypatch.setattr(PC, "_breaks", None)
    with pytest.raises(FileNotFoundError):
        PC.history_breaks()


def test_bad_bar_may_not_swallow_a_split(monkeypatch):
    idx = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"])
    df = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "AdjClose": 1.0, "Volume": 1.0,
                       "Dividends": 0.0, "Splits": [0.0, 2.0, 0.0]}, index=idx)
    monkeypatch.setattr(PC, "_breaks", [{"ticker": "ZZZ", "date": "2020-01-03", "kind": "bad_bar"}])
    with pytest.raises(ValueError):
        PC.apply("ZZZ", df)
    monkeypatch.setattr(PC, "_breaks", [{"ticker": "ZZZ", "date": "2020-01-06", "kind": "bad_bar"}])
    assert len(PC.apply("ZZZ", df)) == 2


def test_fundamentals_break_is_an_event_date(monkeypatch):
    from kashif_engine.data import fundamentals as F
    from kashif_engine.markets import US
    monkeypatch.setattr(PC, "_breaks", [{"ticker": "AAON", "date": "2024-01-10", "kind": "fundamentals_break"}])
    ev = F.event_dates("AAON", date(2023, 6, 1), date(2024, 6, 1), US)
    assert date(2024, 1, 10) in ev
    days = pd.bdate_range("2023-06-01", "2024-06-01")
    v = F.daily_verdicts("AAON", days, US)
    assert v.loc["2024-01-10", "fund_verdict"] == F.screen("AAON", date(2024, 1, 10), US)["verdict"]
