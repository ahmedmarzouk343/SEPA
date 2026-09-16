# Kashif — Technical Thread Status
*Condensed summary of everything tested, built, and decided in the technical/execution chat. For the business/strategy chat, or for restoring context in a future session.*

---

## 1. Data Sources — Final State

### Price data (daily OHLCV, all ~224 EGX stocks)
- **Source: `yfinance`, ticker format `SYMBOL.CA`** (e.g. `COMI.CA`) — free, confirmed working
- **Coverage: 195/224 (~87%) with good 2-year price history.** 28 tickers fail cleanly (empty result, no data). 1 ticker (`NDRL`) returns thin/flat data.
- **Ruled out**: EODHD free tier (too few calls/day), Twelve Data free (excludes Egypt), Alpha Vantage free (too few calls), Finnhub free (confirmed EGX blocked — 403 error tested directly), EGXAPI (confirmed fake/prototype, no real backing package), Neuro Systems/EGXLytics (real data, but API not live — "coming soon"), TradingView (has EGX data but no pull-API, architecture mismatch), EGX's own website (confirmed actively bot-gated, F5/TSPD JS challenge on every path).

### Fundamentals data (quarterly earnings, revenue, margins)
- **Primary: `yfinance` + `stockanalysis.com`, per-ticker "use whichever is fresher."** Combined ~91.5% coverage on first test, refined further with freshness cross-checks.
- **stockanalysis.com** sourced from S&P Global Market Intelligence (credible institutional vendor).
- **Fallback: Mubasher** — net income only (no revenue field), for genuinely stale/missing tickers. **Known caveat**: a 1000x scale error was found once in validation — treat magnitudes as indicative, not audit-grade. **Known nuance**: Mubasher's News pages redirect anonymous browser sessions to a login page under full JS rendering, but the server freely returns content to plain HTTP requests and robots.txt permits the paths used — judged as meaningfully different from active bot-detection (EGX's JS challenge) and kept as a source on that basis, after review.
- **Unresolved (4 tickers, ~1.8% of market)**: `GMCI`, `CCRS`, `RAKT`, `RTVC` — stale/missing across all sources tested. Excluded from fundamentals_screen when this occurs; technical-only (hard_filter) evaluation still applies.
- **Filing lag rule**: Egyptian FRA deadline is 45 days after quarter-end (sometimes extended to 60). Backtesting must apply this lag — don't treat calendar quarter-end as the "knowable" date. Live scans should treat a missing current-quarter figure as normal, not a fault, until the deadline has passed.

---

## 2. Catalyst Detection — Fully Tested, Working

