# Kashif — Engineering Rules: Risk Rules & Position Sizing (Feature 4)

*Source of truth for Claude Code on this feature. Supersedes verbal instructions given in chat — if chat and this file disagree, this file wins until it's explicitly updated. Living document; update it when something new is found, don't just remember a verbal correction.*

**Status:** Ready to build. Six real gaps reviewed and resolved in v0.17 of the JSON, plus four more resolved in this document (vague step-triggers, vague pilot-sizing, ambiguous entry-price definition, and unspecified "capital" base). Architecture updated in v2 to build on top of backtrader per the Considerations_ document — this changes the implementation approach, not the Minervini rules themselves.

---

## 0. What this document is for

Same relationship as Features 1–3: the corrected, fully-specified spec for `risk_rules` and `position_sizing`, plus the rules for proving the code implements it correctly. These two JSON blocks are combined into one feature because they share state (trade history, position state, win/loss tracking) and several of their rules directly reference each other (defensive_mode's size multiplier stacks with losing_streak_response's step-downs).

**v2 architecture change**: the Considerations_ document (now in the project folder) explicitly decided to use `backtrader` as the underlying infrastructure for Feature 4 and the backtest engine. This changes *where* the code lives, not *what rules it implements*. The Minervini rules in Sections 2 and 3 remain unchanged — they become custom `Strategy` and `Sizer` subclasses within backtrader, not standalone modules. Read Sections 0.1 and 0.2 before writing any code.

---

## 0.1 What backtrader provides — don't reimplement these

These are handled by backtrader's built-in broker and order system. Never reimplement:

- **Stop-loss order execution** — use plain `buy()` for entry, then immediately place a separate `sell(exectype=bt.Order.Stop, price=stop_price)` on fill confirmation in `notify_order()`. Do NOT use bracket orders (`buy_bracket()`). Reason: the breakeven-stop swap in Section 0.2 requires canceling and replacing the stop order mid-position (`self.cancel(stop_order)` then a new `sell()`), which is straightforward with a plain stop order but genuinely awkward with bracket orders' OCO-linked legs — canceling one linked leg has non-obvious side effects on the other. The book's actual requirement is "predetermined stop before entry" — a stop placed immediately on fill satisfies this completely. The original spec mentioned `sell_bracket()` (also a typo — Kashif only goes long), which is superseded by this resolution.
- **Gap-through execution** — backtrader's broker executes stop orders at the next available open price if price gaps through the stop level. Already correct behavior — don't override it.
- **Position tracking** — `self.broker.getposition(data)` gives shares, average entry price, and current value. `weighted_avg_entry_price` from Section 2.3 is `position.price` in backtrader.
- **Portfolio equity** — `self.broker.getvalue()` gives current total equity (`cash + positions × current prices`) — exactly the "current equity" definition from Section 2.4.
- **Commission and slippage** — set once via `cerebro.broker.setcommission()` and `cerebro.broker.set_slippage_perc()`. Use realistic EGX values.
- **Look-ahead bias** — backtrader's `next()` loop passes data bar-by-bar. It is structurally impossible to access tomorrow's data. No custom enforcement needed.
- **T+2 settlement** — model settled vs. uncleared cash by configuring `cerebro.broker.set_coc(True)` (cheat-on-close=False) and setting cash settlement delay parameters. See backtrader's `BrokerBack` docs.

---

## 0.2 What stays custom — implement these inside backtrader's framework

These must be written as custom subclasses or functions — backtrader does not provide them:

