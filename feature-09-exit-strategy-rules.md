# Kashif — Engineering Rules: Exit Strategy (Feature 9)

*Source of truth for Claude Code. Every rule in this file has a direct
book citation. Nothing invented. If a rule has no book citation, it is
not in this file.*

---

## 0. The Problem This Fixes

The S&P 500 IS backtest produced 0 winning closed trades. 6 positions
sat open for the entire 2-year period accumulating unrealized gains that
were never locked in. The system correctly cuts losses but has no
mechanism to ever close a winner.

The root cause: exits were only implemented as stop-losses. The book
describes a complete exit system based on volume-confirmed distribution
signals — the same logic as entries but in reverse. Price alone is not
the exit trigger. Volume confirming the price move is what the book
describes.

---

## 1. Source of truth — book citations only

All rules come directly from these chapter notes:
- `ch05-notes.md` — Stage 3 transition signals, distribution bar
- `ch12-notes.md` — stop-loss, breakeven protection
- `ch13-notes.md` — profit protection, trailing concept
- `ch09-notes.md` — leadership breakdown as early warning

---

## 2. The Book's Exit Rules — In Order

### Rule 1 — Hard Stop-Loss (ch12) — ALREADY IMPLEMENTED

**Book**: "Set an absolute maximum line in the sand of no more than 10%
on the downside."

```
if current_price <= stop_price: SELL at next available open price
```

Already working. Do not change.

### Rule 2 — Breakeven Protection (ch13) — ALREADY IMPLEMENTED

**Book**: "Once an open position's gain reaches ~3x the original risk,
move the stop to at least breakeven."

```
if unrealized_gain >= 3 * initial_stop_distance:
    stop_price = entry_price  (move to breakeven, never below)
```

Already implemented. Verify it is actually firing by checking whether
any of the 6 open positions at IS end have their stop above entry price.

### Rule 3 — Distribution Bar Exit (ch05) — MISSING, MUST BUILD

**Book (exact language from ch05-notes.md)**:
"The single largest daily or weekly price decline since the Stage 2
advance began, on heavy volume, is treated as a sell signal — even if
it happens right after a good earnings report. Price action is trusted
over headline fundamentals."

This is the PRIMARY exit signal. Not a trailing stop. Not a percentage
below a moving average. The combination of:
1. Largest single-day price decline since entry began
2. On above-average volume (above 50-day average — already in spec)

Both must be true simultaneously. Either alone is not the signal.

```python
# Track since entry:
largest_decline_since_entry = 0.0  # updated daily

# Each bar for held positions:
todays_decline = (open_price - close_price) / open_price  # intraday decline
if todays_decline > largest_decline_since_entry:
    if volume > volume_50day_average:
        # Distribution bar confirmed — SELL
        largest_decline_since_entry = todays_decline
        place_sell_order()
    else:
        # Largest decline but no volume — update tracker only, do not sell
        largest_decline_since_entry = todays_decline
```

**Why volume matters**: a large price drop on light volume is a healthy
shakeout — weak holders selling, strong hands holding. A large price drop
on heavy volume means institutions are distributing (selling to retail
buyers). The book explicitly says to trust price action + volume over
fundamental news. This is the same logic as VCP entry (volume drying up
= accumulation, volume surging on breakout = confirmation) but for exits.

### Rule 4 — Stage 3 Transition (ch05) — MISSING, MUST BUILD

**Book (ch05-notes.md)**: Stage 3 is characterized by:
- "Increased volatility"
- "The largest single-day or single-week decline since the Stage 2
  advance began"
- "Price starting to whip around the 200-day average"
- "That average flattening/rolling over"

When a held position's price crosses below its 200-day MA on heavy
volume — this is Stage 3 confirmation. Exit.

```python
if close < sma_200 and volume > volume_50day_average:
    # Stage 3 transition confirmed — SELL
    place_sell_order()
```

Note: this is a different signal from the Trend Template hard filter.
The Trend Template prevents ENTRY when below the 200-day MA. This rule
triggers EXIT when a held position crosses below it on volume.

### Rule 5 — Post-Breakeven Trailing Stop (ch13) — ALREADY IN SPEC

**Book (ch13-notes.md)**: "After that [breakeven is protected], continue
looking for opportunities to sell into strength and lock in more of the
gain as it runs."

The book does NOT specify a mechanical trailing stop formula. It says
"look for opportunities." The implementation must be volume-based, not
purely price-based, consistent with the distribution bar logic above.

**Implementation**: after breakeven is protected (Rule 2 has fired),
raise the stop whenever the stock makes a new high. The stop trails up
but never down. When a distribution bar fires (Rule 3), sell.

```python
# After breakeven trigger:
if close > highest_close_since_entry:
    highest_close_since_entry = close
    # Raise stop: use the 50-day MA as the trailing floor
    # Book does not give a formula — 50-day MA is the closest
    # book-referenced level below price during a healthy Stage 2 advance
    new_stop = max(current_stop, sma_50 * 0.97)  # 3% below 50-day MA
    if new_stop > current_stop:
        current_stop = new_stop
        update_stop_order(new_stop)
```

**Note on the 3% buffer and 50-day MA**: the book says in Stage 2
"price is above the 50-day MA" (tt_5 in the Trend Template). When
price falls below the 50-day MA it signals Stage 2 may be ending.
Using the 50-day MA as a trailing floor is the closest book-grounded
level. The 3% buffer prevents premature exit on a brief intraday dip
below the MA. Flag this as a calibration parameter — not a settled number.

```python
TRAILING_STOP_BUFFER_PCT = 0.03  # 3% below 50-day MA — calibration parameter
```

---

## 3. Exit Priority Order

When multiple exit signals are present on the same bar, execute in this
order:

