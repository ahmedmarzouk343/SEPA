# Kashif (كاشف) — Build Roadmap

*EGX Virtual Trading Strategy Platform. Virtual money only, no real trades. Deterministic code decides; AI only explains/scores a pre-filtered shortlist.*

**Current phase: Design/planning only. Nothing built yet.** Zero lines of code written. The next concrete action is a manual data-quality check — everything past that is sequenced below.

---

## Where We Are Now — Settled Decisions

These are locked in and don't need re-litigating:

- **Architecture philosophy**: bulk scanning, backtesting, ledger math, and supervision are 100% deterministic code. The LLM only touches a small, post-filtered daily shortlist for synthesis/explanation — never raw data, never a final buy/sell decision.
- **Data layer**: EODHD (EOD+Intraday plan, ~€30/mo) confirmed to have EGX technicals coverage. Fundamentals (PEG, earnings estimates) have no clean EGX API at reliable depth — refresh manually each earnings season from Mubasher or Simply Wall St instead of automating.
- **Cost-saving tactic**: buy raw price data only (cheapest tier) and compute RSI/momentum/etc. yourself with `pandas-ta`, instead of paying for pre-built indicator endpoints.
- **Strategy schema**: versioned JSON configs (universe filter + entry rules + exit rules + risk rules). Hard criteria (binary, code) vs. soft criteria (0–100 composite score; quantifiable-but-fuzzy = weighted code, genuinely qualitative = LLM scored against a fixed rubric only).
- **Pipeline stages** (`hard_filter`, `soft_score`, `ai_context_review`, `ai_synthesis`) are ordered per-strategy, not globally fixed. Cadence (daily/weekly/monthly) is also per-strategy.
- **State tracking**: each check diffs fresh scan results against current holdings → entry candidate / exit candidate / hold-and-log. Notifications fire only on state change.
- **Ledger**: double-entry bookkeeping, 100,000 virtual capital per strategy, isolated ledgers, reconciliation check after every trade (`cash + positions×price = equity`).
- **Supervision**: a code-based supervisor re-derives each decision independently and diffs against what happened — not an LLM watching an LLM. Separate technical reviewer monitors pipeline health (API success rate, schema failures, scan coverage).
- **Discovery mode**: requires a control group (non-winners) and a held-out validation subset of winners, to avoid mistaking overfitting for signal.
- **LLM model choice**: Claude Haiku 4.5 for the synthesis step, with prompt caching (fixed rubric portion) and Batch API (checks aren't real-time) to keep cost down.
- **Multi-strategy isolation**: one stateless pipeline function called fresh per strategy per run — not separate persistent agents.
- **Backtest validity guards**: point-in-time fundamentals (no lookahead bias), survivorship bias handling (include delisted names), realistic slippage assumptions (not closing-price fills) — all built into the engine from day one, not bolted on later.
- **Naming**: Kashif (كاشف) — "the one who uncovers/reveals."

---

## Open / Unresolved Items

These need a decision before (or during) the phase that depends on them:

| Item | Needed before | Status |
|---|---|---|
| EODHD data quality vs. real watchlist (10–15 tickers) | Everything — this validates the core assumption the whole project rests on | Not started |
| Position sizing rule (fixed $ vs. % of equity vs. per-strategy configurable) | Ledger can be built | Unresolved |
| Portfolio-level capital allocation across simultaneous strategy signals | Multi-strategy paper trading | Unresolved — no concentration/correlation check yet |
| Numeric graduation criteria (min trade count, max drawdown, return-vs-risk ratio) | Promoting any strategy from backtest → paper trade → "trusted" | Unresolved — "manual approval" alone was rejected as not a real bar |
| Mubasher outreach email re: commercial data access | Only needed if EODHD/Twelve Data free tiers prove insufficient | Drafted as an idea, not sent |
| Daily spend tracker/alert for LLM costs | Before synthesis layer goes live | Not started |

---

## Roadmap

### Phase 0 — Validate the core assumption (no code)
- [ ] Manually pull EODHD free-tier data for the real watchlist (10–15 EGX tickers)
- [ ] Check coverage, history depth, and update reliability against what the strategies will actually need
- [ ] Go/no-go decision: is EODHD sufficient, or is Twelve Data / a Mubasher conversation needed?

### Phase 1 — Backtest engine + strategy schema
- [ ] Define the JSON strategy config schema (universe, entry, exit, risk rules; hard vs. soft criteria)
- [ ] Build point-in-time fundamentals handling (no lookahead bias)
- [ ] Build survivorship-bias-aware universe (include delisted EGX names historically)
- [ ] Build realistic slippage modeling into fills
- [ ] Build the `pandas-ta`-based indicator computation layer (RSI, momentum, etc.) on top of raw price data

### Phase 2 — Ledger, position sizing, supervision
- [ ] Resolve position sizing rule (open item above)
- [ ] Build double-entry ledger with per-strategy 100,000 virtual capital
- [ ] Build reconciliation check (cash + positions×price = equity), flagging on mismatch
- [ ] Build the code-based supervisor (independent re-derivation + diff)
- [ ] Build the technical reviewer (pipeline health: API success rate, schema validation, scan coverage)
- [ ] Build the global kill switch

### Phase 3 — Portfolio & risk layer
- [ ] Resolve portfolio-level capital allocation across simultaneous strategy signals
- [ ] Add concentration/correlation checks across strategies
- [ ] Define and implement numeric graduation criteria (trade count, drawdown, return-vs-risk)

### Phase 4 — Paper trading, live monitoring
- [ ] Run strategies live against fresh daily/weekly/monthly data (per-strategy cadence)
- [ ] State-diffing against holdings → entry/exit/hold-and-log
- [ ] Notifications on state change only
- [ ] Daily spend tracker/alert live

### Phase 5 — LLM synthesis layer (added last, deterministic core proven first)
- [ ] Build the fixed rubric for soft/qualitative scoring
- [ ] Wire Haiku 4.5 into the `ai_context_review` / `ai_synthesis` pipeline stages
- [ ] Set up prompt caching for the fixed rubric/schema portion
- [ ] Set up Batch API for non-real-time checks

### Phase 6 — Discovery mode (reverse-engineering winners)
- [ ] Define "super performer" numerically
- [ ] Pull technical/fundamental values at multiple pre-breakout points for winners
- [ ] Build the control group (non-winners) comparison
- [ ] Hold out a validation subset of winners, unused during discovery
- [ ] LLM reads qualitative context (news, sector tailwinds) around winners → proposes hypotheses for a human to formalize
- [ ] Discovery output feeds into the same schema as manual strategies → same backtest → paper trade → graduation pipeline

---

## Explicitly Deferred / Not in Scope Yet
- Real-money execution (standing principle: prove signal quality over real paper-trading time first, if ever considered)
- Automated fundamentals refresh for EGX (no reliable API exists — stays manual per earnings season)
- Hugging Face sentiment model (only if news sentiment is ever added as a signal later)
- EGID direct licensing (B2B only, user prefers not to pursue for personal use)

---

*Source: consolidated from `kashif-project-summary.md` and `kashif-project-summary-part2.md`.*