- **Custom `Strategy` subclass**: calls Features 1–3's existing functions (`market_regime_gate()`, `evaluate_conditions()`, `compute_composite()`, etc.) inside backtrader's `next()` loop. The signal logic is entirely our code — backtrader just ensures it runs in the right time-step order.
- **Custom `Sizer` subclass** (`MinerviniSizer`): implements losing_streak_response (Section 2.1), defensive_mode multiplier (v0.17 JSON), multiplicative stacking (v0.17 JSON), reentry_from_cash sizing (Section 2.2). Override `_getsizing(self, comminfo, cash, data, isbuy)`.
- **EGX-specific guards** (from Considerations_ Section 4):
  - **Corporate Action Guard**: detect dividend drops / stock splits and prevent false stop-loss triggers. Check `data.close[0] / data.close[-1]` for overnight gaps > 20% — flag for human review rather than executing a stop.
  - **Liquidity Lock**: never take a position size exceeding 1–2% of the stock's 50-day average daily dollar volume. Compute inside `_getsizing()` and cap accordingly.
  - **Fundamental data lag**: the 45–60 day FRA deadline rule is already documented in `fundamentals_data_source_routing.filing_lag_rule`. Enforce it in the data feed — only pass fundamentals to `compute_composite()` after the lag has elapsed.
  - **Macro Devaluation Filter**: future safeguard, explicitly deferred in Considerations_ — do not implement in v1.
- **No-averaging-down check**: in `next()`, before any `buy()` call, check `self.broker.getposition(data).price > data.close[0]` — if the position's average entry price is above current price, block the add. This is custom logic backtrader doesn't enforce automatically.
- **Breakeven trailing stop update**: after `unrealized_gain >= 3 × initial_stop_distance`, cancel the original stop order and replace it with a new stop at `>= entry_price`. Must be done manually by tracking open orders — backtrader's trailing stop doesn't implement Minervini's exact 3× rule automatically.
- **Largest-decline-since-entry exit signal**: track `highest_close_since_entry` as a running max in strategy state. When a single bar's decline from that high, on volume > 50-day average, exceeds any prior single-bar decline since entry — flag as exit_candidate. Entirely custom.
- **Scoring Queue (Watchlist Traffic Jam)**: when multiple tickers pass all pipeline stages simultaneously and available slots < candidates, rank by `soft_score + VCP quality + base_count_modifier` (from the JSON) and fill slots with the highest-ranked first. Implement inside the strategy's `next()` as a priority queue.
- **Decision Receipts** (Considerations_ Section 3): log a detailed per-ticker record at every pipeline stage — "Passed Stage 1 & 2, Failed Stage 3 because volume on breakout was 0.8× average, required 1.4×." Plain text or JSON file per trading day.
- **Reporting**: use `QuantStats` to generate HTML performance reports (Win Rate, Max Drawdown, equity curves). Do not write custom report math.

---

## 0.3 Two items in Considerations_ that conflict with standing project decisions — do not implement without an explicit decision

**Playwright for EGX scraping** (Considerations_ Section 2): proposes using `playwright-stealth` to bypass EGX's F5/TSPD anti-bot challenge. `STATUS-technical-thread.md` (Section 7) has an explicit standing rule: "never build or request anything that bypasses active bot-detection (e.g. EGX's JS challenge wall), regardless of stated purpose." These two instructions directly contradict each other. Do not implement EGX scraping via Playwright until this is explicitly resolved — flag it and ask before touching it.

**LangChain + Google AI Studio for catalyst check** (Considerations_ Section 2): the project has used Claude (Haiku 4.5, with prompt caching and Batch API) for the catalyst rubric throughout this project. Switching providers changes cost, latency, and rubric behavior. Not blocking, but this is a real decision — flag it rather than silently switching.

---

## 1. Source of truth

1. `minervini_sepa_v1_strategy_config.json` → `risk_rules`, `position_sizing`, `graduation_criteria` blocks (v0.17+)
2. `Considerations_` — architectural decisions (backtrader, QuantStats, EGX guards)
3. `MANIFESTO.md` Parts 7, 8, 9
4. `ch12-notes.md` — stop-loss rules, the Loss Adjustment Exercise proof
5. `ch13-notes.md` — position sizing, concentration, defensive mode, losing-streak protocol

---