### The two-part method
1. **Timing** ("when did something happen"): ArabFinance's disclosure feed (`companyprofiledisclosures?key={TICKER}`). Confirmed fast — 2-10 days old across 5 tickers tested, vs. Mubasher's 76-138 days old on the same tickers (tested 3 separate ways: per-ticker, "Market News" category, "Company News" category — Mubasher's public site never showed fresh Egypt content in any of the three).
2. **Content** ("what does it mean"): News search, **English AND Arabic, always both, not Arabic-as-fallback.** Arabic search proven critical twice — caught a credit rating upgrade and a 67.8% acquisition invisible to English search; also caught a real earnings decline (OCDI) that English search would have scored as a false positive using a stale figure.

### Structural finding (important, permanent)
**Some catalysts can never appear in any company disclosure feed — from any source, including Mubasher.** Index inclusion/exclusion (e.g. FTSE Russell), analyst rating changes, external credit-agency actions are decided by a third party, not the company — there's nothing for the company to file. Confirmed by exhaustively searching one ticker's full ~494-item disclosure history (zero hits). News search is the only possible path for this category, not a fallback.

### Scoring rubric — v0.3, tested on 15 real stocks
- Categories: STRONG_POSITIVE / NEUTRAL / STRONG_NEGATIVE
- Real distribution from testing: 10 positive, 2 negative, 2 neutral, 1 externally-originated (index) — genuine spread, not cherry-picked
- Rules added from real test cases (not guessed in advance): reporting-basis conflict handling (standalone vs. consolidated profit), source-reconciliation (different P&L lines can both be "correct"), debunked-rumor handling (a denial isn't bad news), earnings-decline as its own negative category (added after 2/2 real negatives were pure earnings misses, not governance/litigation events)
- **Category-priority layer**: ArabFinance disclosure categories (FinancialResults, Corporate = high priority; Trading, General = low) filter what gets full AI scoring — free, code-only, before any AI cost is spent
- **Never a hard gate** — catalyst_check only feeds the final ai_synthesis step, cannot force a buy or skip alone
- **Track-record logging**: designed, not yet built — every call should log ticker/date/score/actual forward return, reviewed at graduation checkpoints

### Known unsolved piece
**Cannot read the actual EGX bulletin PDF content.** EGX's site blocks all automated access, including direct PDF file downloads (confirmed — not just HTML pages). This means disclosure entries give timing + rough category, but not full content — news search remains the primary content source. Workaround: manual download by a human, tested once (confirmed the PDF text is real/extractable, not scanned — so if access is ever solved, OCR won't be needed).

### Deferred to a future strategy (explicit user decision — NOT built into v1)
Market-wide daily disclosure pre-scan (checking all ~224 tickers for new disclosures, not just the shortlist) — proven mechanically feasible, but out of scope for v1 since the book's literal SEPA order runs catalyst check only on the post-fundamentals shortlist.

---

## 3. Trend Template (`hard_filter`) — Built and Verified

### Status: real code exists, tested twice, verified once
- **First test**: 5 stocks only. Found a real distortion — "top 20%" relative-strength ranking with only 5 stocks mathematically blocks 3 of them regardless of real merit. Not a bug — flagged in advance as a known risk, confirmed real by the data.
- **Second test**: full 196-stock universe (28 tickers failed cleanly, same 28 as the original price-coverage gap). **21% of stocks passed all 8 conditions on a typical day** — sane, non-degenerate result. COMI and TMGH's pass-counts corrected down significantly once ranked against real competition (proof the fix mattered). Three previously-unseen stocks (MIPH, GRCA, PRMH) turned out to be the real standout momentum names, sanity-checked against genuine 80-90% price runs.
- **Known-answer verification (Test A)**: PASSED. Built a synthetic 280-day price series with a hand-calculated, known-correct answer, ran the real code against it, exact match. Found and correctly handled a real subtlety along the way — moving averages structurally cannot flip their relationship in a too-short rally window (confirms the model's built-in conservatism is working, not a bug).
- **Known-answer verification (Test B — relative strength ranking)**: **incomplete.** Delivered version only used 2 synthetic stocks, which can't actually test ranking behavior. Redo requested (8-10 series, known relative order) — not yet completed as of this summary.

### Files that exist (on the user's local machine, via Claude Code — NOT in this chat's sandbox)
- `trend_template_test.py` — main implementation
- `test_trend_template_known_answer.py` — passing regression test
- `test_relative_strength_known_answer.py` — requested, redo pending

---

## 4. Pipeline Architecture — Confirmed Correct

```
market_regime_gate → hard_filter → fundamentals_screen → catalyst_check → entry_timing → position_sizing → risk_rules
```

**This order was wrong for a while and got fixed.** Catalyst was originally placed after entry_timing — contradicted the manifesto's own stated SEPA order (Trend → Fundamentals → Catalyst → Entry → Exit). Now corrected and matches source material.

**Daily monitoring ≠ daily trading.** Two different modes per stock per day:
- **Not currently held**: run the full pipeline above to check for a new candidate
- **Currently held**: skip the entire entry pipeline (including catalyst_check) — just check exit rules (stop-loss, largest-decline-since-entry, P/E overextension). A position can sit unchanged for months, exactly per the book's Stage 2 holding philosophy. This is not a day-trading system.

---

## 5. Open Items — Nothing Built Yet Beyond Trend Template

- [ ] Fundamentals screen — code not written
- [ ] Entry timing (VCP/pivot detection) — known to be codeable (real swing-detection math, multiple existing open-source implementations exist for other markets), not yet built for EGX
- [ ] Risk rules / stop-loss / position sizing — designed in the JSON config, not yet built as code
- [ ] Ledger, supervisor, technical reviewer — designed, not built
- [ ] Test B (relative strength known-answer test) — redo pending
- [ ] Full backtest engine — the actual "did this make money historically" test. **This is the real next milestone** once the remaining pieces above are built.

---

## 6. Where the Source-of-Truth Files Live

- **`minervini_sepa_v1_strategy_config.json`** — the living strategy spec. Edited many times in this chat. **The user has manually placed a copy in their local Claude Code project folder** — that copy must be kept in sync; this chat's copy and Claude Code's copy are NOT automatically connected.
- **`MANIFESTO.md`, `00-INDEX.md`, `ch01–ch13-notes.md`** — the book analysis, in this chat's output folder. Not yet confirmed present in Claude Code's local folder.
- **Test scripts** (`trend_template_test.py` and the known-answer tests) — exist only on the user's local machine via Claude Code, not accessible from this chat.

---

## 7. Process Lessons From This Session (worth not re-learning)

- **Settling on a conclusion too early, presented with more confidence than earned**, was the single most repeated mistake — caught multiple times by direct pushback, not self-caught first.
- **This chat's file edits and Claude Code's actual files are two separate places.** Assuming Claude Code had context it never actually had (the real JSON config) went unnoticed for a while.
- **A firm, non-negotiable line**: never build or request anything that bypasses active bot-detection (e.g. EGX's JS challenge wall), regardless of stated purpose. This is different from cases where a site's own server freely serves content with no active challenge and robots.txt permits it (e.g. Mubasher) — that distinction was reasoned through explicitly, not just asserted.
- **This chat is now scoped to technical execution only.** Business/strategy/product decisions happen in a separate chat in the same project. The two chats do not share memory — only files placed in the actual Project (not just downloaded from a chat) or things the user manually repeats in both places.

---
*This document reflects the state of the technical thread as of the point it was generated. It will go stale as work continues — worth regenerating periodically, not treated as permanently current.*
