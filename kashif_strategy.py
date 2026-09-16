"""
KashifStrategy(bt.Strategy) -- Feature 4 (Risk Rules & Position Sizing),
Feature 5 (Entry Timing / VCP Detection), and Feature 6 (Catalyst Check),
strategy half.

Calls Features 1-3's existing functions unmodified inside next() (market_regime_gate,
evaluate_conditions/hard_filter, category_tagging, compute_composite/fundamentals_screen),
plus Feature 6's catalyst_check.catalyst_check() and Feature 5's
entry_timing.evaluate_entry_timing() (see UPDATE below for the real stage
order, which is NOT the order these features were originally built in).
Owns all custom state MinerviniSizer (kashif_sizer.py) reads. Implements the
no-averaging-down guard, breakeven stop swap, largest-decline exit signal,
Scoring Queue, Decision Receipts, and Corporate Action Guard.

--------------------------------------------------------------------------
SCOPE BOUNDARY, stated plainly (not silently glossed over)
--------------------------------------------------------------------------
UPDATE (Feature 6): catalyst_check is now wired in for real too, and runs
BEFORE entry_timing -- see the reordering note in _evaluate_entry_pipeline()
at the catalyst_check() call site for why Feature 5's original ordering
(entry_timing before catalyst_check) was wrong and got corrected here.
score_with_model() (inside catalyst_check.py) is itself still a deliberate
stub -- always NEUTRAL, pending_model_review=True whenever it's actually
invoked -- so a STRONG_POSITIVE/STRONG_NEGATIVE catalyst_check score cannot
occur yet through the live model path (only through the deterministic
edge-case rules, which CAN produce a real NEUTRAL without the stub ever
running). Because entry_timing.price_ready_status requires fundamentals_pass
AND catalyst_confirmed AND price_ready ALL true simultaneously (JSON), and
fundamentals_screen is still SKIPPED (no data feed wired), `qualifies` stays
False regardless of what price_ready comes back as -- the live pipeline
still cannot organically generate a real buy signal end-to-end. The
known-answer test fixtures for position_sizing/risk_rules still trigger
entries directly (calling strat.buy()/strat.getsizing() from the test
harness), the same precedent already established by Feature 3's Fixture 5
(called get_leader_tickers() directly rather than running a heavier
pipeline).

--------------------------------------------------------------------------
TWO DEVIATIONS FROM feature-04-risk-position-sizing-rules.md's LITERAL TEXT,
both surfaced during design and explicitly confirmed by the user before
building -- not silently decided
--------------------------------------------------------------------------
1. CORPORATE ACTION GUARD: the literal spec says "flag for review, don't
   execute the stop" on a >20% overnight gap. This is not achievable as
   written: backtrader's broker fills a standing Stop order during its own
   bar-open processing, BEFORE next() (or any strategy callback) runs for
   that bar -- by the time strategy code could inspect the gap, the fill
   has already happened. Blocking it would require overriding backtrader's
   stop execution, which Section 0.1 itself forbids ("gap-through
   execution... already correct behavior -- don't override it").
   RESOLVED (confirmed by user): let the stop fill exactly as backtrader
   executes it. If a >20% overnight gap coincides with that fill, exclude
   the trade from consecutive_stops/defensive_mode tracking (protects the
   risk statistics from a false stop caused by a split/dividend) and flag
   it "corporate_action_suspected" in the Decision Receipt, rather than
   literally blocking the broker's fill.

2. ORDER MANAGEMENT: Section 0.1's literal text says use sell_bracket() (or
   buy_bracket() -- Kashif only goes long, so sell_bracket() is almost
   certainly a doc typo, since that call is for SHORT entries). RESOLVED
   (confirmed by user): skip bracket orders entirely. Use a plain buy(),
   then on fill submit a separate sell(exectype=Stop) tracked by reference.
   The breakeven-stop swap (Section 0.2) already requires manually
   canceling and replacing the stop leg mid-position -- awkward and
   uncertain with a bracket order's linked/OCO legs. Manual two-order
   tracking sidesteps that entirely and is what buy_bracket() is internally
   built from anyway.

--------------------------------------------------------------------------
SHARED STATE CONTRACT with kashif_sizer.py -- see that file's docstring too
--------------------------------------------------------------------------
Attributes MinerviniSizer reads via self.strategy.<name>:
  self.p.target_position_count, self.current_streak_step, self.is_defensive_mode,
  self.is_reentry_from_cash, self.defensive_mode_multiplier, self.reentry_pilot_multiplier

Additional state owned here, not read by the sizer:
  self.consecutive_stops, self.recent_closed_trades (deque maxlen 20),
  self.streak_consecutive_winners, self.pilot_consecutive_winners,
  self.highest_close_since_entry / self.largest_decline_since_entry /
  self.entry_price / self.initial_stop_distance / self.stop_order /
  self.breakeven_done (all dicts keyed by `data`),
  self.pending_trade_was_stop (dict keyed by `data`, set in notify_order,
  read+popped in notify_trade -- confirmed empirically that notify_order's
  Completed status for a closing sell fires BEFORE notify_trade for the
  same fill event).

--------------------------------------------------------------------------
COLUMN-NAMING TRANSLATION BOUNDARY -- easy to get backwards
--------------------------------------------------------------------------
bt.feeds.PandasData uses lowercase open/high/low/close/volume by convention.
compute_indicators()/evaluate_conditions() (trend_template_test.py, imported
unmodified) expect CAPITALIZED Close/High/Low/Volume columns. The internal
per-ticker history buffer built in next() deliberately uses the capitalized
names to match what those functions require.
"""

import json
import math
import collections
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    import backtrader as bt
except ImportError:  # pragma: no cover
    bt = None

import pandas as pd

from trend_template_test import compute_indicators, evaluate_conditions, compute_rs_percentile
from market_regime_gate import (
    market_regime_gate, get_leader_tickers, leader_pullback_shallow,
    leader_divergence, new_high_low_ratio_favorable, compute_new_high_low_ratio,
    DIVERGENCE_PIVOT_LEADER, DIVERGENCE_PIVOT_UNIVERSE, REGIME_GATE_MIN_CONDITIONS,
)
from fundamentals_screen import evaluate_fundamentals
from fundamentals_fetcher import fetch_fundamentals
from category_tagging import tag_universe
from entry_timing import evaluate_entry_timing
from catalyst_check import catalyst_check, get_error_counters, reset_error_counters
import kashif_config
from kashif_sizer import CONCURRENT_POSITIONS_MIN, CONCURRENT_POSITIONS_HARD_CEILING
from data_persistence import write_event, update_ticker_state

OPS_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "daily_ops_log")
RECEIPTS_DIR = Path(__file__).resolve().parent / "decision_receipts"
CATALYST_FALLBACK_WARNING_THRESHOLD = 3  # Section 3.5 -- "> 3" triggers the console warning

from kashif_config import CONFIG_PATH

HARD_MAX_STOP_PCT = 0.10          # risk_rules.stop_loss.hard_max_pct

# --------------------------------------------------------------------------
# FIX B — technical stop placement, anchored on the VCP pivot.
#
# Before: every stop sat at entry * 0.90 regardless of where the pivot was,
# and breakeven fired at a fixed 3 x 10% = +30% gain. 13 of 26 stop-loss
# trades ran +5% to +27% and reversed without ever reaching +30% — all
# shakeouts that a pivot-anchored stop would have sat below.
#
# The stop now sits 3% under the pivot, floored at 4% (noise) and capped at
# 10% (the book's hard ceiling, ch12 "no more than 10% on the downside").
# --------------------------------------------------------------------------
PIVOT_STOP_BUFFER = 0.97          # stop 3% below the VCP pivot
STOP_DISTANCE_MAX = 0.10          # book hard ceiling — never risk more
STOP_DISTANCE_MIN = 0.04          # floor, so noise cannot place a 1% stop
NO_PIVOT_STOP_DISTANCE = 0.07     # book target average when no pivot is known

# Breakeven now scales with the ACTUAL stop distance instead of a fixed 30%.
# 4.0 not 3.0 deliberately: at a typical 6% technical stop, 3x fires at +18%,
# which would cap the trailing-stop winners that averaged +62.85% return
# (8/8 won, avg peak +84.46%) and carried the entire EGX run. 4x fires at
# +24% — above the observed shakeout band (LUTS +27%, IRON +21%) without
# truncating the runners.
BREAKEVEN_TRIGGER_MULT = 4.0      # was implicitly 3.0 against a fixed 10% stop
CORPORATE_ACTION_GAP_PCT = 0.20   # feature-04.md Section 0.2's resolved threshold
DEFENSIVE_TRIGGER_WINDOW = 20     # trailing N closed trades
DEFENSIVE_WIN_LOSS_RATIO_TRIGGER = 1.5    # v0.27: 2.0->1.5, profit-first
DEFENSIVE_WIN_RATE_TRIGGER = 0.40         # v0.27: 0.50->0.40, profit-first
DEFENSIVE_WIN_LOSS_RATIO_REVERT = 2.0     # revert requires both >= these
DEFENSIVE_WIN_RATE_REVERT = 0.50
LARGEST_DECLINE_VOLUME_WINDOW = 50
TRAILING_STOP_BUFFER_PCT = 0.05   # C10: 3%->5% below 50-day MA — calibration parameter

# Feature 9 distribution-bar sensitivity floor (both calibration parameters).
# Without these, largest_decline_since_entry starts at 0.0, so the FIRST
# down-day after entry is trivially "the largest decline since entry" and
# sells the position if volume happens to be above average. The IS backtest
# that exposed this churned 99 round trips and returned -190.89%.
DISTRIBUTION_BAR_MIN_HOLDING_DAYS = 10      # bars held before the rule arms
DISTRIBUTION_BAR_ATR_FLOOR_MULTIPLE = 1.5   # floor = 1.5x normal daily range
DISTRIBUTION_BAR_ATR_PERIOD = 14            # ATR lookback for that floor

# --------------------------------------------------------------------------
# Post-run review changes (IS run kashif_0906d14d3870, 31 closed trades).
# Both are DELIBERATE DEVIATIONS from documented specs — see notes.
# --------------------------------------------------------------------------
# STAGE 3 EXIT DISABLED. feature-09-exit-strategy-rules.md Rule 4 is
# book-cited (ch05) and this switch overrides it, so it is a flag rather than
# a deletion — flip to True to restore the spec'd behaviour exactly.
# Measured on the IS run: 5 exits, TOTAL P&L -2,335, avg return -4.9% against
# an avg PEAK of +12.0%. It converted winners into scratches and losses:
#   DVA  peaked +25.3% -> closed  +0.6%   (2% of the move captured)
#   ABBV peaked +21.0% -> closed  +1.5%   (7%)
#   SW   peaked +11.5% -> closed  -9.9%
# By the time a stock that has run +25% breaks its 200-day MA, the exit is
# late. Re-enable only with evidence it helps.
STAGE3_TRANSITION_EXIT_ENABLED = False

# ---------------------------------------------------------------------------
# PAIRED-EXPERIMENT CONTROLS
#
# Both read the environment, NOT a source edit, so Run A and Run B execute
# byte-identical code and the only difference between them is the variable the
# experiment is varying. Editing the source between arms would leave the two
# runs incomparable in exactly the way this comparison exists to avoid.
#
# Defaults reproduce current production behaviour, so an ordinary run with no
# environment set is unchanged.
# ---------------------------------------------------------------------------

