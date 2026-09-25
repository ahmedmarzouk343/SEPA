# Kashif: Minervini SEPA v1 on US mid/small caps, final backtest report

Built overnight 2026-09-25. Virtual money only; nothing here connects to a broker.

## Bottom line: no edge after costs

On the untouched holdout (2024-07-01 to 2026-09-24), the strategy with its frozen parameters **did not beat its benchmark**. It returned **+8.3%**, against **+31.9%** for the MDY/IJR 50/50 blend and **+44.4%** for SPY.

| Holdout, run once | Total return | CAGR | Max drawdown | Sharpe | Sortino |
|---|---|---|---|---|---|
| **Strategy (primary arm)** | **+8.3%** | **3.6%** | **−15.3%** | **0.46** | 0.67 |
| MDY / IJR 50/50 | +31.9% | 13.2% | −26.1% | 0.74 | 1.11 |
| MDY (S&P 400) | +28.6% | 11.9% | −24.0% | 0.70 | 1.05 |
| IJR (S&P 600) | +35.1% | 14.4% | −28.0% | 0.76 | 1.15 |
| SPY | +44.4% | 17.9% | −18.8% | 1.08 | 1.61 |
| Equal-weight S&P 400+600, monthly rebalanced | +41.2% | 16.7% | −25.1% | 0.89 | 1.35 |

Trades: 91 · win rate 38.5% · average win +12.0% · average loss −6.3% · win/loss **1.90** (target 2:1) · profit factor 1.23 · average exposure 31% · costs paid $1,256. The auditor matched the ledger exactly.

- **The Sharpe is statistically indistinguishable from zero.** 0.46 over 2.2 years has a Lo (2002) standard error of 0.70, which gives a 95% interval of **−0.92 to 1.84**.
- **The smaller drawdown is not skill.** It comes from being only about 31% invested on average (see section 6).
- **The tuning window agrees.** On 2022-01 to 2024-06 the frozen parameters returned **−0.6%**, against +0.9% for the benchmark blend. Only 20 of the 108 parameter combinations tried had a positive Sharpe.
- **The catalyst layer changed nothing.** Adding it produced **identical trades** in both windows. Filings the rubric rated "strong positive" were followed by *weaker* 60-day returns than neutral ones, in both windows.

That is a valid result, not a failure. As specified tonight, this strategy is not ready for paper trading on this universe.

---

## 1. What was built

- **`kashif_engine/`: a strategy-agnostic backtest engine on backtrader.**
  - A market layer: US uses T+1 settlement and IBKR-style commissions; EGX has a T+2 spec sketched.
  - A double-entry Decimal ledger with T+N settlement, reconciled with the broker after every bar that has fills.
  - An independent auditor that rebuilds P&L from the trade list and price files only.
  - A kill switch, decision receipts, benchmark and QuantStats reports.
  - `HOW_TO_EXTEND.md`: a new strategy is a JSON config plus a module.
- **`strategies/minervini_sepa_v1/`: the strategy.** It follows the config's `pipeline_order`:
  1. Regime gate (OR logic).
  2. Trend Template: all 8 conditions, with RS percentile ranked across the full 1,029-ticker universe.
  3. Fundamentals: the 4-question screen, point-in-time.
  4. Catalyst: ranking only, never a gate.
  5. VCP pivot breakout on volume.
  6. Sizing: min(streak, defensive, pilot) × equity / positions, capped at 2% of average daily dollar volume.
  7. Risk:
     - stop 3% under the pivot, clamped to 4-10%;
     - breakeven at 3× risk;
     - trailing max(peak × 0.85, SMA50 × 0.95);
     - largest-decline exit;
     - full defensive mode.
- **Point-in-time fundamentals adapter** over `us_fundamentals/` (1,024 tickers). It uses only `get_known_fundamentals` / `adjust_eps_for_splits` with the *simulated* date, and a release becomes usable the day after it is published.
- **Catalyst layer (catalyst_check).**
  - A code-only priority layer runs first.
  - Rubric v0.3 scoring then covers SEC 8-K filings (79,038 collected) and web news.
  - It is merged into one point-in-time table with a track record of 10/20/60-day forward returns.