## 2. Resolutions on top of v0.17 (build against this, not the raw JSON for these four items)

### 2.1 `losing_streak_response` — exact triggers

The JSON says "reduce in steps: 100% → 40% → 20%, scale back up only after performance normalizes." Three things undefined: what triggers each step, what "normalizes" means, and whether "streak" means consecutive losses or consecutive stops specifically.

**Resolved:**
- A "streak" counts consecutive **stopped-out** trades (hit the hard stop or gap-through stop) specifically — not just any loss. A trade sold for other reasons (exit signal, manual close) at a small loss does not extend the streak. Rationale: the book's losing-streak concept (Ch. 13) is specifically about a run of stopped-out trades signaling either flawed selection or hostile market conditions, not about small discretionary exits.
- **Step down at 3 consecutive stops → 40% of normal size.** At a 50% win rate (which the book itself calls viable), a 3-loss streak has a 12.5% probability — uncommon enough to genuinely signal something, not so rare it never fires in normal trading.
- **Step down at 5 consecutive stops → 20% of normal size.** 3.1% probability at 50% WR — genuinely unusual.
- **Recovery: 2 consecutive profitable trades at the current reduced size → step back up one level.** Recovery is deliberately asymmetric — consistent with the book's risk-first philosophy and Ch. 13's instruction to scale back up "only after performance normalizes," not immediately.
- Any single winning trade resets the consecutive-stop counter to zero but does NOT automatically restore full position size if already stepped down — only 2 consecutive winners from the current level trigger a step-up.
- In backtrader: implement inside `MinerviniSizer._getsizing()` — this method is called for every order, so it can read strategy-level state (streak counter) and return the appropriately scaled size.

### 2.2 `reentry_from_cash` — exact sizing

The JSON says "start with small pilot positions, increase only after early trades confirm."

**Resolved:**
- **Pilot size = 50% of normal position size.**
- **Scale to 100% after 2 consecutive profitable trades at pilot size.** Same 2-consecutive-winner recovery logic as 2.1.
- If a pilot trade is stopped out, the losing_streak_response counter starts (or continues) normally — pilot status doesn't exempt a trade from streak tracking.
- In backtrader: `is_reentry_from_cash` flag lives in strategy state, read inside `_getsizing()`.

### 2.3 `no_averaging_down` — entry price definition

The JSON says "never increase size on any position currently below entry price." If a position was scaled into (multiple adds at different prices), what's "entry price"?

**Resolved:**
- **Weighted average entry price** across all fills — which is `self.broker.getposition(data).price` in backtrader (backtrader already tracks this correctly as the cost-basis average).
- The no-averaging-down check: `data.close[0] < self.broker.getposition(data).price` → block any `buy()` call. Implement as a guard in `next()` before any add order.

### 2.4 `sizing_logic` — what "capital" means, and how position count interacts

The JSON says "~25% of capital per position (4 equal positions) as baseline."

**Resolved:**
- **"Capital" = current total equity** — use `self.broker.getvalue()` inside `_getsizing()`, not a hardcoded starting amount.
- Actual per-position size = `broker.getvalue() / target_position_count`, bounded by `concurrent_positions` limits from the JSON (4–6 small account, 10–12 large, hard ceiling 20).

---

## 3. What backtrader tracks automatically — no custom state model needed

In the original v1 of this document, a manual state model was specified (open position dict, closed trade list, rolling counters). With backtrader, most of this is provided:

- `self.broker.getposition(data)` → open position (size, avg price, value)
- `self.broker.getvalue()` → total equity
- `trades` are logged via `notify_trade()` — override this in the custom Strategy to update the streak counter, defensive_mode flag, and closed-trade history

**Custom state still needed in the Strategy** (not provided by backtrader):
- `consecutive_stops` counter
- `recent_closed_trades` list (trailing 20, for defensive_mode trigger)
- `is_defensive_mode` boolean
- `current_streak_step` (100% / 40% / 20%)
- `is_reentry_from_cash` boolean
- `pilot_consecutive_winners` counter
- `highest_close_since_entry` per ticker (for largest-decline exit signal)

