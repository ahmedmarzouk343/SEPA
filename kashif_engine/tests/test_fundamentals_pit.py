"""Point-in-time fundamentals adapter: known answers and lookahead guards.

Expected NVDA numbers are NVIDIA's published GAAP diluted EPS (as filed,
before the 2024 10-for-1 split):
    Q2 FY2023 (Jul 2022)  $0.26        Q2 FY2024 (Jul 2023)  $2.48  -> +854%
    Q1 FY2024 (Apr 2023)  $0.82 vs Q1 FY2023 $0.64                  -> +28%
    FY2023 annual $1.74 vs FY2022 $3.85 (annual EPS FELL)
Q2 FY2024 was released 2023-08-23 (10-Q filed 2023-08-28 per EDGAR; the
store's release date is used either way).
"""
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kashif_engine.data import fundamentals as F  # noqa: E402
from kashif_engine.markets import US  # noqa: E402
from fundamentals_store import get_known_history  # noqa: E402


def _release_of(ticker, label):
    h = get_known_history(ticker, date(2030, 1, 1))
    r = h[h["fiscal_quarter"] == label]
    assert len(r) == 1, f"{ticker} {label} missing from store"
    return r.iloc[0]["earnings_release_date"]


def test_nvda_growth_and_acceleration_flag_in_2023():
    s = F.screen("NVDA", date(2023, 10, 2), US)
    snap = s["snapshot"]
    assert snap["latest_quarter"] == "Q2 2024"
    g = snap["eps_yoy_growth_by_quarter"]
    assert g[-1] == pytest.approx((2.48 - 0.26) / 0.26, rel=0.02)          # +854%
    q = s["detail"]
    assert q["q1"]["status"] == "PASS"                                       # EPS growth >= 20%
    assert q["q2"]["status"] == "PASS"                                       # 2q-avg acceleration


def test_nvda_full_screen_blocked_by_annual_eps_until_fy2024_known():
    s = F.screen("NVDA", date(2023, 10, 2), US)
    assert s["verdict"] == "FAIL"
    assert s["detail"]["q4"]["status"] == "FAIL"                             # FY23 1.74 < FY22 3.85
    fy24_release = _release_of("NVDA", "Q4 2024")
    after = F.screen("NVDA", fy24_release + timedelta(days=2), US)
    assert after["detail"]["q4"]["status"] == "PASS"
    assert after["verdict"] == "PASS"


def test_release_day_is_not_known_until_next_day():
    r = _release_of("NVDA", "Q2 2024")
    on_day = F.snapshot("NVDA", r, US)
    next_day = F.snapshot("NVDA", r + timedelta(days=1), US)
    assert on_day["latest_quarter"] != "Q2 2024"
    assert next_day["latest_quarter"] == "Q2 2024"


def test_split_does_not_change_growth():
    before = F.snapshot("NVDA", date(2024, 6, 6), US)
    after = F.snapshot("NVDA", date(2024, 6, 12), US)      # 10-for-1 effective 2024-06-07
    assert before["latest_quarter"] == after["latest_quarter"]
    assert after["latest_eps"] == pytest.approx(before["latest_eps"] / 10)
    assert after["eps_yoy_growth_by_quarter"] == pytest.approx(before["eps_yoy_growth_by_quarter"])


def test_reverse_split_multiplies_eps():
    # NLY 1-for-4 reverse split effective 2022-09-23
    before = F.snapshot("NLY", date(2022, 9, 20), US)
    after = F.snapshot("NLY", date(2022, 9, 26), US)
    assert before["latest_quarter"] == after["latest_quarter"]
    if before["latest_eps"] is not None:
        assert after["latest_eps"] == pytest.approx(before["latest_eps"] * 4)


def test_stale_latest_row_is_skipped():
    r = _release_of("NVDA", "Q2 2024")
    # Pretend no later release existed: check the rule directly on the arithmetic.
    s = F.screen("NVDA", r + timedelta(days=1), US)
    assert s["snapshot"]["stale"] is False
    # A ticker whose data stops: pick the store's last release for NVDA and go 200 days past it.
    last = get_known_history("NVDA", date(2030, 1, 1)).iloc[-1]["earnings_release_date"]
    far = F.screen("NVDA", last + timedelta(days=F.STALE_DAYS + 5), US)
    assert far["verdict"] == "SKIP" and far["reason"].startswith("STALE")


def test_no_data_before_first_release_is_skip_not_crash():
    # The day before the store's FIRST release (it moved from 2020 to 2014
    # when the history was back-filled, so no fixed date can stand in).
    first = get_known_history("NVDA", date(2030, 1, 1)).iloc[0]["earnings_release_date"]
    s = F.screen("NVDA", first - timedelta(days=5), US)
    assert s["verdict"] == "SKIP" and s["reason"] == "NO_FUNDAMENTALS"


@pytest.mark.parametrize("seed", [1, 2])
def test_event_date_carry_forward_equals_direct_evaluation(seed):
    """daily_verdicts evaluates only at event dates; re-check random days directly."""
    rnd = random.Random(seed)
    tickers = ["NVDA", "AAPL", "CELH", "SMCI", "GME", "NLY", "TTEK", "WMT", "AAON", "ACMR"]
    days = pd.bdate_range("2022-01-03", "2025-12-31")
    for t in rnd.sample(tickers, 5):
        v = F.daily_verdicts(t, days, US)
        for d in rnd.sample(list(days), 25):
            direct = F.screen(t, d.date(), US)
            assert v.at[d, "fund_verdict"] == direct["verdict"], (t, d, direct["reason"])