1. Hard stop-loss (Rule 1) — always first, non-negotiable
2. Distribution bar (Rule 3) — primary trend exit signal
3. Stage 3 transition / 200-day MA break on volume (Rule 4)
4. Trailing stop (Rule 5) — catches slow deterioration

---

## 4. What the Book Does NOT Say About Exits

These were in the previous version and are removed because they are
inventions, not book rules:

- **ATR trailing stop (1.5× or 2× ATR)**: not in the book. The book
  never mentions ATR for exits. Removed.
- **P/E expansion at 2.5×**: the book mentions general overextension
  caution but never gives a specific ratio. This was an invented number.
  Kept as a soft flag only, not an exit trigger.
- **Post-earnings reaction**: the book mentions this as context, not
  a mechanical exit rule. Kept as a soft flag only.

---

## 5. The ENTERED Event Timing Fix

**Current bug**: ENTERED event is logged when the pipeline decides to
attempt a buy — before the broker confirms. This caused 137 ENTERED
events vs 18 actual buy orders.

**Fix**: move write_event(ENTERED) from _run_scoring_queue() to
notify_order() — only write ENTERED when:
```python
order.status == Order.Completed AND order.isbuy()
```

The position fields (entry_price, shares, stop_price) must come from
the confirmed fill, not from the intended order.

---

## 6. New Position Metrics

Track these for every held position, reported on exit:

**Max unrealized gain during hold**
```python
max_unrealized_gain_pct = (highest_close_since_entry - entry_price) / entry_price
```
Why: shows how much profit was available vs. captured. A stock that ran
+40% then hit the stop at -8% is a different failure from one that never moved.

**Stock vs SPY during holding period**
```python
stock_return = (exit_price - entry_price) / entry_price
spy_return = (spy_price_at_exit - spy_price_at_entry) / spy_price_at_entry
alpha = stock_return - spy_return
```
Why: a stock losing -5% while SPY lost -10% in the same period is an
outperformer. This tells you if the stock was worth holding vs. the index.

**Max drawdown during hold**
```python
max_drawdown_pct = (lowest_close_since_entry - entry_price) / entry_price
```
Why: shows the worst moment before stop or exit. High drawdown on a
stopped-out position means the stop should have been tighter.

---

## 7. Updated trade_log.csv Schema

Add to SELL rows only (BUY rows leave these null):

```
date, ticker, action, shares, price, commission, slippage, pnl,
portfolio_value, holding_days, exit_reason,
max_unrealized_gain_pct, max_unrealized_gain_date,
max_drawdown_during_hold_pct, max_drawdown_during_hold_date,
stock_return_pct, spy_return_pct, alpha_vs_spy_pct
```

`exit_reason` must be one of:
- "STOP_LOSS" — hard stop fired
- "BREAKEVEN_STOP" — stop moved to breakeven, then hit
- "DISTRIBUTION_BAR" — largest decline on heavy volume
- "STAGE3_TRANSITION" — price below 200-day MA on heavy volume
- "TRAILING_STOP" — trailing stop (50-day MA floor) hit

---

## 8. Testing Standard

**Fixture 1 — Distribution bar fires correctly**:
Synthetic position: enter at 100, price rises to 150 over 30 bars.
On bar 31: price drops 8% (largest single-day drop since entry) on
volume 1.8× 50-day average. SELL must fire. exit_reason = "DISTRIBUTION_BAR".

**Fixture 2 — No sell on large drop without volume**:
Same setup. Bar 31: price drops 8% (largest drop) on volume 0.6×
50-day average. No sell. Largest decline tracker updates to 8%,
but no exit because volume did not confirm.

**Fixture 3 — Stage 3 transition fires**:
Synthetic position: enter at 100. Price falls below 200-day MA on
bar 20, volume 1.5× average. SELL fires. exit_reason = "STAGE3_TRANSITION".
If price falls below 200-day MA on light volume (0.4×), no sell.

**Fixture 4 — Trailing stop raises after new high**:
Enter at 100, stop at 90. Breakeven fires at 130 (3× gain of 10).
Stop moves to 100. Price continues to 180 — trailing stop should now
be above 100 (at 50-day MA - 3%). Price then falls through trailing stop.
SELL fires at a profit. exit_reason = "TRAILING_STOP".

**Fixture 5 — ENTERED event timing**:
Buy order submitted. Before notify_order() confirms: no ENTERED event
in watchlist_history.jsonl. After confirm: ENTERED event with actual
fill price, not intended price.

**Fixture 6 — New metrics populated on exit**:
Position that ran +30% then was stopped at -5%:
- max_unrealized_gain_pct = 0.30
- stock_return_pct = -0.05
- alpha depends on SPY return during same period
All three fields populated in SELL row of trade_log.csv.

---

## 9. Deliverables Checklist

- [ ] kashif_strategy.py:
  - `_check_distribution_bar(data)` — Rule 3
  - `_check_stage3_transition(data)` — Rule 4
  - `_update_trailing_stop(data)` — Rule 5, 50-day MA floor
  - `_track_position_metrics(data)` — max gain, max drawdown, SPY comparison
  - Move write_event(ENTERED) to notify_order() on confirmed fill
  - Populate new trade_log.csv columns on exit

- [ ] test_feature9_known_answer.py — 6 fixtures above
- [ ] Full regression sweep after — all existing suites must pass
- [ ] Rerun run_backtest_sp500.py IS after all changes

---

## Change Log

- v1 — first draft used ATR trailing stop. Not from the book.
- v2 — complete rewrite. Rules now come directly from ch05 and ch13
  chapter notes only. Distribution bar (price + volume) is the primary
  exit signal, matching the book's actual language. ATR trailing stop
  removed. 50-day MA floor used as trailing level because it is
  referenced in the Trend Template as the key support level during
  Stage 2 advances.