---

## 4. Testing standard

Same discipline as Features 1–3 (known-answer fixtures, predictions before code, no circular verification, wrong predictions left visible).

**Key difference from Features 1–3**: these fixtures test behavior across a *sequence of bars and trades*, not a single point-in-time calculation. Use backtrader's `bt.feeds.PandasData` with a small synthetic OHLCV DataFrame as the data feed — keeps fixtures deterministic and fast, same spirit as the synthetic price series used in Test A.

Required fixtures:

- **Fixture 1 — stop-loss enforcement via bracket order**: open a position at price 100 with a bracket stop at 90 (10%). Feed a bar with low < 90. The stop must execute at 90 (or opening price if gapped). Confirm `was_stopped_out = True` via `notify_trade()`.
- **Fixture 2 — breakeven trigger**: open at 100, stop at 90 (10-point distance). Price rises to 130 (3× the 10-point distance). Strategy must cancel the original stop and replace with a new stop at ≥ 100. Then price drops to 99 — must be stopped out at 100, not 90.
- **Fixture 3 — no-averaging-down**: position at average entry 100, current price 95. A `buy()` attempt must be blocked by the guard in `next()`. Then price rises to 106 — `buy()` must now be allowed.
- **Fixture 4 — losing-streak step-downs**: feed a sequence of 5 synthetic losing trades (each gapping through the stop). After trade 3, `_getsizing()` must return 40% of normal. After trade 5, 20%. Then 2 consecutive winning trades — size must step back to 40%, not jump directly to 100%.
- **Fixture 5 — defensive_mode trigger and revert**: inject a trailing-20-trade history with `win_loss_ratio = 1.5` (below the 2.0 threshold from v0.17). Defensive mode must activate. Then inject a recovery history (ratio ≥ 2.0 AND win rate ≥ 50%). Must deactivate — and both conditions must be satisfied, not just one (AND, not OR, per v0.17).
- **Fixture 6 — multiplicative stacking**: defensive_mode active (0.5×) AND losing_streak at step 1 (40%) simultaneously. `_getsizing()` must return 20% of normal — `0.5 × 0.40`, not `min(0.5, 0.4)`.
- **Fixture 7 — reentry_from_cash**: strategy starts fully in cash. First order must be 50% of normal size. After exactly 1 profitable close, second order still 50%. After 2 consecutive profitable closes, third order must be 100%.
- **Fixture 8 — largest-decline exit signal**: price advances 100→120 over several bars, then a single bar drops 8% on volume 1.5× the 50-day average — and this is the largest single-bar decline since entry. Must flag as `exit_candidate` regardless of whether the stop is still intact.
- **Fixture 9 — equity-based sizing**: start with 100,000 EGP. One 25,000 position gains 20% and closes → equity = 105,000. Next position size must be based on 105,000, not 100,000 — verify via `_getsizing()` calling `broker.getvalue()`.
- **Fixture 10 — Liquidity Lock**: a position size calculated from equity would exceed 2% of the ticker's 50-day ADDV. The Liquidity Lock guard must cap the size. Confirm the returned size is smaller than the unconstrained equity-based calculation.

---

## 5. Deliverables checklist