# Fix 1 under test. "EGX" passes market= to evaluate_entry_timing(), which
# turns on the volume-dry-up gate AND switches to the weekly-primary path that
# skips daily contraction re-validation. "NONE" is the pre-Fix-1 baseline.
# DEFAULT REVERTED TO None (2026-09-05). The paired test — Run A market=None
# vs Run B market="EGX", split corrections applied and catalyst stubbed in
# both — found Fix 1 actively harmful: +107.32% vs +42.11%, win rate 52.6% vs
# 30.2%, profit factor 4.59 vs 2.38. Passing market="EGX" takes a branch that
# skips daily contraction re-validation entirely (entry_timing.py), trading
# ~9,400 daily-structure rejections for ~8,400 volume rejections and yielding
# 48% more signals at much lower precision. Set KASHIF_ENTRY_MARKET=EGX to
# re-enable for a comparison run; do not restore it as the default without a
# new paired backtest.
_ENTRY_MARKET_RAW = os.environ.get("KASHIF_ENTRY_MARKET", "NONE").strip().upper()
ENTRY_TIMING_MARKET = None if _ENTRY_MARKET_RAW in ("", "NONE", "NULL") else _ENTRY_MARKET_RAW

# Catalyst control. "stub" forces every ticker to a NEUTRAL, non-blocking
# result with zero network calls, so catalyst state is a constant across arms
# instead of a 20-call budget that races and orders differently per run.
CATALYST_MODE = os.environ.get("KASHIF_CATALYST_MODE", "live").strip().lower()
CATALYST_STUBBED = CATALYST_MODE == "stub"


def _stub_catalyst_result(ticker):
    """
    Deterministic NEUTRAL stand-in for catalyst_check(). Shapes exactly like a
    real result so _update_catalyst_counters() and the receipt builder need no
    special-casing: model_call_attempted False (no API call counted),
    retry_log [] (not None — a None here is what previously raised inside the
    counter update and silently killed catalyst_check), error_flag False (not
    a fallback), pipeline_blocks_entry False (never gates entry).
    """
    return {
        "score": "NEUTRAL",
        "source": "stubbed_for_controlled_run",
        "priority_tier": "NONE",
        "rationale": f"catalyst stubbed (KASHIF_CATALYST_MODE=stub) for {ticker}",
        "pipeline_blocks_entry": False,
        "model_call_attempted": False,
        "retry_log": [],
        "error_flag": False,
    }

# PEAK-REFERENCED TRAILING FLOOR. NOT in the book and NOT in feature-09 —
# the spec's Rule 5 uses a 50-day MA floor only. That floor lags badly on a
# stock that spikes then decays, so the stop never ratchets above breakeven
# and the whole gain is returned:
#   TSLA peaked +39.9% -> closed -4.3%  (BREAKEVEN_STOP; trailing never armed)
#   PANW peaked +52.7% -> closed +6.1%  (12% captured)
# Across the run, 14 of 31 trades peaked positive and closed negative,
# giving back 219 percentage points of price move. This caps the give-back
# from the running peak. Pure calibration parameter — no book basis.
TRAILING_STOP_MAX_GIVEBACK_PCT = 0.15
# FIX A (Defect 2): 260 -> 400. 260 daily bars is ~52 weekly bars, too few for
# the WEEKLY stage of the weekly-then-daily VCP detector to resolve a base —
# measured: at 260 bars ZERO of the 42 missed 200%+ winners ever produced a
# PRICE_READY signal; at 400 bars three do (WKOL +509%, MENA +405%, OIH +383%),
# all signalling before their peak. 500/600/750/unlimited recover nothing
# further, so 400 is the whole of the available gain.
HISTORY_BUFFER_MAXLEN = 400       # >= 252-day RS/52wk window + weekly VCP depth
MARKET_SUFFIX = ".CA"             # yfinance exchange suffix (".CA" for EGX, "" for US)

# A6 — losing streak step-down RESTORED (was neutered to [1.0] in v0.27).
# ch13: "reduce position size in steps (40% -> 20%) during losing streaks".
# The step SIZES (0.40, 0.20) are book-given; the TRIGGER COUNTS (3, 5) and
# the recovery rule are CALIBRATION PARAMETERS, not book numbers.
STREAK_STEPS = [1.0, 0.40, 0.20]
STREAK_STEP_DOWN_TRIGGERS = {3: 1, 5: 2}   # 3 consecutive stops -> 40%, 5 -> 20%
# B3 — recovery: 2 consecutive winners -> 1 profitable trade steps up one level.
# ch13 says only "once performance normalizes"; 1 is the more permissive read.
STREAK_RECOVERY_WINNERS_NEEDED = 1

# Section 2.2 -- reentry_from_cash exact rule.
REENTRY_PILOT_WINNERS_TO_GRADUATE = 2


def load_risk_rules():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg["risk_rules"]


def load_position_sizing():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg["position_sizing"]


