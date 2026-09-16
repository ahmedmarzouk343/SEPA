"""
data_persistence.py -- Feature 8: Data Persistence Layer.

Four callable functions for Kashif's two persistent stores:
  1. write_event(event_dict)                 -> appends to watchlist_history.jsonl
  2. update_ticker_state(ticker, fields_dict) -> upserts ticker_state.parquet
  3. get_current_state(ticker)               -> reads current row from parquet
  4. query_watchlist_history(filters)         -> queries JSONL with filters

No imports from kashif_strategy.py or any pipeline module.

Stores:
  watchlist_history.jsonl — append-only event log, one JSON line per event
  ticker_state.parquet    — one row per ticker, updated (not appended) on each event
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent
# --------------------------------------------------------------------------
# MARKET SCOPING (Action 2)
#
# These files used to be global, so run_backtest.py (EGX, 195 tickers) and
# run_backtest_sp500.py (S&P 500, 503 tickers) wrote the SAME
# watchlist_history.jsonl and ticker_state.parquet. Running both at once
# interleaved two markets' events into one history file and raced on the
# state table (last writer wins), and --clear-receipts in one run deleted
# the other's receipts mid-flight.
#
# Call set_market("SP500") BEFORE the strategy runs to scope every path.
# Default stays "EGX" so existing callers keep their current filenames.
# --------------------------------------------------------------------------
MARKET = "EGX"
WATCHLIST_HISTORY_PATH = PROJECT_DIR / f"watchlist_history_{MARKET}.jsonl"
TICKER_STATE_PATH = PROJECT_DIR / f"ticker_state_{MARKET}.parquet"


def set_market(market):
    """
    Re-point every persistence path at a market-scoped filename.

    Module-level globals rather than parameters because write_event() and
    update_ticker_state() are called from deep inside the strategy, which has
    no notion of which market it is trading. Must be called before cerebro.run().
    """
    global MARKET, WATCHLIST_HISTORY_PATH, TICKER_STATE_PATH
    MARKET = str(market)
    WATCHLIST_HISTORY_PATH = PROJECT_DIR / f"watchlist_history_{MARKET}.jsonl"
    TICKER_STATE_PATH = PROJECT_DIR / f"ticker_state_{MARKET}.parquet"
    return {"market": MARKET,
            "watchlist_history": str(WATCHLIST_HISTORY_PATH),
            "ticker_state": str(TICKER_STATE_PATH)}

TICKER_STATE_COLUMNS = [
    "ticker", "last_updated", "current_status", "days_on_watchlist",
    "stage_reached", "stage_failed_at", "failure_reason",
    "composite_score", "vcp_quality_score", "catalyst_score",
    "position_entry_price", "position_entry_date", "position_shares",
    "position_current_stop", "total_closed_trades", "lifetime_pnl_egp",
]


def write_event(event_dict):
    """Appends one JSON line to watchlist_history.jsonl. Never overwrites."""
    if "event_id" not in event_dict:
        event_dict["event_id"] = str(uuid.uuid4())
    if "timestamp" not in event_dict:
        event_dict["timestamp"] = datetime.now(timezone.utc).isoformat()
    with open(WATCHLIST_HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(event_dict, default=str) + "\n")
    return event_dict


def _load_ticker_state():
    """
    Load the derived ticker-state table.

    Fails SOFT on a corrupt file. ticker_state.parquet is derived state — it
    is rebuilt from watchlist_history.jsonl events as a run proceeds — so a
    damaged file is never worth aborting for. It previously raised straight
    out of update_ticker_state() and killed a ~2-hour backtest outright:
        OSError: Unexpected end of stream: Page was smaller (501) than
                 expected (504)
    The bad file is renamed aside (not deleted) so it can still be inspected,
    and the run continues from an empty table.
    """
    if not TICKER_STATE_PATH.exists():
        return pd.DataFrame(columns=TICKER_STATE_COLUMNS)
    try:
        return pd.read_parquet(TICKER_STATE_PATH)
    except Exception as e:  # noqa: BLE001 — any read failure is recoverable here
        try:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            TICKER_STATE_PATH.rename(
                TICKER_STATE_PATH.with_suffix(f".parquet.corrupt.{stamp}"))
        except Exception:
            pass
        print(f"[data_persistence] ticker_state.parquet unreadable ({e}); "
              f"quarantined and starting from an empty state table.")
        return pd.DataFrame(columns=TICKER_STATE_COLUMNS)


def _save_ticker_state(df):
    """
    Write atomically: full write to a temp file in the same directory, then
    os.replace() onto the target. os.replace is atomic on Windows and POSIX,
    so an interrupted run can no longer leave a half-written parquet behind —
    which is exactly how the file above got truncated.
    """
    tmp = TICKER_STATE_PATH.with_suffix(f".parquet.tmp{os.getpid()}")
    try:
        df.to_parquet(tmp, index=False)
        for _attempt in range(5):
            try:
                os.replace(tmp, TICKER_STATE_PATH)
                break
            except PermissionError:
                if _attempt == 4:
                    raise
                time.sleep(0.2)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def update_ticker_state(ticker, fields_dict):
    """Updates or creates the ticker's row in ticker_state.parquet."""
    df = _load_ticker_state()

    mask = df["ticker"] == ticker
    if mask.any():
        idx = df.index[mask][0]
        for k, v in fields_dict.items():
            df.at[idx, k] = v
    else:
        row = {"ticker": ticker}
        for col in TICKER_STATE_COLUMNS:
            if col not in row:
                row[col] = None
        row.update(fields_dict)
        new_row = pd.DataFrame([row])
        df = pd.concat([df, new_row], ignore_index=True)

    _save_ticker_state(df)
    return df[df["ticker"] == ticker].iloc[0].to_dict()


def get_current_state(ticker):
    """Returns the current row for a ticker as a dict, or None if not found."""
    if not TICKER_STATE_PATH.exists():
        return None
    df = pd.read_parquet(TICKER_STATE_PATH)
    match = df[df["ticker"] == ticker]
    if match.empty:
        return None
    return match.iloc[0].to_dict()


def query_watchlist_history(filters=None):
    """
    Reads watchlist_history.jsonl and returns matching events.

    filters: dict with optional keys:
      - ticker: str — exact match
      - action: str or list of str — exact match on action field
      - start_date: str (YYYY-MM-DD) — event date >= this
      - end_date: str (YYYY-MM-DD) — event date <= this
    """
    if not WATCHLIST_HISTORY_PATH.exists():
        return []

    filters = filters or {}
    events = []
    with open(WATCHLIST_HISTORY_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            event = json.loads(line)

            if "ticker" in filters and event.get("ticker") != filters["ticker"]:
                continue
            if "action" in filters:
                target = filters["action"]
                if isinstance(target, list):
                    if event.get("action") not in target:
                        continue
                elif event.get("action") != target:
                    continue
            if "start_date" in filters and event.get("date", "") < filters["start_date"]:
                continue
            if "end_date" in filters and event.get("date", "") > filters["end_date"]:
                continue

            events.append(event)

    return events