- [ ] `kashif_strategy.py` — custom `bt.Strategy` subclass. Calls Features 1–3 functions in `next()`, manages custom state (Section 3), implements no-averaging-down guard, breakeven stop update, largest-decline exit signal, scoring queue, and Decision Receipts
- [ ] `kashif_sizer.py` — custom `bt.Sizer` subclass (`MinerviniSizer`). Implements losing_streak_response (Section 2.1), defensive_mode multiplier (v0.17 JSON), multiplicative stacking (v0.17 JSON), reentry_from_cash sizing (Section 2.2), equity-based sizing (Section 2.4), and Liquidity Lock (Considerations_ Section 4)
- [ ] EGX-specific guards in the appropriate modules: Corporate Action Guard (in strategy's `next()`), Liquidity Lock (in sizer's `_getsizing()`), fundamental data lag (in data feed layer)
- [ ] Known-answer test file covering all 10 fixtures in Section 4, using synthetic `bt.feeds.PandasData`, predictions written before running, corrected in place if wrong
- [ ] QuantStats HTML report generated from the test run — confirms the reporting pipeline works, not just the trading logic
- [ ] Updated `minervini_sepa_v1_strategy_config.json` reflecting Sections 2.1–2.4's resolutions (may already be in sync from prior chat work — verify before editing)
- [ ] The two flagged conflicts in Section 0.3 (Playwright, LangChain) **must not be implemented** — flag them in a comment, leave them as TODOs for an explicit decision

---

## Change Log

- v1 — initial version. Resolves: losing_streak step-triggers, reentry_from_cash sizing, no_averaging_down entry-price definition, sizing_logic capital base. Builds on v0.17's six prior JSON fixes. Designed around standalone modules.
- v2 — architecture rewritten to build on top of `backtrader` per the Considerations_ document. All Minervini rules from v1 unchanged — they become a custom Strategy subclass and a custom Sizer subclass within backtrader's framework. State model simplified (backtrader tracks most of it automatically). Two conflicts with standing project decisions flagged explicitly (Playwright anti-bot bypass, LangChain provider switch). Added Fixture 10 (Liquidity Lock), QuantStats reporting to deliverables, Decision Receipts, and EGX-specific guards from Considerations_ Section 4.
- v3 — two implementation questions resolved during build. (1) Corporate Action Guard: backtrader fills stops at bar-open before next() runs, so "don't execute the stop" is impossible without overriding execution (forbidden by Section 0.1). Resolved: let the fill happen, reclassify in notify_trade() — exclude >20% gap fills from consecutive_stops/defensive_mode tracking, flag as corporate_action_suspected in Decision Receipt. (2) Bracket orders: sell_bracket() was a typo (Kashif is long-only), and even buy_bracket() makes the breakeven-stop swap awkward. Resolved: plain buy() + separate sell(exectype=bt.Order.Stop) — transparent lifecycle, simple cancel-and-replace for the breakeven swap, satisfies the book's "predetermined stop before entry" requirement without the OCO-linking complexity.

---

## v3 Update — Profit-First Principle Applied

**Six changes from the profit-first audit:**

1. **Position count: 4 → 6 default** — book says 4-6 for small accounts.
   Profit-first takes the top of the range. More concurrent positions =
   more opportunities captured simultaneously.

2. **Position size: 25% → 16.7%** — same capital deployed, 6 equal
   positions instead of 4. Each position is 16.7% of current equity.

3. **Losing streak step-down REMOVED** — the specific triggers (3
   consecutive stops → 40%, 5 → 20%) were invented numbers, not in the
   book. Book says "reduce during losing streaks" without specific triggers.
   Defensive mode handles sustained underperformance instead. Full size
   maintained until defensive mode activates.

4. **Defensive mode trigger loosened** — changed from
   (ratio < 2.0 OR rate < 0.50) to (ratio < 1.5 OR rate < 0.40).
   Less aggressive trigger = more time at full size before defensive
   mode activates.

5. **Pilot size on reentry: 50% → 75%** — book says "start small, add
   after early trades confirm." 75% is still smaller than full size but
   deploys capital faster. Profit-first takes the less conservative
   interpretation.

6. **Breakout volume: 1.4× → 1.2×** — 1.4× was invented. Book says
   "meaningfully above average." 1.2× still confirms institutional
   interest while capturing more genuine breakouts.

**Change Log v3**: profit-first principle applied. Removes over-engineering
added before strategy was validated on real data.
