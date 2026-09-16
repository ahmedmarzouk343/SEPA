"""
backfill_catalyst_returns.py -- Feature 6, Stage D backfill.

Separate script, NOT run during the main pipeline (avoids lookahead bias --
the main pipeline must never look up future prices). Reads
catalyst_track_record.jsonl, looks up the close price at score_date +
10/20/60 trading days via yfinance (SYMBOL.CA format, same fetch pattern as
trend_template_test.py) using pandas BDay offsets (business-day arithmetic,
not calendar-day arithmetic), and writes the forward_return_* fields back
into each record.

Run this periodically (e.g. at each graduation_criteria checkpoint, per
feature-06-catalyst-check-rules.md Section 6) once enough calendar time has
passed for the later forward-return windows to have real data.

--------------------------------------------------------------------------
HOW "REWRITE" IS DONE SAFELY ON AN APPEND-ONLY FILE
--------------------------------------------------------------------------
catalyst_check.py's log_to_track_record() is append-only by design (never
overwrites -- protects against losing history on a crash mid-write). This
script's job is specifically to ADD data to existing lines, which means it
must read the whole file, update matching records in memory, and write a
new file -- that is not the same thing as the main pipeline "overwriting"
history; it is a deliberate, explicit, periodic maintenance step, run by a
human/cron, never invoked implicitly by catalyst_check() itself. The
original header comment is preserved. Written atomically (temp file + os
.replace) so a crash mid-write cannot corrupt the track record.
--------------------------------------------------------------------------
"""

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta

import yfinance as yf
from pandas.tseries.offsets import BDay

TRACK_RECORD_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalyst_track_record.jsonl")
FORWARD_RETURN_DAYS = [10, 20, 60]
HEADER_PREFIX = "#"


def load_track_record(path=TRACK_RECORD_PATH):
    """
    Returns (header_lines, records) -- header_lines are any leading lines
    starting with "#" (preserved verbatim on write-back), records are the
    parsed JSON objects. Skips blank lines. Malformed JSON lines are kept
    as raw strings in a third list (returned separately) so a corrupt line
    doesn't silently vanish -- surfaced to the caller instead.
    """
    header_lines = []
    records = []
    malformed = []
    if not os.path.exists(path):
        return header_lines, records, malformed

    with open(path, encoding="utf-8") as f:
        seen_json = False
        for line in f:
            stripped = line.rstrip("\n")
            if not stripped:
                continue
            if stripped.startswith(HEADER_PREFIX) and not seen_json:
                header_lines.append(stripped)
                continue
            try:
                records.append(json.loads(stripped))
                seen_json = True
            except json.JSONDecodeError:
                malformed.append(stripped)
    return header_lines, records, malformed


def _fetch_close_on_or_after(symbol, target_date, search_window_days=10):
    """
    yfinance daily bars don't include weekends/holidays, so "score_date + N
    calendar days" often lands on a non-trading day. Looks up the close on
    the FIRST trading day on or after target_date, searching up to
    `search_window_days` forward. Returns None if no data is found (ticker
    delisted, too-recent date with no bars yet, etc.) -- never raises.
    """
    try:
        t = yf.Ticker(symbol)
        start = target_date
        end = target_date + timedelta(days=search_window_days)
        hist = t.history(start=start.isoformat(), end=end.isoformat(), interval="1d")
    except Exception:  # noqa: BLE001 -- network/ticker errors must not crash the backfill run
        return None
    if hist.empty:
        return None
    return float(hist["Close"].iloc[0])


def compute_forward_returns(ticker, score_date_str, forward_return_days=None):
    """
    ticker: bare ticker (e.g. "COMI") -- ".CA" appended here for yfinance,
    same convention as trend_template_test.py's fetch_data().
    score_date_str: "YYYY-MM-DD".
    Returns {f"forward_return_{d}d": float or None, ...} -- None for any
    window that can't be computed yet (not enough time has passed) or
    where price data is unavailable.
    """
    if forward_return_days is None:
        forward_return_days = FORWARD_RETURN_DAYS

    symbol = f"{ticker.replace('.CA', '').replace('.ca', '')}.CA"
    score_date = datetime.strptime(score_date_str, "%Y-%m-%d").date()

    base_close = _fetch_close_on_or_after(symbol, score_date)
    results = {}
    today = datetime.now().date()

    for days in forward_return_days:
        field = f"forward_return_{days}d"
        target_date = (score_date + BDay(days)).date()
        if target_date > today:
            # Not enough time has elapsed yet -- honestly None, not a guess.
            results[field] = None
            continue
        if base_close is None:
            results[field] = None
            continue
        future_close = _fetch_close_on_or_after(symbol, target_date)
        if future_close is None:
            results[field] = None
            continue
        results[field] = (future_close - base_close) / base_close

    return results


def backfill(path=TRACK_RECORD_PATH, forward_return_days=None, dry_run=False):
    """
    Reads the track record, computes any missing forward_return_* fields
    (leaves already-populated fields untouched -- never overwrites a real
    computed value with a fresh lookup), and writes the file back
    atomically. Returns (updated_count, skipped_count, malformed_count).
    """
    if forward_return_days is None:
        forward_return_days = FORWARD_RETURN_DAYS

    header_lines, records, malformed = load_track_record(path)
    if malformed:
        print(f"WARNING: {len(malformed)} malformed line(s) in {path} -- left untouched, not parsed.")

    updated_count = 0
    skipped_count = 0
    for record in records:
        fields = [f"forward_return_{d}d" for d in forward_return_days]
        already_complete = all(record.get(f) is not None for f in fields)
        if already_complete:
            skipped_count += 1
            continue
        new_values = compute_forward_returns(record["ticker"], record["date"], forward_return_days)
        changed = False
        for field, value in new_values.items():
            if record.get(field) is None and value is not None:
                record[field] = value
                changed = True
        if changed:
            updated_count += 1
        else:
            skipped_count += 1

    if not dry_run:
        fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for h in header_lines:
                    f.write(h + "\n")
                for r in records:
                    f.write(json.dumps(r) + "\n")
                for m in malformed:
                    f.write(m + "\n")
            for _attempt in range(5):
                try:
                    os.replace(tmp_path, path)
                    break
                except PermissionError:
                    if _attempt == 4:
                        raise
                    time.sleep(0.2)
        except Exception:
            os.unlink(tmp_path)
            raise

    return updated_count, skipped_count, len(malformed)


def main():
    updated, skipped, malformed = backfill()
    print(f"Backfill complete: {updated} record(s) updated, {skipped} already complete or too-recent, "
          f"{malformed} malformed line(s) left untouched.")


if __name__ == "__main__":
    main()
    sys.exit(0)