class KashifStrategy(bt.Strategy if bt is not None else object):
    params = (
        ("target_position_count", 6),  # v0.27: 4->6, profit-first (book's 4-6 range)
        ("decision_receipts_dir", str(RECEIPTS_DIR)),
        ("run_period", "UNKNOWN"),     # Fix 5: IS/VAL/OOS, stamped into RUN_START
    )

    def __init__(self):
        rr = load_risk_rules()
        self.defensive_mode_multiplier = rr["defensive_mode"]["adjustments"]["position_size_multiplier"]
        self.reentry_pilot_multiplier = 0.50  # A4: 75%->50%; ch13 "small pilot positions first"

        assert CONCURRENT_POSITIONS_MIN <= self.p.target_position_count <= CONCURRENT_POSITIONS_HARD_CEILING, \
            "target_position_count out of the JSON's concurrent_positions bounds"

        # --- Sizer-facing state (see module docstring's shared contract) ---
        self.current_streak_step = STREAK_STEPS[0]
        self.is_defensive_mode = False
        self.is_reentry_from_cash = False

        # --- Strategy-internal state ---
        self.consecutive_stops = 0
        self.streak_step_index = 0
        self.streak_consecutive_winners = 0
        self.pilot_consecutive_winners = 0
        self.recent_closed_trades = collections.deque(maxlen=DEFENSIVE_TRIGGER_WINDOW)

        self.highest_close_since_entry = {}
        self.lowest_close_since_entry = {}
        self.largest_decline_since_entry = {}
        self.entry_price = {}
        self.entry_date = {}
        self.entry_bar_index = {}
        self.initial_stop_distance = {}
        # FIX B: per-position stop distance as a FRACTION of entry price.
        # Pivot-derived, so it varies per trade instead of always being 0.10.
        self.stop_distance_pct = {}
        self.stop_order = {}
        # Every stop order ever placed per data, so none can be orphaned.
        # Dropping the self.stop_order reference does NOT remove an order
        # from the broker: an uncancelled stop stays live indefinitely and
        # can fire months after its position closed, opening a SHORT.
        # (IS backtest: DELL/GEN/FISV/WDC each went short this way when
        # price fell back through a stale breakeven stop in April 2025.)
        self.all_stop_orders = {}
        self.stop_type = {}
        self.breakeven_done = {}
        self.pending_trade_was_stop = {}
        # FIX 2: actual SELL fill price, captured in notify_order. notify_trade
        # used d.close[0] — the bar's CLOSE — as the exit price, which is not
        # what the trade executed at. A stop that fills intrabar (or gaps
        # through at the open) can be far from that bar's close, so
        # stock_return_pct in trade_log.csv disagreed with the realised pnl.
        self.exit_fill_price = {}
        self.exit_candidates = {}
        self.exit_reason = {}
        self.spy_price_at_entry = {}
        self.position_exit_metrics = {}
        self._pending_entry_receipt = {}
        self.flagged_for_review = []

        self._spy_data = None
        for d in self.datas:
            if d._name == "SPY":
                self._spy_data = d
                break

        self.history = {d: collections.deque(maxlen=HISTORY_BUFFER_MAXLEN) for d in self.datas}
        self._high_low_counts = collections.deque(maxlen=HISTORY_BUFFER_MAXLEN)
        self.decision_receipts = []
        self.regime_open_count = 0
        self._regime_diag_counts = {"ratio": 0, "pullback": 0, "divergence": 0, "eval_bars": 0}

        # N-10 fix: per-bar caches — cleared at the top of each next() call.
        self._indicator_cache = {}
        self._rs_snapshot_cache = None
        self._indicator_cache_hits = 0
        self._indicator_cache_misses = 0

        self._fundamentals_cache = {}

        # P19 fix: historical RS percentile cache — date → {ticker: percentile}.
        # Accumulated over the run so each bar's hard_filter uses the RS
        # percentile that was cross-sectionally correct on THAT date, not
        # today's snapshot broadcast to every bar.
        self._rs_percentile_history = {}

        # P13 wiring: pre-computed category tags DataFrame (indexed by ticker).
        # Populated via load_category_tags() when market-cap/listing-date data
        # is available; empty DataFrame when no data source is wired.
        self._category_tags = pd.DataFrame()

        # Feature 6 -- identifies which backtest/live run produced a given
        # catalyst_track_record.jsonl entry (Stage D field, per
        # feature-06-catalyst-check-rules.md Section 6).
        self._pipeline_run_id = f"kashif_{uuid.uuid4().hex[:12]}"
        # Fix 5: receipt files that already carry this run's RUN_START marker.
        self._receipt_files_marked = set()

        # Feature 7 -- Daily Operations Log counters (Section 3.3/3.4).
        # Reset catalyst_check.py's module-level HTTP error counters here
        # too -- they are module-level (not per-strategy-instance) globals,
        # so without this reset a second cerebro.run() in the same Python
        # process would carry over the previous run's error counts into
        # this run's ops log, contradicting Section 3.2's "one file per
        # calendar day, latest run wins" framing.
        reset_error_counters()
        self._tickers_scanned = 0
        self._tickers_passing_hard_filter = 0
        self._tickers_reaching_catalyst_check = 0
        self._catalyst_api_calls_made = 0
        self._catalyst_api_errors = 0
        self._catalyst_fallback_to_neutral = 0
        self._new_entries_signaled = 0
        self._exit_signals_flagged = 0
        self._pipeline_errors = []
        self._ledger_drift_events = []

        # Feature 8 — Data Persistence Layer state.
        # _watchlist: tickers currently being tracked (passed hard_filter).
        # Maps ticker -> {"added_date": str, "stage_reached": str}.
        self._watchlist = {}
        # _held_event_written: tickers for which the one-time HELD event was emitted.
        self._held_event_written = set()

    # ------------------------------------------------------------------
    # Config-driven helpers (kept as small, directly-testable methods)
    # ------------------------------------------------------------------

    def _update_defensive_mode(self):
        """
        v0.27 profit-first:
          trigger: rolling_win_loss_ratio < 1.5 OR rolling_win_rate < 0.40
          revert:  rolling_win_loss_ratio >= 2.0 AND rolling_win_rate >= 0.50
        """
        trades = list(self.recent_closed_trades)
        if len(trades) < 10:
            return
        wins = [t for t in trades if t["was_win"]]
        losses = [t for t in trades if not t["was_win"]]
        win_rate = len(wins) / len(trades)

        avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0.0
        avg_loss = abs(sum(t["pnl"] for t in losses) / len(losses)) if losses else 0.0
        win_loss_ratio = (avg_win / avg_loss) if avg_loss > 0 else float("inf")

        if self.is_defensive_mode:
            if win_loss_ratio >= DEFENSIVE_WIN_LOSS_RATIO_REVERT and win_rate >= DEFENSIVE_WIN_RATE_REVERT:
                self.is_defensive_mode = False
        else:
            if win_loss_ratio < DEFENSIVE_WIN_LOSS_RATIO_TRIGGER or win_rate < DEFENSIVE_WIN_RATE_TRIGGER:
                self.is_defensive_mode = True

    def _guard_no_averaging_down(self, data):
        """
        Section 2.3: weighted average entry price = position.price in
        backtrader. Returns True if an add-on buy is allowed.
        """
        pos = self.broker.getposition(data)
        if pos.size <= 0:
            return True  # no existing position, nothing to "average down" from
        return not (data.close[0] < pos.price)

    def getsizing(self, data=None, isbuy=True):
        """
        Thin wrapper around backtrader's real Strategy.getsizing(), which
        forwards to the attached MinerviniSizer. Kept as a named method here
        purely so fixtures can call strat.getsizing(data, isbuy=True) in one
        obviously-real-wiring call, matching this project's "call the real
        code, not a re-typed copy" standard.
        """
        return super().getsizing(data=data, isbuy=isbuy)

    # ------------------------------------------------------------------
    # Per-bar loop
    # ------------------------------------------------------------------

    def prenext(self):
        # Multi-data strategies: process bars before all feeds are active.
        # Internal code already handles missing/insufficient history per ticker.
        self.next()

    def next(self):
        # --- KILL SWITCH CHECK (Feature 7 -- must be first, before any
        # pipeline logic). Halts NEW entry evaluation only; held positions
        # still get exit checks (stop-loss, breakeven, largest-decline) --
        # a deliberate safety property (Section 2.3), not an oversight.
        # P23 fix: reads kashif_config.KILL_SWITCH as a live module
        # attribute on every next() call — toggling it mid-run takes
        # effect immediately without restarting the process.
        if kashif_config.KILL_SWITCH:
            kill_switch_receipt = {
                "date": str(self.datas[0].datetime.date(0)),
                "ticker": "ALL",
                "stages": {"kill_switch": "HALTED"},
                "final_verdict": "KILL_SWITCH_HALTED",
                "human_readable": ("KILL_SWITCH=True in kashif_config.py -- "
                                    "new entry evaluation skipped"),
            }
            self.decision_receipts.append(kill_switch_receipt)
            self._flush_decision_receipts_for_date(self.datas[0].datetime.date(0))
            for d in self.datas:
                if self.broker.getposition(d).size > 0:
                    self._manage_open_position(d)
            return

        # N-10 fix: invalidate per-bar caches (new bar = new data).
        self._indicator_cache = {}
        self._rs_snapshot_cache = None

        # 1. Append today's bar to each ticker's history buffer (translation
        # boundary: capitalized columns to match compute_indicators()).
        # "Date" added in Feature 5 -- entry_timing.py's weekly resample()
        # needs a real DatetimeIndex; the buffer had no date field at all
        # before this (Features 1-4 never needed one, since compute_indicators
        # /evaluate_conditions only need positional continuity).
        for d in self.datas:
            self.history[d].append({
                "Date": d.datetime.date(0),
                "Open": d.open[0], "High": d.high[0], "Low": d.low[0],
                "Close": d.close[0], "Volume": d.volume[0],
            })

        # 1b. Accumulate daily 52-week high/low counts for the regime gate's
        # new-high-low ratio (T0-A fix: rolling time series, not a snapshot).
        count_high = 0
        count_low = 0
        for d in self.datas:
            closes = [b["Close"] for b in self.history[d]]
            if len(closes) >= 253:
                if closes[-1] >= max(closes[-253:]):
                    count_high += 1
                if closes[-1] <= min(closes[-253:]):
                    count_low += 1
        self._high_low_counts.append((count_high, count_low))

        # 1c. P19 fix: accumulate today's cross-sectional RS percentile into
        # the historical cache so _evaluate_entry_pipeline can build a per-bar
        # RS series (no lookahead — each bar gets only the rank computed from
        # data available on that date).
        today = self.datas[0].datetime.date(0)
        rs_today = self._compute_rs_snapshot()
        if rs_today:
            self._rs_percentile_history[today] = rs_today
            self._rs_snapshot_cache = rs_today

        # 2. Cross-sectional Feature 3 gate -- computed ONCE per bar, not
        # per ticker, since its inputs are themselves cross-sectional.
        self.regime_open, self.regime_diag = self._evaluate_market_regime()
        if self.regime_open:
            self.regime_open_count += 1

        candidates = []
        still_passing = set()

        for d in self.datas:
            if d._name == "SPY":
                continue
            self._tickers_scanned += 1  # Feature 7 -- every ticker evaluated in next()
            try:
                pos = self.broker.getposition(d)
                if pos.size > 0:
                    self._manage_open_position(d)
                elif self.regime_open:
                    receipt, qualifies = self._evaluate_entry_pipeline(d)
                    self.decision_receipts.append(receipt)

                    ticker = d._name
                    hf_passed = receipt.get("stages", {}).get("hard_filter") == "PASS"

                    if hf_passed:
                        still_passing.add(ticker)
                        if ticker not in self._watchlist:
                            self._watchlist[ticker] = {
                                "added_date": str(self.datas[0].datetime.date(0)),
                                "last_receipt": receipt,
                            }
                            self._emit_watchlist_event("ADDED", d, receipt=receipt)
                        else:
                            self._watchlist[ticker]["last_receipt"] = receipt
                    elif ticker in self._watchlist:
                        failed_stage = receipt.get("final_verdict", "").replace("REJECTED_AT_", "")
                        self._emit_watchlist_event(
                            "STAGE_FAILED", d, receipt=receipt,
                            reason=f"Failed at {failed_stage}: {receipt.get('human_readable', '')}",
                        )

                    if qualifies:
                        candidates.append((d, receipt))
            except Exception as e:  # noqa: BLE001 -- Feature 7 ops-log safety net.
                self._pipeline_errors.append(f"{d._name}: {e}")

        # Feature 8: REMOVED — watchlist tickers that didn't pass this bar
        removals = []
        for ticker in list(self._watchlist):
            if ticker not in still_passing:
                held = any(
                    d._name == ticker and self.broker.getposition(d).size > 0
                    for d in self.datas
                )
                if not held:
                    reason = "market_regime_closed" if not self.regime_open else "failed_hard_filter"
                    for d in self.datas:
                        if d._name == ticker:
                            self._emit_watchlist_event("REMOVED", d, reason=reason)
                            break
                    removals.append(ticker)
        for ticker in removals:
            del self._watchlist[ticker]

        # 3. Scoring Queue -- rank same-bar candidates, fill available slots
        # highest-first (Considerations.md Section 4).
        self._run_scoring_queue(candidates)

        # 4. Flush Decision Receipts for this trading day.
        self._flush_decision_receipts_for_date(self.datas[0].datetime.date(0))

    def _evaluate_market_regime(self):
        """
        Cross-sectional market_regime_gate() inputs, built from all
        self.datas collectively. Defensive: returns (False, {}) rather than
        raising if there isn't enough history yet for any component --
        insufficient history is not a failure, same "evaluable" convention
        already established in Features 1-3.
        """
        try:
            if self._rs_snapshot_cache is not None:
                rs_snapshot = self._rs_snapshot_cache
            else:
                rs_snapshot = self._compute_rs_snapshot()
                self._rs_snapshot_cache = rs_snapshot
            leader_tickers = get_leader_tickers(rs_snapshot) if rs_snapshot else []
            leader_prices = {d._name: pd.Series([b["Close"] for b in self.history[d]])
                              for d in self.datas if d._name in leader_tickers and len(self.history[d]) >= 20}
            universe_prices = {d._name: pd.Series([b["Close"] for b in self.history[d]])
                                for d in self.datas if len(self.history[d]) >= 40}

            if not leader_prices or not universe_prices:
                return False, {"reason": "insufficient_history"}

            pullback_pass, pullback_diag = leader_pullback_shallow(leader_prices)

            leader_hl = [self._higher_low_flag(s) for s in leader_prices.values()]
            universe_hl = [self._higher_low_flag(s) for s in universe_prices.values()]
            divergence_pass, divergence_diag = leader_divergence(leader_hl, universe_hl)

            ratio_pass = self._new_high_low_ratio_favorable_snapshot()

            self._regime_diag_counts["eval_bars"] += 1
            if ratio_pass:
                self._regime_diag_counts["ratio"] += 1
            if pullback_pass:
                self._regime_diag_counts["pullback"] += 1
            if divergence_pass:
                self._regime_diag_counts["divergence"] += 1

            gate_pass, gate_diag = market_regime_gate(ratio_pass, pullback_pass, divergence_pass)
            gate_diag["_pullback"] = pullback_diag
            gate_diag["_divergence"] = divergence_diag
            return gate_pass, gate_diag
        except Exception as e:  # noqa: BLE001 -- defensive, insufficient synthetic history in fixtures is expected
            return False, {"reason": f"regime_evaluation_error: {e}"}

    def _compute_rs_snapshot(self):
        rets = {}
        for d in self.datas:
            closes = [b["Close"] for b in self.history[d]]
            if len(closes) >= 253:
                rets[d._name] = closes[-1] / closes[-253] - 1
        if len(rets) < 2:
            return {}
        ret_wide = pd.DataFrame({k: [v] for k, v in rets.items()})
        pct = compute_rs_percentile(ret_wide)
        return pct.iloc[0].to_dict()

    @staticmethod
    def _higher_low_flag(price_series, window=20):
        if len(price_series) < window * 2:
            return False
        low_nd = price_series.rolling(window).min()
        return bool(low_nd.iloc[-1] > low_nd.iloc[-1 - window])

    def _new_high_low_ratio_favorable_snapshot(self):
        # T0-A fix: use the rolling time series accumulated in next(), not a
        # constant single-value broadcast.  Needs 22+ bars of history so the
        # ratio[t] > ratio[t-21] comparison has a real prior value.
        if len(self._high_low_counts) < 22:
            return False
        count_high = pd.Series([h for h, _ in self._high_low_counts])
        count_low = pd.Series([l for _, l in self._high_low_counts])
        ratio = compute_new_high_low_ratio(count_high, count_low)
        fav = new_high_low_ratio_favorable(ratio)
        return bool(fav.iloc[-1]) if not pd.isna(fav.iloc[-1]) else False

    def _evaluate_entry_pipeline(self, d):
        """
        Runs pipeline_order stages 2 (hard_filter) through 6 (entry_timing)
        for one ticker, all for real -- catalyst_check (stage 5) now runs
        BEFORE entry_timing (stage 6), matching the JSON's pipeline_order
        and feature-06.md Section 0 (see the reordering note at the
        catalyst_check call site below). Returns (receipt: dict, qualifies: bool).
        """
        ticker = d._name
        stages = {"market_regime_gate": "PASS" if self.regime_open else "CLOSED"}
        qualifies = False
        tag_row = None

        ps = {
            "market_regime": self._build_regime_reason(),
            "hard_filter": {"result": "SKIPPED", "conditions_passed": [], "conditions_failed": [], "reason": "not yet evaluated"},
            "category_tag": {"result": "SKIPPED", "reason": "not yet reached"},
            "fundamentals": {"result": "SKIPPED", "overall_reason": "not yet reached"},
            "catalyst": {"result": "SKIPPED", "reason": "not yet reached"},
            "entry_timing": {"result": "SKIPPED", "reason": "not yet reached"},
        }

        if not self.regime_open:
            receipt = self._build_receipt(d, stages, "REJECTED_AT_market_regime_gate")
            receipt["_pipeline_state"] = ps
            return receipt, False

        bars = self.history[d]
        if len(bars) < 253:
            ps["hard_filter"] = {"result": "SKIPPED", "reason": f"Insufficient history ({len(bars)} bars, need 253 for RS percentile)"}
            stages["hard_filter"] = "SKIPPED: insufficient_history"
            receipt = self._build_receipt(d, stages, "REJECTED_AT_hard_filter")
            receipt["_pipeline_state"] = ps
            return receipt, False

        try:
            if ticker in self._indicator_cache:
                df = self._indicator_cache[ticker]
                self._indicator_cache_hits += 1
            else:
                df = pd.DataFrame(list(bars))
                df.index = pd.RangeIndex(len(df))
                df = compute_indicators(df)
                self._indicator_cache[ticker] = df
                self._indicator_cache_misses += 1
            bar_dates = [b["Date"] for b in bars]
            rs_pct = pd.Series(
                [self._rs_percentile_history.get(dt, {}).get(ticker, float("nan"))
                 for dt in bar_dates],
                index=df.index,
            )
            cond, evaluable, all_pass = evaluate_conditions(df, rs_pct)
            hf_pass = bool(all_pass.iloc[-1]) if evaluable.iloc[-1] else False
        except Exception as e:  # noqa: BLE001
            ps["hard_filter"] = {"result": "FAIL", "reason": f"Error evaluating conditions: {e}"}
            stages["hard_filter"] = f"ERROR: {e}"
            receipt = self._build_receipt(d, stages, "REJECTED_AT_hard_filter")
            receipt["_pipeline_state"] = ps
            return receipt, False

        if not hf_pass:
            failing = [c for c in cond.columns if not cond[c].iloc[-1]]
            passing = [c for c in cond.columns if cond[c].iloc[-1]]
            current_rs = rs_pct.iloc[-1] if not rs_pct.empty else None
            rs_str = f", RS percentile {current_rs:.0f}th" if current_rs is not None and not pd.isna(current_rs) else ""
            ps["hard_filter"] = {
                "result": "FAIL",
                "conditions_passed": passing,
                "conditions_failed": failing,
                "reason": f"Failed {len(failing)} Trend Template condition(s): {', '.join(failing)}{rs_str}",
            }
            stages["hard_filter"] = f"FAIL: {', '.join(failing[:3])}"
            receipt = self._build_receipt(d, stages, "REJECTED_AT_hard_filter")
            receipt["_pipeline_state"] = ps
            return receipt, False

        passing_all = list(cond.columns)
        current_rs = rs_pct.iloc[-1] if not rs_pct.empty else None
        rs_str = f", RS percentile {current_rs:.0f}th across EGX universe" if current_rs is not None and not pd.isna(current_rs) else ""
        ps["hard_filter"] = {
            "result": "PASS",
            "conditions_passed": passing_all,
            "conditions_failed": [],
            "reason": f"All {len(passing_all)} Trend Template conditions confirmed{rs_str}",
        }
        stages["hard_filter"] = "PASS"
        self._tickers_passing_hard_filter += 1  # Feature 7 -- Section 3.4

        if not self._category_tags.empty and ticker in self._category_tags.index:
            tag_row = self._category_tags.loc[ticker]
            band = tag_row.get("market_cap_band", "unknown")
            cap_mod = tag_row.get("market_cap_band_modifier", 0.0)
            ipo_mod = tag_row.get("years_since_ipo_modifier", 0.0)
            cat = tag_row.get("category", "unclassified")
            yrs = tag_row.get("years_since_ipo", None)
            ps["category_tag"] = {
                "result": str(cat),
                "market_cap_band": str(band),
                "years_since_ipo": float(yrs) if yrs is not None else None,
                "reason": f"{band}-cap, categorized as {cat} (cap_mod={cap_mod:.3f}, ipo_mod={ipo_mod:.3f})",
            }
            stages["category_tagging"] = (
                f"band={band} "
                f"cap_mod={cap_mod:.3f} "
                f"ipo_mod={ipo_mod:.3f}"
            )
        else:
            ps["category_tag"] = {"result": "SKIPPED", "reason": f"No category data available for {ticker}"}
            stages["category_tagging"] = "SKIPPED: no category data for ticker"

        try:
            current_date = pd.Timestamp(self.datas[0].datetime.date(0))
            ticker_name = d._name
            if ticker_name not in self._fundamentals_cache:
                self._fundamentals_cache[ticker_name] = fetch_fundamentals(ticker_name, suffix=MARKET_SUFFIX)
            fund_data = self._fundamentals_cache[ticker_name]
            if fund_data is None or fund_data.get("eps_yoy_growth_by_quarter") is None:
                ps["fundamentals"] = {"result": "SKIPPED", "overall_reason": f"No yfinance quarterly data available for {ticker}"}
                stages["fundamentals_screen"] = "SKIPPED: no yfinance quarterly data"
            else:
                category = tag_row.get("category") if tag_row is not None else None
                fund_result = evaluate_fundamentals(fund_data, category=category)
                fund_pass = fund_result.get("pass", False)
                q1 = fund_result.get("q1", {})
                q2 = fund_result.get("q2", {})
                q3 = fund_result.get("q3", {})
                ps["fundamentals"] = {
                    "result": "PASS" if fund_pass else "FAIL",
                    "q1": q1,
                    "q2": q2,
                    "q3": q3,
                    "overall_reason": fund_result.get("overall_reason", "") + " (Phase A: logged, does not block entry)",
                }
                stages["fundamentals_screen"] = (
                    f"Q1={q1.get('status','?')} Q2={q2.get('status','?')} Q3={q3.get('status','?')} "
                    f"pass={fund_pass} (Phase A: score logged, does NOT block entry)"
                )
        except Exception as e:
            ps["fundamentals"] = {"result": "SKIPPED", "overall_reason": f"Error: {e} (Phase A: does not block entry)"}
            stages["fundamentals_screen"] = f"ERROR: {e} (Phase A: does NOT block entry)"

        # Stage 5 (catalyst_check) -- Feature 6, WIRED IN FOR REAL, and
        # MOVED AHEAD of entry_timing from where Feature 5 originally left
        # it.
        #
        # [CORRECTED -- ordering error, caught before writing any Feature 6
        # code] Feature 5's build ran entry_timing BEFORE catalyst_check
        # (matching the OLD "STUBBED_NOT_BUILT" stub's textual position in
        # this method, which happened to sit after fundamentals_screen and
        # before entry_timing's real code). That ordering contradicts two
        # independent sources: the JSON's own top-level pipeline_order
        # (["...", "fundamentals_screen", "catalyst_check", "entry_timing",
        # ...] -- catalyst_check BEFORE entry_timing) and feature-06.md
        # Section 0's literal text ("after ... Market Regime Gate ... and
        # BEFORE entry timing (Feature 5)"). This task's own instructions
        # confirm it too ("NEUTRAL and STRONG_POSITIVE both allow entry
        # timing to PROCEED" -- phrasing that only makes sense if
        # catalyst_check gates whether entry_timing runs at all, not the
        # reverse). Fixed here: catalyst_check now runs first; a
        # STRONG_NEGATIVE score short-circuits BEFORE entry_timing's real
        # (more expensive) VCP computation ever runs, same "cheap
        # deterministic gates before expensive ones" pattern hard_filter/
        # market_regime_gate already follow.
        self._tickers_reaching_catalyst_check += 1  # Feature 7 -- "just before catalyst_check() is called"
        try:
            bar_date = self.datas[0].datetime.date(0)
            if CATALYST_STUBBED:
                catalyst_result = _stub_catalyst_result(ticker)
            else:
                catalyst_result = catalyst_check(
                    ticker, pipeline_run_id=self._pipeline_run_id,
                    reference_date=bar_date, log_track_record=False,
                )
            self._update_catalyst_counters(catalyst_result)
            stages["catalyst_check"] = (
                f"score={catalyst_result['score']} source={catalyst_result['source']} "
                f"priority_tier={catalyst_result['priority_tier']}"
            )
            if catalyst_result.get("retry_log"):
                stages["catalyst_check"] += f" retry_log={catalyst_result['retry_log']}"
            if catalyst_result.get("error_flag"):
                stages["catalyst_check"] += " error_flag=True"
            ps["catalyst"] = {
                "result": catalyst_result.get("score", "SKIPPED"),
                "source": catalyst_result.get("source", ""),
                "priority_tier": catalyst_result.get("priority_tier", ""),
                "reason": catalyst_result.get("rationale", str(catalyst_result.get("score", ""))),
            }
            if catalyst_result.get("event_description"):
                ps["catalyst"]["event_description"] = catalyst_result["event_description"]
            if catalyst_result.get("disclosure_category"):
                ps["catalyst"]["disclosure_category"] = catalyst_result["disclosure_category"]
        except Exception as e:  # noqa: BLE001 -- defensive, same convention as hard_filter's try/except above
            stages["catalyst_check"] = f"ERROR: {e}"
            ps["catalyst"] = {"result": "SKIPPED", "reason": f"Catalyst check failed: {e}"}
            catalyst_result = None
            self._catalyst_api_errors += 1  # Feature 7 -- the whole call failed outright

        if catalyst_result is not None and catalyst_result["pipeline_blocks_entry"]:
            ps["entry_timing"] = {"result": "SKIPPED", "reason": f"Blocked by STRONG_NEGATIVE catalyst: {catalyst_result.get('rationale', '')}"}
            stages["entry_timing"] = "SKIPPED: blocked by STRONG_NEGATIVE catalyst_check"
            receipt = self._build_receipt(d, stages, "REJECTED_AT_catalyst_check")
            receipt["catalyst_score"] = catalyst_result["score"]
            receipt["catalyst_rationale"] = catalyst_result["rationale"]
            receipt["_pipeline_state"] = ps
            return receipt, False

        # Stage 6 (entry_timing) -- Feature 5. entry_timing.evaluate_entry_
        # timing() needs a real DatetimeIndex for its weekly resample() --
        # built here from the history buffer's "Date" field (added in
        # Feature 5; see next()'s comment) without touching the
        # RangeIndex-based `df` above, which compute_indicators()/
        # evaluate_conditions() still expect unchanged.
        # reference_date=bar_date eliminates lookahead bias: fetch and
        # search functions filter to articles/disclosures on or before
        # the bar date. log_track_record=False suppresses append-only
        # track record writes during backtests.
        vcp_quality_score = 0.0
        pivot_price = None
        try:
            df_dt = df.set_index(pd.DatetimeIndex(df["Date"]))
            # FIX 1: the market kwarg has existed on evaluate_entry_timing()
            # since the EGX volume-dry-up gate was added, but was never passed
            # from here — so require_volume_dryup was False in every backtest
            # run to date and the EGX-specific weekly-base path never ran.
            entry_timing_result = evaluate_entry_timing(df_dt, market=ENTRY_TIMING_MARKET)
            price_ready = entry_timing_result["price_ready"]
            pivot_price = entry_timing_result["pivot_price"]
            vcp_quality_score = entry_timing_result["vcp_quality_score"]
            reason_str = entry_timing_result.get("reason", "")
            stages["entry_timing"] = (
                f"price_ready={price_ready} reason={reason_str} "
                f"pivot={pivot_price} vcp_quality={vcp_quality_score}"
            )
            et_ps = {"result": "PASS" if price_ready else "FAIL", "reason": reason_str}
            if pivot_price is not None:
                et_ps["pivot_price"] = pivot_price
            et_ps["vcp_quality_score"] = vcp_quality_score
            base_number = entry_timing_result.get("base_number")
            if base_number is not None:
                et_ps["base_number"] = base_number
            base_duration = entry_timing_result.get("base_duration_weeks")
            if base_duration is not None:
                et_ps["base_duration_weeks"] = base_duration
            contractions = entry_timing_result.get("contraction_depths")
            if contractions:
                et_ps["contraction_count"] = len(contractions)
                et_ps["contraction_depths"] = contractions
                et_ps["final_contraction_depth_pct"] = contractions[-1] if contractions else None
            vol_ratio = entry_timing_result.get("breakout_volume_ratio")
            if vol_ratio is not None:
                et_ps["breakout_volume_ratio"] = vol_ratio
            if price_ready and contractions:
                depths_str = "->".join(f"{c:.0f}%" for c in contractions)
                vol_str = f", breakout on {vol_ratio:.1f}x average volume" if vol_ratio else ""
                et_ps["reason"] = f"{len(contractions)}-contraction VCP, depths decreasing {depths_str}{vol_str}"
            ps["entry_timing"] = et_ps
        except Exception as e:  # noqa: BLE001 -- defensive, same convention as hard_filter's try/except above
            stages["entry_timing"] = f"ERROR: {e}"
            ps["entry_timing"] = {"result": "FAIL", "reason": f"Entry timing error: {e}"}
            price_ready = False

        catalyst_ok = catalyst_result is None or not catalyst_result["pipeline_blocks_entry"]
        qualifies = price_ready and catalyst_ok

        if qualifies:
            verdict = "QUALIFIED"
        elif not price_ready:
            verdict = "REJECTED_AT_entry_timing"
        else:
            verdict = "REJECTED_AT_catalyst_check"

        receipt = self._build_receipt(d, stages, verdict)
        receipt["vcp_quality_score"] = vcp_quality_score
        receipt["pivot_price"] = pivot_price
        receipt["_pipeline_state"] = ps
        if catalyst_result is not None:
            receipt["catalyst_score"] = catalyst_result["score"]
            receipt["catalyst_rationale"] = catalyst_result["rationale"]
        return receipt, qualifies

    def _build_receipt(self, d, stages, final_verdict):
        human_readable = f"{final_verdict} for {d._name}: " + "; ".join(f"{k}={v}" for k, v in stages.items())
        return {
            "date": str(self.datas[0].datetime.date(0)),
            "ticker": d._name,
            "stages": stages,
            "final_verdict": final_verdict,
            "human_readable": human_readable,
        }

    def _build_regime_reason(self):
        """Feature 8: builds a plain-English market_regime reason from regime_diag."""
        diag = getattr(self, "regime_diag", {})
        result = "OPEN" if self.regime_open else "CLOSED"

        if not diag or "reason" in diag:
            reason_text = diag.get("reason", "insufficient history to evaluate regime")
            return {"result": result, "reason": f"Market regime CLOSED — {reason_text}" if not self.regime_open else reason_text}

        ratio_ok = diag.get("new_high_low_ratio_favorable", False)
        pullback_ok = diag.get("leader_pullback_shallow", False)
        divergence_ok = diag.get("leader_divergence", False)

        pb = diag.get("_pullback", {})
        dv = diag.get("_divergence", {})

        parts = []

        if ratio_ok:
            parts.append("new high/low ratio rising over 21 days")
        else:
            parts.append("new high/low ratio NOT favorable (more new lows than highs)")

        if pb:
            depth = pb.get("avg_pullback_depth")
            days = pb.get("avg_days_since_local_high")
            n = pb.get("n_leaders", 0)
            if depth is not None and days is not None:
                depth_pct = depth * 100 if depth < 1 else depth
                if pullback_ok:
                    parts.append(f"leader basket ({n} tickers, RS>=90) pullback avg {depth_pct:.1f}% over {days:.0f} days — shallow")
                else:
                    parts.append(f"leader basket ({n} tickers) pullback avg {depth_pct:.1f}% over {days:.0f} days — too deep or too long")
        elif pullback_ok:
            parts.append("leader pullback shallow")
        else:
            parts.append("leader pullback too deep or too extended")

        if dv:
            leader_pct = dv.get("leader_pct_higher_low")
            universe_pct = dv.get("universe_pct_higher_low")
            if leader_pct is not None and universe_pct is not None:
                if divergence_ok:
                    parts.append(f"leaders showing higher lows ({leader_pct:.0%}) while broader universe still declining ({universe_pct:.0%} with higher lows)")
                else:
                    lp = dv.get("leader_pivot", DIVERGENCE_PIVOT_LEADER)
                    up = dv.get("universe_pivot", DIVERGENCE_PIVOT_UNIVERSE)
                    parts.append(f"no leader divergence (leaders {leader_pct:.0%} higher lows, universe {universe_pct:.0%} — need leaders >{lp:.0%} and universe <{up:.0%})")
        elif divergence_ok:
            parts.append("leader divergence positive")
        else:
            parts.append("no leader divergence detected")

        if self.regime_open:
            # The gate is an OR (market_regime_gate.py) — ONE condition is
            # enough to open it. The old text appended "all three regime
            # conditions confirmed" unconditionally, so an OPEN driven by
            # pullback alone read as if all three had passed while the same
            # string listed two of them as failing. Name what actually fired.
            fired = []
            if ratio_ok:
                fired.append("new_high_low_ratio")
            if pullback_ok:
                fired.append("pullback_shallow")
            if divergence_ok:
                fired.append("leader_divergence")
            not_fired = [c for c in ("new_high_low_ratio", "pullback_shallow", "leader_divergence")
                         if c not in fired]
            verdict = (f"regime OPEN — {len(fired)}/{len(fired) + len(not_fired)} conditions met "
                       f"(need {REGIME_GATE_MIN_CONDITIONS}): {', '.join(fired)} fired")
            if not_fired:
                verdict += f". NOT fired: {', '.join(not_fired)}"
            reason = " — ".join(parts[:2]) + (f", {parts[2]}" if len(parts) > 2 else "") + f" — {verdict}"
        else:
            failing = []
            if not ratio_ok:
                failing.append("high/low ratio")
            if not pullback_ok:
                failing.append("pullback depth")
            if not divergence_ok:
                failing.append("leader divergence")
            reason = " — ".join(parts[:2]) + (f", {parts[2]}" if len(parts) > 2 else "") + f" — regime CLOSED ({', '.join(failing)} failed)"

        return {"result": result, "reason": reason}

    def _build_persistence_event(self, action, ticker, date_str, pipeline_state,
                                   position=None, exit_info=None):
        """Feature 8: builds a full event dict for write_event()."""
        event = {
            "event_id": str(uuid.uuid4()),
            "pipeline_run_id": self._pipeline_run_id,
            "date": date_str,
            "timestamp": datetime.now().isoformat(),
            "ticker": ticker,
            "action": action,
            "pipeline_state": pipeline_state,
            "position": position or {
                "entry_price": None, "entry_date": None, "shares": None,
                "position_value_egp": None, "stop_price": None,
                "initial_stop_distance_pct": None,
                "portfolio_equity_at_entry": None,
                "position_size_pct_of_portfolio": None,
            },
            "exit": exit_info or {
                "exit_price": None, "exit_date": None, "exit_reason": None,
                "exit_description": None, "pnl_egp": None, "pnl_pct": None,
                "holding_days": None, "portfolio_equity_at_exit": None,
            },
        }
        return event

    def _pipeline_state_from_receipt(self, receipt):
        """Extracts a pipeline_state dict from a decision receipt."""
        stages = receipt.get("stages", {})
        regime_result = "OPEN" if stages.get("market_regime_gate") == "PASS" else "CLOSED"
        hf = stages.get("hard_filter", "SKIPPED")
        hf_result = "PASS" if hf == "PASS" else ("FAIL" if "FAIL" in str(hf) else "SKIPPED")
        cat = stages.get("category_tagging", "SKIPPED")
        fund = stages.get("fundamentals_screen", "SKIPPED")
        cat_stage = stages.get("catalyst_check", "SKIPPED")
        entry = stages.get("entry_timing", "SKIPPED")
        return {
            "market_regime": {
                "result": regime_result,
                "reason": str(stages.get("market_regime_gate", "")),
            },
            "hard_filter": {
                "result": hf_result,
                "reason": str(hf),
            },
            "category_tag": {
                "result": str(cat),
                "reason": str(cat),
            },
            "fundamentals": {
                "result": str(fund),
                "overall_reason": str(fund),
            },
            "catalyst": {
                "result": receipt.get("catalyst_score", "SKIPPED"),
                "reason": receipt.get("catalyst_rationale", str(cat_stage)),
            },
            "entry_timing": {
                "result": str(entry),
                "reason": str(entry),
            },
        }

    def _emit_watchlist_event(self, action, d, receipt=None, exit_info=None,
                              position=None, reason=""):
        """Emits a persistence event and updates ticker_state."""
        ticker = d._name if hasattr(d, '_name') else str(d)
        date_str = str(self.datas[0].datetime.date(0))
        if receipt and "_pipeline_state" in receipt:
            pipeline_state = receipt["_pipeline_state"]
        elif receipt:
            pipeline_state = self._pipeline_state_from_receipt(receipt)
        else:
            pipeline_state = {
                "market_regime": {"result": "OPEN" if getattr(self, 'regime_open', False) else "CLOSED", "reason": reason},
            }

        event = self._build_persistence_event(
            action=action, ticker=ticker, date_str=date_str,
            pipeline_state=pipeline_state, position=position, exit_info=exit_info,
        )
        write_event(event)

        state_updates = {"last_updated": date_str}
        if action == "ADDED":
            state_updates["current_status"] = "WATCHING"
            state_updates["stage_reached"] = "hard_filter"
            state_updates["days_on_watchlist"] = 0
        elif action == "STAGE_FAILED":
            state_updates["current_status"] = "WATCHING"
            state_updates["failure_reason"] = reason
        elif action == "ENTERED":
            state_updates["current_status"] = "HELD"
            state_updates["stage_reached"] = "entry_timing"
            if position:
                state_updates["position_entry_price"] = position.get("entry_price")
                state_updates["position_entry_date"] = position.get("entry_date")
                state_updates["position_shares"] = position.get("shares")
                state_updates["position_current_stop"] = position.get("stop_price")
        elif action == "HELD":
            state_updates["current_status"] = "HELD"
        elif action in ("STOP_HIT", "EXIT_SIGNAL"):
            state_updates["current_status"] = "REMOVED"
            state_updates["position_entry_price"] = None
            state_updates["position_entry_date"] = None
            state_updates["position_shares"] = None
            state_updates["position_current_stop"] = None
            if exit_info and exit_info.get("pnl_egp") is not None:
                current = update_ticker_state(ticker, {})  # read current
                prev_trades = current.get("total_closed_trades") or 0
                prev_pnl = current.get("lifetime_pnl_egp") or 0.0
                state_updates["total_closed_trades"] = prev_trades + 1
                state_updates["lifetime_pnl_egp"] = prev_pnl + exit_info["pnl_egp"]
            state_updates["failure_reason"] = reason
        elif action == "REMOVED":
            state_updates["current_status"] = "REMOVED"
            wl_info = self._watchlist.get(ticker)
            if wl_info:
                from datetime import date as date_type
                try:
                    added = date_type.fromisoformat(wl_info["added_date"])
                    now = self.datas[0].datetime.date(0)
                    state_updates["days_on_watchlist"] = (now - added).days
                except (ValueError, TypeError):
                    pass
            state_updates["failure_reason"] = reason

        update_ticker_state(ticker, state_updates)
        return event

    def _update_catalyst_counters(self, catalyst_result):
        """
        Feature 7 (Operational Safety), Section 3.4: updates the
        catalyst-related ops-log counters from one real catalyst_check()
        result. Factored out as its own method (not inlined at the call
        site) specifically so a test fixture can call it directly with a
        SYNTHETIC catalyst_result (e.g. {"error_flag": True, ...}) --
        Fixture 2 needs catalyst_fallback_to_neutral=4 from 4 injected
        results, which would otherwise require 4 real tickers to
        organically reach Stage 5 (253+ bars of history, HIGH/MEDIUM
        disclosure priority, real news, etc.). Same "call the real update
        method directly" precedent as _update_defensive_mode() (Feature 4)
        and _update_streak_state() (Feature 4).
        """
        if catalyst_result.get("model_call_attempted"):
            self._catalyst_api_calls_made += 1
        # `or []` not `.get(k, [])`: the default only applies when the key is
        # ABSENT. A caller that sets "retry_log": None explicitly (the S&P
        # stub did) returned None and made this loop raise
        # "'NoneType' object is not iterable" — swallowed by the caller's
        # try/except, which silently killed catalyst_check in every backtest.
        retry_log = catalyst_result.get("retry_log") or []
        self._catalyst_api_errors += sum(1 for r in retry_log if r.get("outcome") in ("rate_limited", "error"))
        if catalyst_result.get("error_flag"):
            self._catalyst_fallback_to_neutral += 1

    def _run_scoring_queue(self, candidates):
        """
        Considerations.md Section 4 ("Watchlist Traffic Jam"): rank same-bar
        candidates by soft_score + vcp_quality + base_count_modifier, fill
        available slots highest-first. vcp_quality now reads the REAL
        entry_timing.evaluate_entry_timing() score (Feature 5) instead of a
        stub. base_count_modifier stays a 0 neutral stub -- "which numbered
        base is this across the ticker's whole Stage 2 run" detection is
        explicitly not built by Feature 5 either (see vcp_detection.py's
        score_vcp_quality() docstring and the JSON's own base_count_modifier.
        known_gap note) -- degraded but functional ranking key for that one
        component, same honest-interim-default pattern as
        risk_rules.profit_protection's flat-10% initial_stop_distance.
        """
        if not candidates:
            return
        open_count = sum(1 for d in self.datas if self.broker.getposition(d).size > 0)
        available_slots = max(self.p.target_position_count, 0) - open_count
        if available_slots <= 0:
            for d, receipt in candidates:
                receipt["final_verdict"] = "QUEUED_INSUFFICIENT_SLOTS"
            return

        def score_key(item):
            d, receipt = item
            soft_score = receipt.get("soft_score", 0)
            vcp_quality = receipt.get("vcp_quality_score", 0)  # real, Feature 5
            base_count_modifier = 0  # still a stub -- see this method's docstring
            return soft_score + vcp_quality + base_count_modifier

        ranked = sorted(candidates, key=score_key, reverse=True)
        for i, (d, receipt) in enumerate(ranked):
            if i < available_slots:
                if not self._guard_no_averaging_down(d):
                    receipt["final_verdict"] = "REJECTED_AT_no_averaging_down_guard"
                    continue
                size = self.getsizing(d, isbuy=True)
                if size > 0:
                    self.buy(data=d, size=size, exectype=bt.Order.Market)
                    self._new_entries_signaled += 1  # Feature 7 -- Section 3.4
                    receipt["final_verdict"] = "ENTERED"
                    self._pending_entry_receipt[d] = receipt
                else:
                    receipt["final_verdict"] = "REJECTED_AT_position_sizing_zero_shares"
            else:
                receipt["final_verdict"] = "QUEUED_INSUFFICIENT_SLOTS"

    def _manage_open_position(self, d):
        pos = self.broker.getposition(d)
        close = d.close[0]

        prev_highest = self.highest_close_since_entry.get(d, close)
        self._track_position_metrics(d)

        ticker = d._name
        if ticker not in self._held_event_written:
            self._held_event_written.add(ticker)
            entry_price = self.entry_price.get(d, pos.price)
            stop_order = self.stop_order.get(d)
            stop_price = stop_order.price if stop_order and hasattr(stop_order, 'price') else None
            equity = self.broker.getvalue()
            pos_value = pos.size * close
            self._emit_watchlist_event(
                "HELD", d,
                position={
                    "entry_price": round(entry_price, 4) if entry_price else None,
                    "entry_date": str(self.datas[0].datetime.date(0)),
                    "shares": pos.size,
                    "position_value_egp": round(pos_value, 2),
                    "stop_price": round(stop_price, 4) if stop_price else None,
                    "initial_stop_distance_pct": round(self.stop_distance_pct.get(d, HARD_MAX_STOP_PCT) * 100, 1),
                    "portfolio_equity_at_entry": round(equity, 2),
                    "position_size_pct_of_portfolio": round(pos_value / equity * 100, 1) if equity > 0 else 0,
                },
                reason="Position held — first holding day",
            )

        # Corporate Action Guard detection (bookkeeping-only).
        if len(d.close) > 1 and d.close[-1] != 0:
            gap = abs(d.open[0] / d.close[-1] - 1)
            if gap > CORPORATE_ACTION_GAP_PCT:
                self.flagged_for_review.append({
                    "date": str(d.datetime.date(0)), "ticker": d._name,
                    "gap_pct": gap, "reason": "overnight_gap_over_20pct",
                })

        # Feature 9: exit checks in priority order.
        # (Hard stop already handled by backtrader's broker before next().)
        if self._check_distribution_bar(d):
            return
        if self._check_stage3_transition(d):
            return

        # Breakeven stop swap.
        entry = self.entry_price.get(d)
        stop_dist = self.initial_stop_distance.get(d)
        if entry is not None and stop_dist is not None and not self.breakeven_done.get(d, False):
            unrealized_gain = close - entry
            if unrealized_gain >= BREAKEVEN_TRIGGER_MULT * stop_dist:
                old_stop = self.stop_order.get(d)
                if old_stop is not None and old_stop.alive():
                    self.cancel(old_stop)
                new_stop = self.sell(data=d, size=pos.size, exectype=bt.Order.Stop, price=entry)
                self._register_stop(d, new_stop)
                self.breakeven_done[d] = True
                self.stop_type[d] = "BREAKEVEN_STOP"
                # BUG FIX (found via Feature 9 Fixture 6 after Fix B):
                # do NOT let the trailing stop replace this order on the SAME
                # bar it was submitted. backtrader has not accepted a
                # same-bar order yet, so self.cancel() on it is a silent
                # no-op — the breakeven stop stays live, the trailing stop is
                # added alongside it, and BOTH fire on the next bar. That
                # double sell drove the position net short (observed: sells
                # at 100.00 and 109.65 on the same bar for a 166-share long).
                # The trailing stop simply resumes on the following bar.
                return

        # Feature 9: trailing stop (only active after breakeven).
        self._update_trailing_stop(d, prev_highest)

    def _check_distribution_bar(self, d):
        """Feature 9 Rule 3: largest single-day decline on heavy volume."""
        # Fix 6: never emit a sell for a position that is already flat or short.
        # A sell placed against size<=0 opens/extends a SHORT — this strategy is
        # long-only. Guarded at the top so the tracker cannot fire either.
        if self.broker.getposition(d).size <= 0:
            return False
        if d.open[0] <= 0:
            return False
        today_decline = (d.open[0] - d.close[0]) / d.open[0]
        if today_decline <= 0:
            return False
        largest = self.largest_decline_since_entry.get(d, 0)
        if today_decline > largest:
            self.largest_decline_since_entry[d] = today_decline
            avg_vol = self._avg_volume(d, LARGEST_DECLINE_VOLUME_WINDOW)
            if avg_vol is not None and d.volume[0] > avg_vol:
                # Flag regardless of holding age — Feature 4's largest-decline
                # flag is bookkeeping and predates Feature 9's sell.
                self.exit_candidates[d] = True

                # Feature 9 sensitivity fix: the book describes this signal
                # for a stock that has been ADVANCING for weeks. Before the
                # position has that history, only the hard stop applies.
                entry_bar = self.entry_bar_index.get(d)
                bars_held = (len(self) - entry_bar) if entry_bar is not None else 0
                if bars_held < DISTRIBUTION_BAR_MIN_HOLDING_DAYS:
                    return False

                pos = self.broker.getposition(d)
                old_stop = self.stop_order.get(d)
                if old_stop and old_stop.alive():
                    self.cancel(old_stop)
                self.exit_reason[d] = "DISTRIBUTION_BAR"
                self._exit_signals_flagged += 1
                self.sell(data=d, size=pos.size, exectype=bt.Order.Market)
                return True
        return False

    def _check_stage3_transition(self, d):
        """
        Feature 9 Rule 4: close below 200-day MA on heavy volume.

        DISABLED by default — see STAGE3_TRANSITION_EXIT_ENABLED. The rule is
        kept intact behind the flag rather than removed, because it is
        book-cited (ch05) and only the measured outcome argues against it.
        """
        if not STAGE3_TRANSITION_EXIT_ENABLED:
            return False
        # Fix 6: same long-only guard as _check_distribution_bar.
        if self.broker.getposition(d).size <= 0:
            return False
        bars = self.history[d]
        if len(bars) < 200:
            return False
        closes_200 = [b["Close"] for b in list(bars)[-200:]]
        sma_200 = sum(closes_200) / 200
        close = d.close[0]
        if close < sma_200:
            avg_vol = self._avg_volume(d, LARGEST_DECLINE_VOLUME_WINDOW)
            if avg_vol is not None and d.volume[0] > avg_vol:
                pos = self.broker.getposition(d)
                old_stop = self.stop_order.get(d)
                if old_stop and old_stop.alive():
                    self.cancel(old_stop)
                self.exit_reason[d] = "STAGE3_TRANSITION"
                self.exit_candidates[d] = True
                self._exit_signals_flagged += 1
                self.sell(data=d, size=pos.size, exectype=bt.Order.Market)
                return True
        return False

    def _update_trailing_stop(self, d, prev_highest=None):
        """Feature 9 Rule 5: after breakeven, trail stop up using 50-day MA floor."""
        if not self.breakeven_done.get(d, False):
            return
        pos = self.broker.getposition(d)
        if pos.size <= 0:
            return
        close = d.close[0]
        highest_before = prev_highest if prev_highest is not None else self.highest_close_since_entry.get(d, close)
        if close > highest_before:
            # Two independent floors; the HIGHER one wins.
            #   1. peak floor  — caps how much of the run can be handed back.
            #      Always available (needs only the new high), so the trailing
            #      stop now arms even before 50 bars of history exist.
            #   2. sma_50 floor — the spec'd Rule 5 level, kept unchanged.
            # The peak floor is what fixes the TSLA/PANW give-back: on a stock
            # that spikes then decays, sma_50 trails so far below the peak that
            # it never clears the breakeven stop, and the stop never ratchets.
            candidate_stops = [close * (1 - TRAILING_STOP_MAX_GIVEBACK_PCT)]

            bars = self.history[d]
            if len(bars) >= 50:
                closes_50 = [b["Close"] for b in list(bars)[-50:]]
                sma_50 = sum(closes_50) / 50
                candidate_stops.append(sma_50 * (1 - TRAILING_STOP_BUFFER_PCT))

            new_stop_price = max(candidate_stops)

            # Never trail the stop above the current close — that would be an
            # instant fill at a price the market has not traded through.
            if new_stop_price >= close:
                return

            current_stop_order = self.stop_order.get(d)
            current_stop_price = current_stop_order.price if current_stop_order and hasattr(current_stop_order, 'price') else 0
            if new_stop_price > current_stop_price:
                if current_stop_order and current_stop_order.alive():
                    self.cancel(current_stop_order)
                new_order = self.sell(data=d, size=pos.size, exectype=bt.Order.Stop, price=new_stop_price)
                self._register_stop(d, new_order)
                self.stop_type[d] = "TRAILING_STOP"

    def _track_position_metrics(self, d):
        """Feature 9: update per-position high/low every bar."""
        close = d.close[0]
        prev_high = self.highest_close_since_entry.get(d, close)
        prev_low = self.lowest_close_since_entry.get(d, close)
        self.highest_close_since_entry[d] = max(prev_high, close)
        self.lowest_close_since_entry[d] = min(prev_low, close)

    @staticmethod
    def _avg_volume(d, window):
        vols = d.volume.get(size=window)
        if vols is None or len(vols) < window:
            return None
        return sum(vols) / len(vols)

    def _register_stop(self, d, order):
        """Record a stop order so it can never be orphaned in the broker."""
        self.stop_order[d] = order
        self.all_stop_orders.setdefault(d, []).append(order)

    def _cancel_all_stops(self, d):
        """
        Cancel every stop still alive for this data and forget them.

        Called on trade close. Cancelling only self.stop_order[d] is not
        enough — any stop that was replaced without being cancelled, on any
        code path, would otherwise outlive the position.
        """
        cancelled = 0
        for order in self.all_stop_orders.get(d, []):
            if order is not None and order.alive():
                self.cancel(order)
                cancelled += 1
        self.all_stop_orders.pop(d, None)
        return cancelled

    def _atr_pct(self, d, period=DISTRIBUTION_BAR_ATR_PERIOD):
        """
        ATR(period) expressed as a FRACTION of price, computed from the bars
        already in history (i.e. strictly before the entry bar when called
        from notify_order, since next() appends the current bar after fills).

        Normalizing to a fraction is required, not cosmetic: the distribution
        bar compares against today_decline = (open - close) / open, which is
        dimensionless. A raw ATR in price units would be ~2.0 for a $100
        stock and would make the floor unreachable.

        Returns None when there is not enough history for `period` true
        ranges (needs period + 1 bars for the first prev_close).
        """
        bars = list(self.history[d])
        if len(bars) < period + 1:
            return None
        window = bars[-(period + 1):]
        true_ranges = []
        for i in range(1, len(window)):
            hi, lo = window[i]["High"], window[i]["Low"]
            prev_close = window[i - 1]["Close"]
            true_ranges.append(max(hi - lo, abs(hi - prev_close), abs(lo - prev_close)))
        atr = sum(true_ranges) / len(true_ranges)
        ref_price = window[-1]["Close"]
        if ref_price <= 0:
            return None
        return atr / ref_price

    def _flush_decision_receipts_for_date(self, date):
        if not self.decision_receipts:
            return
        # Action 2: honour the decision_receipts_dir PARAM instead of the
        # module-level RECEIPTS_DIR. The param already existed but was never
        # read here, so every run wrote to the same global directory and two
        # concurrent runs interleaved receipts (and --clear-receipts in one
        # deleted the other's). Runners now pass a market-scoped directory.
        receipts_dir = Path(self.p.decision_receipts_dir)
        receipts_dir.mkdir(parents=True, exist_ok=True)
        path = receipts_dir / f"decision_receipts_{date.strftime('%Y%m%d')}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            # Fix 5 — run isolation. Receipt files are opened in APPEND mode and
            # are named by SIMULATED date, so consecutive runs interleave in the
            # same file with nothing to tell them apart (the Q17 audit found 877
            # DELL receipts and 6 ENTERED verdicts where one run should produce
            # far fewer). One RUN_START marker per file per run makes runs
            # separable after the fact: split on RUN_START, keep the segment
            # whose run_id you care about.
            if path not in self._receipt_files_marked:
                self._receipt_files_marked.add(path)
                f.write(json.dumps({
                    "_marker": "RUN_START",
                    "run_id": self._pipeline_run_id,
                    "wall_clock_utc": datetime.now(timezone.utc).isoformat(),
                    "period": self.p.run_period,
                    "simulated_date": date.strftime("%Y-%m-%d"),
                }) + "\n")
            for r in self.decision_receipts:
                f.write(json.dumps(r) + "\n")
        self.decision_receipts = []

    # ------------------------------------------------------------------
    # Order / trade lifecycle
    # ------------------------------------------------------------------

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status == order.Completed:
            d = order.data
            if order.isbuy():
                pos = self.broker.getposition(d)
                is_addon = pos.size > order.executed.size

                # N-3 fix: cancel existing stop before placing a consolidated
                # one — prevents two competing stops for different sizes.
                old_stop = self.stop_order.get(d)
                if old_stop is not None and old_stop.alive():
                    self.cancel(old_stop)

                # FIX B: the receipt carries the VCP pivot this entry was
                # triggered on. Popped BEFORE the stop is placed (it used to be
                # read afterwards, purely for the ENTERED event) so the stop can
                # be anchored to the pivot instead of a flat 10%.
                receipt = self._pending_entry_receipt.pop(d, None)

                if is_addon:
                    blended_price = pos.price
                    self.entry_price[d] = blended_price
                    # Keep the add-on on the SAME risk fraction as the original
                    # entry rather than snapping back to the 10% ceiling.
                    sd_pct = self.stop_distance_pct.get(d, HARD_MAX_STOP_PCT)
                    self.initial_stop_distance[d] = blended_price * sd_pct
                else:
                    self.entry_price[d] = order.executed.price
                    self.entry_date[d] = self.datas[0].datetime.date(0)
                    self.entry_bar_index[d] = len(self)
                    entry_px = order.executed.price
                    pivot_price = receipt.get("pivot_price") if receipt else None
                    if pivot_price and pivot_price > 0:
                        technical_stop = pivot_price * PIVOT_STOP_BUFFER
                        sd_pct = (entry_px - technical_stop) / entry_px
                        sd_pct = max(STOP_DISTANCE_MIN, min(STOP_DISTANCE_MAX, sd_pct))
                    else:
                        sd_pct = NO_PIVOT_STOP_DISTANCE
                    self.stop_distance_pct[d] = sd_pct
                    self.initial_stop_distance[d] = entry_px * sd_pct
                    self.highest_close_since_entry[d] = order.executed.price
                    self.lowest_close_since_entry[d] = order.executed.price
                    # Feature 9 sensitivity fix: seed the largest-decline
                    # tracker at 1.5x the stock's normal daily range instead
                    # of 0.0, so routine noise is not "the largest decline
                    # since entry". Falls back to 0.0 only when history is
                    # too short for ATR — the min-holding guard still covers
                    # that case.
                    atr_pct = self._atr_pct(d)
                    self.largest_decline_since_entry[d] = max(
                        (atr_pct * DISTRIBUTION_BAR_ATR_FLOOR_MULTIPLE) if atr_pct is not None else 0.0,
                        0.0,
                    )
                    self.breakeven_done[d] = False
                    if self._spy_data is not None:
                        self.spy_price_at_entry[d] = self._spy_data.close[0]

                # FIX B: stop at the pivot-derived distance, not a flat 10%.
                stop_pct = self.stop_distance_pct.get(d, HARD_MAX_STOP_PCT)
                stop_price = self.entry_price[d] * (1 - stop_pct)
                new_stop = self.sell(data=d, size=pos.size, exectype=bt.Order.Stop, price=stop_price)
                self._register_stop(d, new_stop)
                self.stop_type[d] = "STOP_LOSS"

                # Feature 9: emit ENTERED only on confirmed fill.
                # (receipt was popped above, before stop placement.)
                ticker = d._name
                fill_price = order.executed.price
                fill_size = abs(order.executed.size)
                equity = self.broker.getvalue()
                pos_value = fill_price * fill_size
                self._emit_watchlist_event(
                    "ENTERED", d, receipt=receipt,
                    position={
                        "entry_price": round(fill_price, 4),
                        "entry_date": str(self.datas[0].datetime.date(0)),
                        "shares": fill_size,
                        "position_value_egp": round(pos_value, 2),
                        "stop_price": round(stop_price, 4),
                        "initial_stop_distance_pct": round(self.stop_distance_pct.get(d, HARD_MAX_STOP_PCT) * 100, 1),
                        "portfolio_equity_at_entry": round(equity, 2),
                        "position_size_pct_of_portfolio": round(pos_value / equity * 100, 1) if equity > 0 else 0,
                    },
                )
                self._watchlist.pop(ticker, None)
            else:
                # Sell completed — determine exit reason.
                our_stop_order = self.stop_order.get(d)
                is_our_stop = our_stop_order is not None and our_stop_order.ref == order.ref
                self.pending_trade_was_stop[d] = is_our_stop
                # FIX 2: this is the price the exit ACTUALLY executed at — the
                # same value backtrader uses for trade.pnl.
                self.exit_fill_price[d] = order.executed.price
                if is_our_stop and d not in self.exit_reason:
                    self.exit_reason[d] = self.stop_type.get(d, "STOP_LOSS")

                # Safety net: this strategy is long-only. If a sell ever
                # leaves a negative position, an unintended short was
                # opened — flatten it immediately and flag for review
                # rather than carrying it silently to the end of the run.
                pos_after = self.broker.getposition(d)
                if pos_after.size < 0:
                    self._cancel_all_stops(d)
                    self.buy(data=d, size=abs(pos_after.size), exectype=bt.Order.Market)
                    self.flagged_for_review.append({
                        "date": str(d.datetime.date(0)), "ticker": d._name,
                        "shares": abs(pos_after.size),
                        "reason": "unintended_short_position_auto_flattened",
                    })

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        d = trade.data
        was_stopped_out = self.pending_trade_was_stop.pop(d, False)
        was_win = trade.pnl > 0

        # [CORRECTED -- logic error, same root cause as _manage_open_position's
        # gap check above]: overnight gap = today's OPEN vs yesterday's CLOSE,
        # not today's CLOSE vs yesterday's CLOSE.
        gap = abs(d.open[0] / d.close[-1] - 1) if len(d.close) > 1 and d.close[-1] != 0 else 0
        corporate_action_suspected = gap > CORPORATE_ACTION_GAP_PCT and was_stopped_out

        if not corporate_action_suspected:
            self.recent_closed_trades.append({
                "date": str(d.datetime.date(0)), "ticker": d._name,
                "pnl": trade.pnl, "was_stopped_out": was_stopped_out, "was_win": was_win,
            })
            self._update_streak_state(was_stopped_out, was_win)
            self._update_reentry_state(was_win)
            self._update_defensive_mode()
        else:
            self.flagged_for_review.append({
                "date": str(d.datetime.date(0)), "ticker": d._name,
                "reason": "corporate_action_suspected_excluded_from_streak_tracking",
            })

        # Feature 9: compute exit metrics before cleaning up state.
        ticker = d._name
        entry_p = self.entry_price.get(d, 0)
        # FIX 2: prefer the real fill price over the bar close. Falls back to
        # d.close[0] only if no fill was recorded (defensive; every closing
        # SELL passes through notify_order first).
        exit_price = self.exit_fill_price.pop(d, None)
        if exit_price is None:
            exit_price = d.close[0]
        pnl_pct = ((exit_price - entry_p) / entry_p * 100) if entry_p > 0 else 0
        exit_equity = self.broker.getvalue()

        highest = self.highest_close_since_entry.get(d, entry_p)
        lowest = self.lowest_close_since_entry.get(d, entry_p)
        max_gain_pct = ((highest - entry_p) / entry_p) if entry_p > 0 else 0
        max_dd_pct = ((lowest - entry_p) / entry_p) if entry_p > 0 else 0
        stock_return_pct = ((exit_price - entry_p) / entry_p) if entry_p > 0 else 0

        spy_return_pct = 0.0
        if self._spy_data is not None and d in self.spy_price_at_entry:
            spy_entry = self.spy_price_at_entry[d]
            spy_exit = self._spy_data.close[0]
            spy_return_pct = ((spy_exit - spy_entry) / spy_entry) if spy_entry > 0 else 0
        alpha_pct = stock_return_pct - spy_return_pct

        entry_dt = self.entry_date.get(d)
        exit_dt = self.datas[0].datetime.date(0)
        holding_days = (exit_dt - entry_dt).days if entry_dt else None

        reason_code = self.exit_reason.pop(d, "STOP_LOSS" if was_stopped_out else "EXIT_SIGNAL")
        if corporate_action_suspected:
            reason_code += "_CORPORATE_ACTION"

        self.position_exit_metrics[d] = {
            "holding_days": holding_days,
            "exit_reason": reason_code,
            "max_unrealized_gain_pct": round(max_gain_pct, 6),
            "max_drawdown_during_hold_pct": round(max_dd_pct, 6),
            "stock_return_pct": round(stock_return_pct, 6),
            "spy_return_pct": round(spy_return_pct, 6),
            "alpha_vs_spy_pct": round(alpha_pct, 6),
        }

        action = "STOP_HIT" if was_stopped_out else "EXIT_SIGNAL"
        exit_desc = f"{reason_code}: price={exit_price:.2f}"
        self._emit_watchlist_event(
            action, d,
            exit_info={
                "exit_price": round(exit_price, 4),
                "exit_date": str(exit_dt),
                "exit_reason": reason_code,
                "exit_description": exit_desc,
                "pnl_egp": round(trade.pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "holding_days": holding_days,
                "portfolio_equity_at_exit": round(exit_equity, 2),
                # Fix 4 — FRACTIONS, not percentages. These were written x100
                # here while position_exit_metrics/trade_log.csv wrote the raw
                # fraction, so the same field meant -8.35 in one consumer and
                # -0.0835 in the other. Fractions everywhere now; the only
                # percentage left is pnl_pct, which was always a percentage.
                "max_unrealized_gain_pct": round(max_gain_pct, 6),
                "max_drawdown_during_hold_pct": round(max_dd_pct, 6),
                "stock_return_pct": round(stock_return_pct, 6),
                "spy_return_pct": round(spy_return_pct, 6),
                "alpha_vs_spy_pct": round(alpha_pct, 6),
            },
            reason=reason_code,
        )
        self._held_event_written.discard(ticker)

        # Cancel every stop still live for this data BEFORE dropping the
        # references. Popping self.stop_order only forgets the order — the
        # broker keeps it working forever otherwise.
        self._cancel_all_stops(d)

        for state_dict in (self.entry_price, self.entry_date, self.entry_bar_index,
                            self.initial_stop_distance, self.stop_distance_pct,
                            self.exit_fill_price,
                            self.stop_order, self.stop_type, self.breakeven_done,
                            self.highest_close_since_entry, self.lowest_close_since_entry,
                            self.largest_decline_since_entry, self.exit_candidates,
                            self.spy_price_at_entry):
            state_dict.pop(d, None)

        # P16: Ledger reconciliation — verify broker.getvalue() matches
        # cash + sum(open positions marked to market) after every trade close.
        self._check_ledger_reconciliation()

    def _check_ledger_reconciliation(self):
        cash = self.broker.getcash()
        positions_value = sum(
            self.broker.getposition(d).size * d.close[0]
            for d in self.datas
            if self.broker.getposition(d).size != 0
        )
        reported_equity = self.broker.getvalue()
        reconstructed = cash + positions_value
        drift = abs(reported_equity - reconstructed)
        if drift >= 0.01:
            event = {
                "date": str(self.datas[0].datetime.date(0)),
                "reported_equity": reported_equity,
                "reconstructed_equity": reconstructed,
                "cash": cash,
                "positions_value": positions_value,
                "drift": drift,
            }
            self._ledger_drift_events.append(event)

    def _update_streak_state(self, was_stopped_out, was_win):
        """Section 2.1, exact triggers."""
        if was_stopped_out:
            self.consecutive_stops += 1
            self.streak_consecutive_winners = 0
            for count, step_idx in sorted(STREAK_STEP_DOWN_TRIGGERS.items()):
                if self.consecutive_stops >= count and step_idx > self.streak_step_index:
                    self.streak_step_index = step_idx
            self.current_streak_step = STREAK_STEPS[self.streak_step_index]
        else:
            self.consecutive_stops = 0
            if was_win and self.streak_step_index > 0:
                self.streak_consecutive_winners += 1
                if self.streak_consecutive_winners >= STREAK_RECOVERY_WINNERS_NEEDED:
                    self.streak_step_index = max(0, self.streak_step_index - 1)
                    self.current_streak_step = STREAK_STEPS[self.streak_step_index]
                    self.streak_consecutive_winners = 0
            elif not was_win:
                self.streak_consecutive_winners = 0

    def _update_reentry_state(self, was_win):
        """Section 2.2, exact rule."""
        if not self.is_reentry_from_cash:
            return
        if was_win:
            self.pilot_consecutive_winners += 1
            if self.pilot_consecutive_winners >= REENTRY_PILOT_WINNERS_TO_GRADUATE:
                self.is_reentry_from_cash = False
                self.pilot_consecutive_winners = 0
        else:
            self.pilot_consecutive_winners = 0

    # ------------------------------------------------------------------
    # Feature 7 (Operational Safety) -- Daily Operations Log.
    # ------------------------------------------------------------------

    def stop(self):
        """
        backtrader calls this once after all bars have been processed --
        guarantees the ops log reflects the complete run, not an
        intermediate state (Section 3.6). Reaching stop() at all is itself
        the signal that the run completed (an unhandled exception earlier
        in the run would have propagated out of cerebro.run() and stop()
        would never be called) -- see _write_ops_log()'s own note on
        run_completed.
        """
        self._write_ops_log()

    def _write_ops_log(self):
        """
        Writes daily_ops_log/ops_YYYYMMDD.json -- Section 3.2/3.3. Uses
        the REAL wall-clock date (datetime.now(), not the last processed
        bar's date) as run_date: this log answers "did TODAY's run
        complete", matching a real daily cron job's framing (Section 3.1),
        not a backtest's synthetic bar dates. Overwrites any existing file
        for the same calendar day (Section 3.2: "the latest run's data is
        the relevant one") -- plain "w" mode, not append.
        """
        run_date = datetime.now().date()

        # [CORRECTED -- logic error caught by smoke-testing before writing
        # the formal fixtures] Section 3.4's literal suggestion,
        # "len(self.broker.positions)", is NOT the same thing as "open
        # positions at end of run" (the field's own stated meaning) once a
        # strategy calls self.broker.getposition(d) broadly -- confirmed
        # empirically with a standalone probe: backtrader lazily creates a
        # Position entry (size=0) in broker.positions the FIRST TIME
        # getposition() is called for a data feed, even if no trade ever
        # happens. KashifStrategy's next() calls getposition() for EVERY
        # ticker EVERY bar (to check pos.size > 0 before deciding exit vs.
        # entry-pipeline), so a literal len(self.broker.positions) would
        # equal the total ticker count scanned, not the count actually
        # holding a position. Filtered to nonzero-size entries instead.
        positions_held = sum(1 for pos in self.broker.positions.values() if pos.size != 0)

        http_errors = get_error_counters()

        if self._catalyst_fallback_to_neutral > CATALYST_FALLBACK_WARNING_THRESHOLD:
            # Section 3.5 -- console-only, informational, never blocks the
            # pipeline or raises.
            print(
                f"WARNING: {self._catalyst_fallback_to_neutral} tickers fell back to NEUTRAL due to "
                f"API rate limits today. Consider adding inter-call sleep. "
                f"See known_gaps_and_todos in minervini_sepa_v1_strategy_config.json."
            )

        ops_log = {
            "run_date": run_date.isoformat(),
            "run_completed": True,
            "tickers_scanned": self._tickers_scanned,
            "tickers_passing_hard_filter": self._tickers_passing_hard_filter,
            "tickers_reaching_catalyst_check": self._tickers_reaching_catalyst_check,
            "catalyst_api_calls_made": self._catalyst_api_calls_made,
            "catalyst_api_errors": self._catalyst_api_errors,
            "catalyst_fallback_to_neutral": self._catalyst_fallback_to_neutral,
            "arabfinance_fetch_errors": http_errors["arabfinance_fetch_errors"],
            "google_news_rss_errors": http_errors["google_news_rss_errors"],
            "new_entries_signaled": self._new_entries_signaled,
            "exit_signals_flagged": self._exit_signals_flagged,
            "kill_switch_active": kashif_config.KILL_SWITCH,
            "positions_held": positions_held,
            "portfolio_equity_egp": self.broker.getvalue(),
            "pipeline_errors": self._pipeline_errors,
            "ledger_drift_events": self._ledger_drift_events,
        }

        os.makedirs(OPS_LOG_DIR, exist_ok=True)
        path = os.path.join(OPS_LOG_DIR, f"ops_{run_date.strftime('%Y%m%d')}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(ops_log, f, indent=2)

        return ops_log