## 2. Data and no-lookahead guarantees

- **Prices.** Yahoo daily bars, 2019-01 to 2026-09-24. The 09-25 bar was partial and is excluded.
  - Signals use split-adjusted prices.
  - Fills are at the split-adjusted open or stop, with raw share counts and prices recorded next to them. The dollar amounts are identical, and no stop can fire on a split.
  - Dividends are credited on the ex-date to shares held at the prior close.
- **Fundamentals, extended to 2020 so YoY growth exists from 2021.** Two root-cause fixes to release dates:
  - Quarters were dated to the fiscal year's 10-K whenever that 10-K repeated their numbers. That affected 3,219 rows, up to 9 months late. They are now dated to the first filing that reported the same value, and no value changed.
  - Release dates were then moved to the **8-K Item 2.02 earnings press release** where one exists: 60.7% of rows, median 5 days earlier. The overlay never moves a date across a split or borrows the date of an original release for a restated value.
  - Re-verified after both fixes:

    | Check | Result |
    |---|---|
    | Checkpoints | 9/9 |
    | Split tests | 80/80 |
    | Store point-in-time validation | pass |
    | Missing data | 0.40% |
    | Unexplained missing values | 0 |
- **Lookahead tests in the suite:**
  - deleting future bars changes no past panel row;
  - a release is unknown on its own day and known the next;
  - growth is unchanged across a split;
  - the event-date shortcut equals direct evaluation on random days.
- **Holdout protocol.**
  - The tuning parameters and a pre-declared analysis list were committed (`0c5385d`) before the holdout ran.
  - The holdout ran once (`HOLDOUT_LOCK.json` stores the SHA-256 of every frozen input and the commit `bfecbf7`).
  - Code refuses any other run that reaches the holdout, and holdout forward returns were withheld until the run finished.

## 3. Tuning, done honestly

- **Windows:** tuning 2022-01-03 to 2024-06-28; holdout 2024-07-01 to 2026-09-24.
- **Grid:** only existing config parameters, book-grounded ranges, 108 combinations.
  - RS threshold {70, 80, 90}
  - Breakout volume {1.2, 1.4, 1.6}×
  - Maximum stop {6, 8, 10}%
  - Maximum positions {4, 6, 8, 12}
