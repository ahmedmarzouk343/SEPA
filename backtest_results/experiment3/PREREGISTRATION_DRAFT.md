# Experiment 3: forward paper trading (pre-registration DRAFT)

**Status: draft of 2026-09-26, for the lead and the owner to review.** It becomes binding only once it is committed, with the arm (a) placeholder filled in, **before the first signal at the 2026-09-28 close**. After that, changes are dated amendments that apply going forward only.

## Why forward

The model-book hypotheses (`backtest_results/experiment2/MODEL_BOOK_DEV.md`) were picked in-sample, from about 40 cuts of 2022–2026. The only data that neither they nor any model or person has seen is data that does not exist yet. The 2017–2021 window belongs to experiment 2's one-shot validation and is not used here.

## 1. Arms

Every arm trades the **frozen universe**: the S&P 400 + 600 members listed in `kashif_data/experiment2/index_universe.txt` (2026-09-25).
- Later index additions are not traded.
- Names that are later dropped stay in the universe, so there is no survivorship bias going forward.
- A delisted position is closed at its last available price.

| Arm | Definition |
|---|---|
| **A** | The experiment-2 pick: `<variant + parameters, filled in when experiment 2 selects it>`. Unchanged code. |
| **B1** | A with only the entry changed. **H1:** the VCP price-ready gate is replaced by "close above the prior 50-day closing high on ≥ 1.2× the 50-day average volume". **H2:** an RS floor of 95, with candidates ranked by RS. |
| **B2** | B1 + **H3:** a single Q2 or a single Q4 fundamentals failure is no longer a veto; it becomes a ranking penalty. Q1, double failures and stale/no-data SKIPs stay vetoes. |
| **B3** | B2 + **H5:** for RS ≥ 95, an early Stage-2 path that accepts tt_1, tt_2 and tt_7 (close above the 50-, 150- and 200-day MAs) without tt_3–tt_6 or tt_8b. |
| **C** | B1 + an **AI-agent catalyst rating**, used only as a ranking input and never as a gate. |

- The B arms and C inherit **every non-entry setting from A**: regime gate, exits, stop cap, sizing, max positions and defensive mode. Any difference between them is therefore the entry rule.
- **Arm C rating inputs:**
  - The LLM rates the 8-K and news items for each candidate whose publication timestamp is at or before that day's signal time. The allowed ratings are STRONG_POSITIVE, NEUTRAL and STRONG_NEGATIVE, with the engine's `catalyst_weight` of 0.5.
  - The model id is pinned, the temperature is 0, and the prompt is frozen with its hash logged.
  - There is no browsing. The model sees only the supplied documents.
  - A failed call means NEUTRAL, and the failure is logged. Any model change starts a new, separately reported segment.
  - Because ranking matters only when there are more candidates than free slots, the log also records which candidates B1 would have bought on each such day.