- **Objective**, declared in code before any run: daily Sharpe, with at least 30 trades and max drawdown ≤ 25%. The final pick is the combination with the best **median Sharpe over itself and its grid neighbours**, so a lone spike cannot win.
- **Backtests run:** **435** in total. That is 108 on the full window plus 3 anchored walk-forward folds × 109, and every one was audited exactly. This is the multiple-testing count.
- **Full tuning window:** the median Sharpe across the grid was −0.26, and only 20 of 108 combinations were above zero.
  - The single best cell (Sharpe 0.73, the config's defaults) was a spike: one open ADMA position carried it.
  - The stability rule picked **RS 70 / volume 1.6× / stop 10% / 6 positions**. Its own tuning Sharpe is **0.02**, which is the honest summary of the tuning window: *no robust edge; the rule picked a flat region*.
- **Walk-forward:** every fold chose a *different* combination (RS 70 / 1.2× / 10% / 4 positions). Its out-of-sample tests were positive (+3.8%, +8.2%, +15.4%), but on only 11, 6 and 7 trades.
  - That is weak evidence, and it does **not** validate the deployed parameters.

**Tuning window, frozen parameters (TUNE_final):**

| | Total return | CAGR | Max drawdown | Sharpe |
|---|---|---|---|---|
| Strategy | −0.6% | −0.2% | −12.3% | 0.02 |
| MDY / IJR 50/50 | +0.9% | 0.4% | −23.5% | 0.12 |
| SPY | +18.3% | 7.0% | −24.5% | 0.46 |
| EW S&P 400+600 | +13.0% | 5.0% | −22.3% | 0.33 |

94 trades · win rate 30.9% · win/loss 1.96 · profit factor 0.85.

## 4. Did the catalyst help? No.

- **What was scored.** SEC 8-K filings from the 90 days before every candidate day (363 in tuning, 351 in the holdout), plus web news research in the same windows (339 items).
- **Who scored it.** Claude subagents and two parallel research sessions, all under rubric v0.3 with a strict earnings rule: "positive" needs an explicit YoY profit-line gain.
- **Quality checks:**
  - A blind second rater agreed on 95% of a 40-filing sample (Cohen's κ 0.89).
  - The earlier free-tier API scores agreed 81% (tuning window).
- **The layer cannot discriminate.** Every candidate had already passed an EPS-growth screen, so 231 of 240 scored tuning candidates were "strong positive". The +0.5 rank bonus therefore lifted almost everyone equally, and **no trade changed** in either window.
- **Track record: positive calls preceded *weaker* returns.** Mean forward return after the filing or article, 60 trading days:

  | Window | Source | STRONG_POSITIVE | NEUTRAL |
  |---|---|---|---|
  | Tuning | 8-K | +8.9% | +12.5% |
  | Holdout | 8-K | +12.9% | +17.6% |
  | Holdout | news | +10.9% | +14.3% |
- **Hindsight risk.** The models may know how 2022-2026 turned out. The raters were told to judge only as of each publication date, and rationales were scanned for price language, but this can't be proven. It matters little here, because the layer had no effect.

## 5. Integrity checks

- **Auditor.** The independent auditor matched the ledger **exactly** on every run: cash, equity and each round trip.
  - That covers all 435 tuning runs, both holdout arms and every test.
  - It also checks each fill against the tape: market orders fill at the open, stops at the stop or the gap open, costs are recomputed, dividends are recomputed.
- **Ledger.** It reconciled with the broker after every bar that had fills. Any drift trips the kill switch and aborts the run.
- **Chaos test** (missing weeks, zero volume, a 10× price bar, an all-NaN ticker, missing fundamentals):
  - no crash;
  - bad bars are flagged and never traded;
  - dark-feed exits wait for a real bar;
  - the books still balance exactly.
- **Suites.**

  | Suite | Result |
  |---|---|
  | Engine | 30/30 |
  | Legacy known-answer | 144/144, plus the 12 auditor-tolerance tests now owned by the parallel session = 156 |
  | Checkpoints | 9/9 |
  | Split tests | 80/80 |
  | Store point-in-time validation | pass |
  | FY-month and label checks | pass |

  `scaled_verification.py` still prints "FAIL" for its gap-scan and duplicate-NI heuristics, exactly as it did before tonight: all 116 gaps have a diagnosis row, and the FHN duplicate is a known flag.

## 6. Why the strategy under-performs (evidence, not guesses)

1. **Defensive mode is on almost all the time.**
   - The config trips it when the win rate over the last 20 trades is below 40%. This system's win rate is structurally 31-38%.
   - It was active at **80-84% of trade closes**. That meant half size, a 6% stop cap, and an **11% profit target** that sells winners early. The 21 target exits per window averaged +11.5% / +13.5%, the right tail cut off.
2. **Low exposure.**
   - Pilot sizing (47-64% of trades) plus defensive halving kept average exposure near 30%.
   - Candidate supply is thin: 639 price-ready breakout days in 2.5 years across 1,029 stocks. Most VCP rejections are daily bases with fewer than 2 contractions.
3. **The regime gate barely filters.** The OR gate was open on 95% of days since 2022.
4. **The edge per trade is about zero.** With a ~35% win rate and win/loss about 1.9-2.0, expected value per trade is roughly zero before the caps above, and negative after costs in the tuning window.

## 7. Bugs found and fixed tonight (root cause first; the full suites re-run after each)

**Data**
1. Late release dates from the 10-K quarterly note (3,219 rows).
2. A crash that dropped CWEN, caught by a row-count diff.
3. 8-K overlay guards against restated values and splits.
4. The fundamentals adapter anchored on the last *released* row instead of the newest quarter (7 windows); the candidate set was unchanged.
5. Tickers with no fundamentals raised an error instead of being skipped.

**Engine**, caught by known-answer tests or the parallel review before any result was trusted:

6. Fills were stamped one day early (settlement was off by a day).
7. The sign of payables in the reconciliation was wrong.
8. backtrader delivers order *clones*, so stop exits were labelled "EXIT".
9. **Stop orders were re-tested against a stock's previous bar on days it had no bar.** Fixed with a `ClockBroker`, and the test fails without the fix.
10. Market orders on a feed that never returned sat pending forever.
11. The auditor didn't check stop fill levels.

The default configuration was re-run after these fixes and reproduced all 206 fills to the cent. None of the 435 tuning runs was affected.

**Legacy `kashif_strategy.py` versus the config** (fixed in the new module; the legacy EGX file is untouched):

12. Fundamentals were only logged and never gated.
13. A STRONG_NEGATIVE catalyst blocked entry.
14. Breakeven was at 4× risk instead of 3×.
15. Defensive mode applied only its size multiplier.
16. The reentry pilot never switched on.
17. Profitable trailing-stop exits counted toward the losing streak.
18. `fundamentals_fetcher` returned cur/prior as "growth" and used live data.
19. The breakout-volume multiple never reached `check_breakout`.

**Catalyst pipeline**

20. NaN is truthy, so the model was never called.
21. v1 text was cover-page boilerplate.
22. v2 text was truncated or missing (57 of 329 unusable, and most releases were cut).
23. Transient 503 errors were treated as quota exhaustion.
24. Unparseable model answers were cached as NEUTRAL.
25. `build_catalyst_table` would have printed holdout returns before the holdout run; caught in review before it was ever run.

**Tuning**

26. `select()` ignored failing neighbours; the re-derived picks are identical.
27. The Sortino formula was wrong.
28. The equal-weight benchmark mixed in hand-picked names.

## 8. Limitations

- **Survivorship.** The universe is *today's* S&P 400/600 members plus 27 hand-picked extras (NVDA, MSFT, AMZN, SMCI and others).
  - Estimate: equal-weight current members minus the MDY/IJR blend = **+12.1 points in tuning (about 4.7%/yr) and +9.3 points in the holdout (about 3.5%/yr)**. That gap mixes survivorship with the equal-weight tilt.
  - The extras contributed only 6 trades (−$1,360) in tuning and 4 trades (+$791) in the holdout.
  - The strategy still lost to benchmarks that don't carry this bias.
- **Costs are modelled, not measured.** $0.005 per share (minimum $1), plus slippage of 5 bps + 10 bps × √(participation / 1%). Real small-cap costs may be higher, which would make the result worse, not better.
- **Execution simplifications:**
  - decisions at the close, entries at the next open;
  - a new stop is live from the bar after the entry;
  - the defensive profit target is checked at the close and sold at the next open;
  - dividends are credited on the ex-date, not the pay date.
- **Knowledge-date simplifications:**
  - fundamentals are usable the day after release, one day conservative for pre-market releases;
  - 76 rows carry *restated* values dated to the restatement, so they are known later than the original number was;
  - news is usable the day after publication.
- **Small samples.** 91-94 trades per window; walk-forward tests of 6-11 trades.
- **Rubric gaps:**
  - the acquired side of a merger (ROKU) is not covered;
  - a narrowing loss (LQDA) is ambiguous;
  - one "implied" gross-profit call (GAP);
  - two holdout shareholder letters were cut at 14,500 characters (CART, FOUR);
  - 12 news figures came from search snippets.
- **Missing data.**
  - CWEN-A has no Yahoo series and was dropped.
  - HLX, LEG, ONON, OZK and PFBC have no fundamentals, so they were never eligible.

## 9. Judgment calls to confirm (not decided silently)

1. **Config vs prompt.** The prompt mentions a "soft score" and Code 33, but the config removed both in v0.27. I followed the config, so there was no soft-score threshold to tune.
2. **Catalyst scale.** FIX 12 removed STRONG_POSITIVE, but I used your rubric v0.3 (three classes). It has no effect on the results either way.
3. **Q1 needs positive current EPS.** A narrowing loss is not treated as earnings growth. A loss-to-profit swing is treated as a turnaround (100% threshold).
4. **Stop placement** kept the legacy pivot × 0.97 clamped to 4-10%, and the approved deviations were kept: trailing give-back 15%, Stage-3 exit off.
5. **Defensive mode needs at least 10 trades** before it can trigger (the legacy guard).
6. **Losing streak = consecutive losing trades** (the legacy code counted stop exits, including profitable ones).
7. **The reentry pilot is armed at the start and whenever the book goes flat.**
8. **The "post-breakout 20-day MA" check is inert.** With entries filling at the next open, it has no effect. Turning it into an exit would be a new rule.

## 10. Suggestions (new rules, **not** applied; evidence above)

- **Revisit defensive mode for breakout systems.** Its 40% win-rate trigger fires almost permanently for a strategy whose normal win rate is about 35%, and its 11% profit target removes the fat right tail. This is the largest measured drag. Any change needs a fresh tuning/holdout cycle.
- **Tighten the regime gate** (2-of-3 or AND). The OR gate is open 95% of the time.
- **Make the catalyst rubric discriminate among growth stocks**: for example, require a beat *plus* a raised profit guide, or a size threshold.
- **Buying extended breakouts: no action.** The median entry was 12-13% above the pivot, but outcome by extension was mixed across windows, so the evidence doesn't support a max-extension rule yet.
- **Use a point-in-time index-membership history** to remove survivorship bias.

## 11. Unfinished items

- EGX: the market spec exists but there is no point-in-time EGX fundamentals store, so EGX cannot run.
- Live/paper news feed: not wired. The tooling exists (8-K collector plus scorer), but there is no scheduler or official RSS source yet.
- The legacy `kashif_strategy.py` still carries the old behaviours listed in section 7; only the new module is fixed.

## 12. Cost and how the work was done

- **LLM API spend: $0.027 notional** (230 calls, Groq gpt-oss-20b and Gemini flash-lite free tiers; $0 billed) against a $10 cap. The log is in `kashif_data/llm_spend.jsonl`.
- **Parallel sessions.** When the free-tier limits made scoring slow, and at your request, the work moved to Claude subagents and two parallel sessions ("First Trial" and "First Trial (fork 2)") coordinated by this session. Together they:
  - researched news for all 241 candidate windows;
  - scored 714 filings;
  - ran the blind reliability check;
  - did two read-only code reviews, which found real bugs (items 9-11, 25-28).

  That usage is session time, not metered API dollars.
- **Git.** Committed locally on `main` and **not pushed**. `independent_auditor.py` and its test were changed by the parallel session and left for you to commit.

## 13. Files

- `backtest_results/HOLDOUT_primary/`, `HOLDOUT_with_catalyst/`, `TUNE_final/`, `TUNE_final_with_catalyst/`. Each holds the trade list, fills, equity curve, audit, metrics, **decision receipts** (one row per stock per day per stage) and **QuantStats HTML**.
- `backtest_results/tuning/`: the grid, walk-forward, all 435 trials, `selection.json`, `PREDECLARED_HOLDOUT_ANALYSES.md` and `HOLDOUT_LOCK.json`.
- `backtest_results/catalyst/`: scores and track records for both windows, raw scorer outputs, rater agreement and reliability.
- `backtest_results/holdout_analysis.json`: the pre-declared analyses.
- `kashif_engine/HOW_TO_EXTEND.md`.