- **Why arm C cannot be backtested:** every available LLM was trained on text covering 2017–2026. Asked to "rate" a 2019 8-K, it already knows how the story ended. No prompt removes that lookahead. Going forward the outcome does not exist yet, so the rating is clean, provided the pinned model is not updated mid-test. Experiment 1's catalyst showed zero effect, so expectations are low.
- **Proposal P-1 (H4, not an arm without the owner's written sign-off):**
  - An initial stop of 2 × ATR14 (minimum 4%).
  - Each position sized to a fixed 1% of account risk, still capped at 2% of 50-day dollar volume.
  - It conflicts with `risk_rules.stop_loss.hard_max_pct = 10%`, so it is a strategy change, not a parameter.
  - If the owner signs off before 2026-09-28, it enters as **B4 = B1 + P-1** in the secondary family. If the sign-off comes later, P-1 starts its own clock on that date and is never back-dated.

## 2. Mechanics

- **Timing:**
  - Day 1 is 2026-09-28. The first signals are generated at its close, and the first simulated fills are at the 2026-09-29 open.
  - A daily job runs after the close (about 18:00 ET).
- **Daily job:**
  1. Fetch the day's bars for the universe and the benchmarks. Store the raw snapshot.
  2. Add the SEC filings accepted by the signal time to the fundamentals store. The MarketSpec usability rule applies: an 8-K before 16:00 ET is usable the same day; everything else the next day.
  3. Run one engine step per arm, with the engine's own code, stops and exit rules.
  4. Queue orders for the next open.
- **Fills and costs:**
  - Orders fill at the next day's actual open, with the engine's US costs: IBKR fixed commission plus square-root slippage.
  - The 2% dollar-volume liquidity cap and T+1 settlement apply.
  - Every arm starts with the same virtual equity as the backtests.
- **Virtual money only (hard rule):**
  - The paper-trading code has no order-routing path.
  - No broker SDK, credentials or API keys may exist in its repository or environment.
  - Real-money trading is outside this experiment, is the owner's decision alone, and is never executed by an agent.
- **Append-only log:**
  - One file per trading day, `paper_trading/exp3/log/YYYY-MM-DD.jsonl`, holding for each arm: the inputs' hashes, candidates, ratings, orders, fills, positions and equity.
  - Each file stores the SHA-256 of the previous day's file, forming a hash chain, plus the code commit and the config hash.
  - The file is committed that day and **pushed to a remote**, so an outside party witnesses the timestamp.
  - Files are never edited. A correction is a new, dated entry that points at the old one.
- **Code freeze:**
  - The arms' code is the commit recorded on Day 1.
  - A fix is allowed only for a crash or an auditor mismatch. It applies from the next day on and is logged as an amendment. Past days are never re-run.
- **Data revisions:**
  - The ledger uses bars as they were fetched that day, and later Yahoo revisions are ignored.
  - A missed day is processed late from that day's archived snapshot, with identical code, and flagged LATE.
- **Weekly audit:** `independent_auditor` recomputes each arm's ledger from the log once a week. A mismatch makes that arm **INVALID** until it is fixed going forward.

## 3. Success criteria and minimum duration

**Primary metric.** Daily excess return of an arm over the **MDY/IJR 50/50 blend** (total return). The secondary benchmark is the equal-weight basket of the frozen universe, rebalanced monthly.

**Test.** The same test as experiment 2: a one-sided stationary block bootstrap (mean block 20 days, 10,000 resamples, seed 7) of the mean daily excess return, with H0: mean ≤ 0.

**Power.** For iid daily returns, the standard error of an annualised Sharpe estimate after T years is about 1/√T (Lo 2002). The table uses one-sided α = 0.10 unless stated.

| Question | Answer |
|---|---|
| Years needed to tell an excess Sharpe of 1.0 from 0 at 80% power, α = 0.10 | **4.5** (6.2 at α = 0.05) |
| The same in trades, at 40–90 trades a year | 180–410 (250–560 at α = 0.05) |
| With realistic 1.3× variance inflation (fat tails, clustered trades) | about 6 years |
| Smallest excess Sharpe detectable at 80% power after 1 / 2 / 3 / 5 years | 2.1 / 1.5 / 1.2 / 0.95 |
| Power to detect a true Sharpe of 1.0 after 1 / 2 / 3 / 5 years | 39% / 55% / 67% / 83% |

**The honest answer is years.** A 12-month run can only expose a gross failure or confirm an exceptional edge (Sharpe above about 2). It cannot confirm a good strategy.

**Decision schedule.** The primary arm is tested with a Haybittle–Peto design:

| Look | Date | Rule |
|---|---|---|
| Early PASS | 24 and 36 months | Only if p < 0.005. It has 80% power at an excess Sharpe of 2.4 (at 24 months) or 2.0 (at 36 months). |
| **Futility (binding)** | 24 months | If the primary arm's observed excess Sharpe is ≤ 0, stop it with verdict **FAIL**. This wrongly stops a true Sharpe-1.0 arm 8% of the time. |
| **Final** | 60 months (2031-09-26) | At α = 0.10. |

**No PASS may be declared before 24 months and 100 closed trades** in the arm.

**Verdicts per arm:**

| Verdict | Condition |
|---|---|
| PASS | Excess p below the applicable threshold, **and** CAGR above both benchmarks, **and** the auditor matches the log, **and** the arm was not killed |
| FAIL | Excess CAGR ≤ 0 at a final or futility look, or the arm was killed |
| INVALID | An auditor mismatch that was not resolved |
| INCONCLUSIVE | Anything else |

Every look also reports: Sharpe with its Lo standard error; returns by calendar quarter against both benchmarks; trades; exit reasons; and, for C, the days on which the rating changed a purchase.

## 4. Multiple testing

- **One primary test:** arm **B1** vs the MDY/IJR blend. B1 is the arm with the strongest in-sample evidence, H1 + H2. The lead may swap the primary before Day 1, but never after.
- **Secondary family:** A, B2, B3, C (and B4 if signed off) vs the blend, controlled with **Holm at a family α of 0.10**, at the final look only.
  - Holm is valid for these correlated arms, which share a universe.
  - The strictest Holm step is 0.025 one-sided, which needs about 7.9 years for Sharpe 1.0. Secondary arms will rarely be confirmed; this is stated now so it is not a surprise later.
- **Pairwise contrasts** (B2 − B1, B3 − B2, C − B1, B1 − A) are **descriptive only**. Their differences are smaller than the effects above, and they are unpowered for years.
- **No switching:** no arm is promoted to primary on the strength of forward results.

## 5. Kill criteria (per arm, binding)

- **Drawdown:** equity more than **25% below its running peak** (experiment 2's drawdown limit). The arm is flattened at the next open and stopped, with verdict FAIL. This applies in a market-wide crash too, because real capital would suffer the same.
- **Integrity:** INVALID for more than 10 trading days, or a break in the hash chain that cannot be explained, stops the arm.
- **Not a kill, only a flag:** fewer than 10 trades in the first 6 months means the arm is probably broken. It is investigated and fixed going forward only.
- **No other stops.** An arm is never stopped for looking disappointing. Only these rules and the 24-month futility look can end one.
