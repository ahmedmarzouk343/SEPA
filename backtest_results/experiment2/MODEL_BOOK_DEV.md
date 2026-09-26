# Model book: the 2022–2026 winners the SEPA funnel missed

Development window only (2022-01-03 .. 2026-09-24). Written 2026-09-26 by the "Fork 4" session for the experiment-2 lead.

This is a **descriptive, in-sample study**. No backtest was run. Every forward return below is a property of a ticker-day, not the result of a trade: there are no stops, slots or sizing. The rules at the end are **hypotheses**, and each one must be validated forward from 2026-09-25.

## Bottom line

1. **The funnel catches 12 of 447 big winners (2.7%)** on any day that still left at least +50% to the peak. Experiment 1's frozen ×1.6 volume setting catches 8 (1.8%).
   - The first stage that blocks a winner on its best day:

     | Stage | Share of winners |
     |---|---|
     | Trend Template | **52%** |
     | Fundamentals | **30%** |
     | VCP | 10% |
     | RS | 5% |
     | Regime gate | 0% |
2. **Blocking winners is not the same as being wrong.** Across all the stocks the funnel passes, the funnel barely changes the odds of catching a winner:
   - The share of ticker-days that double within 126 days goes from 1.7% (every liquid ticker-day) to 2.3% (days that pass the whole funnel).
   - The share that reach +50% goes from 10.0% to 15.7%.
   - The median 63-day return is no better than the universe's.
3. **RS is the only filter that clearly separates winners from losers**, and it is too loose at 70. Among volume breakouts, the rate of doubling within 126 days by RS:

   | RS percentile | Doubled within 126 days |
   |---|---|
   | above 95 | 6.2% |
   | 70 to 95 | 0.9–2.3% |
   | below 70 (days that passed the rest of the funnel) | 0% |
4. **Three filters block winners and losers alike:**
   - **VCP.** Volume days with a rejected base did as well as VCP-ready days. A plain 50-day-high breakout on volume gives 2.2× as many entry days with at least as good outcomes.
   - **Fundamentals.** It removes 77% of the days that pass the other four filters and barely changes their outcomes.
   - **Trend Template.** It mostly delays entry. When it first passes, the median upside left to the peak is 56%, against 127% at the low.
5. **Volatility is the strongest trait of the doublers, and it collides with the stop.**
   - On their first Stage-2 day, winners had a median ATR of 4.6% of price, against 3.2% for the stocks the funnel picked that did not reach +50%.
   - Among breakout candidates with ATR of 5–7%, 12% doubled, but 55% closed 8% or more below entry within 20 days.
   - This matches experiment 1's pattern: 55–68% of trades were stopped out within 5–9 days.

## Rules followed

- **Window.** Only 2022-01-03 .. 2026-09-24 was studied.
  - Earlier bars were used only as indicator lookback: moving averages, the 52-week high and low, RS, the 400-bar VCP window, and 50-day dollar volume.
  - Nothing that any stock did in 2017–2021 was looked at, ranked or described.
  - Winner-window days before 2022-01-03 were not evaluated.
- **Read-only.** Nothing was written outside `kashif_data/experiment2/model_book_dev/` and this file. No commits.
- **CPU.** A single process throughout.
- **Data:**
  - Prices: `P.load` (split-adjusted, with load-time corrections and history breaks). The winner scan was re-run after the history-break table changed: nothing changed except the 3 DAVE shell bars dropped. VCP was recomputed for the 17 tickers that have a price break or correction.
  - Panel: `kashif_data/panels/US_idx`, the rebuild with file time 2026-09-26 02:25. Its `tt_core` matches my price-only Trend Template recomputation on all 1,060,501 ticker-days.
  - Fundamentals: the engine's own `fundamentals.daily_verdicts`, i.e. `screen()` at every date where the verdict can change. It was run at 03:20–03:26 on the final store (store files written 03:19).
  - VCP: the exact `signals._vcp_worker` call, i.e. `evaluate_entry_timing` on the last **400** bars at the loosest ×1.2 multiple (the brief said about 260, but the engine uses 400). 1.4 and 1.6 are applied afterwards from the stored breakout volume ratio.

## 1. The winners

**Definition.** A start day s ≥ 2022-01-03 whose split-adjusted close at least doubles within the next 126 trading days, with the peak also inside the window. The start day must also have:
- a **raw** close of at least $10 (the price actually traded that day; the split-adjusted close understates it when a split came later);
- a 50-day average dollar volume of at least $5M.

**Episodes.** Episodes are taken greedily per ticker, largest gain first, and overlapping starts are merged into one.
- **L** is the low (the run start).
- **P** is the peak.
- **B** is the breakout day: the first close after L above the highest close of the prior 50 days.
- **Window E ("catchable")** runs from L to the last day that still left at least +50% to P. It is the main evaluation window. L±10 and B±10 are also reported.

**What was found: 447 episodes on 286 tickers.**
- Median gain L→P is +131% over 115 trading days.
- B comes a median 19 days after L, and leaves +82% to the peak.
- By year of L:

  | 2022 | 2023 | 2024 | 2025 | 2026 |
  |---|---|---|---|---|
  | 66 | 72 | 66 | 171 | 72 |

  The episodes cluster after market-wide lows: 78 started in 2025 Q2 and 43 in 2023 Q4.

**What the runs look like.** Most are recoveries from deep declines, not breakouts from tight bases near highs:
- The median decline into L from the prior 252-day high is −41%, and 51% fell 40% or more.
- At B the median stock is still 22% below its 52-week high. Only 37% are within 15% of it.

### The largest 30 gains and what blocked them

The "best day in E" is the day the episode got furthest through the funnel (the earliest such day).

| Ticker | Low | Peak | Gain | Best day in E | Upside left then | Got to | Blocked by | RS | Exp-1 trades |
|---|---|---|---|---|---|---|---|---|---|
| MXL | 2026-03-06 | 2026-06-30 | +714% | 2026-04-02 | +612% | fund | FAIL: Q1 FAIL: current EPS -0.17 is a loss | 83 |  |
| CAR | 2026-02-23 | 2026-04-21 | +714% | 2026-02-23 | +714% | tt | TT fails tt_1,tt_2,tt_5,tt_6,tt_7,tt_8b | 35 |  |
| LEU | 2025-04-21 | 2025-10-15 | +596% | 2025-06-05 | +220% | fund | FAIL: Q1=PASS, Q2=PASS, Q3=PASS, Q4=FAIL | 99 |  |
| SEZL | 2024-05-28 | 2024-11-25 | +571% | 2024-09-13 | +209% | vcp | volume < 1.2x | 94 |  |
| SEZL | 2025-04-04 | 2025-07-03 | +535% | 2025-05-16 | +94% | fund | FAIL: Q1=PASS, Q2=FAIL, Q3=PASS, Q4=PASS [BREAKOUT_YEAR] | 100 |  |
| ICHR | 2025-12-31 | 2026-06-30 | +509% | 2026-01-29 | +235% | fund | FAIL: Q1 FAIL: EPS growth -737.5% < 20% | 75 |  |
| UCTT | 2025-12-31 | 2026-06-30 | +463% | 2026-01-21 | +202% | fund | FAIL: Q1 FAIL: EPS growth -380.0% < 20% | 72 |  |
| MP | 2025-05-27 | 2025-10-14 | +426% | 2025-06-04 | +301% | fund | SKIP: EPS_GROWTH_UNDEFINED | 92 |  |
| HIMS | 2024-09-06 | 2025-02-19 | +404% | 2024-11-25 | +119% | QUALIFIED | entry signal | 99 |  |
| PENG | 2026-03-30 | 2026-07-09 | +401% | 2026-03-30 | +401% | tt | TT fails all nine | 31 |  |
| GME | 2024-04-22 | 2024-05-14 | +387% | 2024-04-22 | +387% | tt | TT fails all nine | 2 |  |
| ARWR | 2025-07-21 | 2025-12-11 | +381% | 2025-10-15 | +85% | fund | FAIL: Q1 FAIL: EPS growth 8.7% < 20% | 97 |  |
| VSH | 2025-12-01 | 2026-06-03 | +365% | 2026-04-07 | +237% | vcp | volume < 1.2x | 77 |  |
| VICR | 2025-10-20 | 2026-04-22 | +357% | 2025-11-14 | +198% | fund | FAIL: Q1=PASS, Q2=PASS, Q3=PASS, Q4=FAIL | 94 |  |
| DAVE | 2024-11-05 | 2025-05-09 | +344% | 2025-05-06 | +58% | QUALIFIED | entry signal | 99 | 1 (best +14%) |
| DOCN | 2025-11-04 | 2026-05-06 | +315% | 2025-12-05 | +233% | vcp | volume < 1.2x | 84 |  |
| CYTK | 2023-10-03 | 2024-01-08 | +302% | 2023-10-03 | +302% | tt | TT fails all nine | 3 |  |
| VSAT | 2025-05-21 | 2025-10-31 | +298% | 2025-08-05 | +87% | fund | FAIL: Q1 FAIL: EPS growth -136.2% < 20% | 71 |  |
| VIAV | 2025-10-29 | 2026-05-01 | +296% | 2025-11-17 | +231% | fund | FAIL: Q1 FAIL: EPS growth -900.0% < 20% | 95 |  |
| CORT | 2026-03-13 | 2026-08-25 | +284% | 2026-03-13 | +284% | tt | TT fails all nine | 5 |  |
| FORM | 2025-10-22 | 2026-04-24 | +276% | 2025-11-07 | +197% | fund | FAIL: Q1 FAIL: EPS growth -16.7% < 20% | 86 |  |
| CAR | 2025-03-13 | 2025-07-24 | +274% | 2025-06-18 | +60% | fund | FAIL: Q1 FAIL: EPS growth -347.0% < 20% | 73 |  |
| VSXY | 2025-07-16 | 2026-01-09 | +272% | 2025-11-28 | +59% | fund | FAIL: Q1 FAIL: EPS growth -50.0% < 20% | 73 |  |
| KTOS | 2025-04-07 | 2025-10-07 | +267% | 2025-04-09 | +226% | fund | FAIL: Q1=PASS, Q2=FAIL, Q3=PASS, Q4=PASS [BREAKOUT_YEAR] | 97 |  |
| TTMI | 2025-12-17 | 2026-06-22 | +260% | 2025-12-18 | +230% | vcp | volume < 1.2x | 99 |  |
| SITM | 2025-11-20 | 2026-05-11 | +257% | 2026-02-05 | +120% | vcp | DAILY_BASE_REJECTED:CONTRACTION_COUNT_OUT_OF_RANGE | 96 |  |
| STRL | 2025-04-04 | 2025-09-23 | +254% | 2025-06-09 | +83% | fund | FAIL: Q1=PASS, Q2=PASS, Q3=FAIL, Q4=PASS [BREAKOUT_YEAR] | 95 |  |
| AVAV | 2025-04-04 | 2025-10-06 | +251% | 2025-04-09 | +185% | tt | TT fails tt_1..tt_6, tt_8b | 45 |  |
| LIF | 2025-04-08 | 2025-10-06 | +251% | 2025-06-10 | +77% | vcp | volume < 1.2x | 99 |  |
| STRL | 2025-12-17 | 2026-06-04 | +250% | 2026-01-15 | +195% | fund | FAIL: Q1=PASS, Q2=FAIL, Q3=PASS, Q4=PASS [BREAKOUT_YEAR] | 96 |  |

All 447 episodes are in `model_book_dev/modelbook.csv`.

## 2. The funnel

### Episodes

A winner counts at a stage if at least one day in window E passes every stage up to and including that one.

| Stage (cumulative) | Episodes | Share |
|---|---|---|
| Winner episodes | 447 | 100% |
| Market regime gate open (OR) | 447 | 100.0% |
| + Trend Template tt_1..tt_8b | 214 | 47.9% |
| + RS percentile ≥ 70 | 192 | 43.0% |
| + Fundamentals PASS | 58 | 13.0% |
| + VCP price-ready (×1.2) = **caught** | **12** | **2.7%** |
| caught with experiment 1's frozen ×1.6 | 8 | 1.8% |
| caught with the 2-of-3 regime gate | 10 | 2.2% |

The share caught in the narrower windows is lower still:

| Window | Caught (×1.2) | Caught (×1.6) |
|---|---|---|
| L ± 10 days | 0.2% | 0.2% |
| B ± 10 days | 0.7% | 0.4% |
| E | 2.7% | 1.8% |

**How much was left when each stage first passed** (within [L, P]):

| First day passing through | Episodes reaching it | Median upside left | Interquartile range |
|---|---|---|---|
| Regime (i.e. at the low) | 447 | +127% | +108% .. +164% |
| + Trend Template | 344 | +56% | +28% .. +101% |
| + RS ≥ 70 | 325 | +53% | +23% .. +97% |
| + Fundamentals PASS | 116 | +42% | +16% .. +75% |
| + VCP price-ready | 22 | +48% | +17% .. +65% |

### Ticker-days

This covers all liquid days (raw close ≥ $10 and 50-day dollar volume ≥ $5M) with a full 126-day forward horizon, i.e. up to about 2026-03.

| Stage (cumulative) | Ticker-days | Tickers | Doubled in 126 days | Reached +50% in 126 days | Median 63-day return |
|---|---|---|---|---|---|
| liquid days | 940,311 | 992 | 1.7% | 10.0% | 0.9% |
| + regime | 910,415 | 992 | 1.7% | 9.9% | 0.8% |
| + TT | 178,578 | 962 | 1.9% | 10.7% | 0.3% |
| + RS ≥ 70 | 132,810 | 903 | 2.3% | 12.2% | 0.7% |
| + fundamentals PASS | 28,505 | 517 | 2.4% | 13.2% | 0.3% |
| + VCP ready | 926 | 174 | 2.3% | 15.7% | 0.7% |

## 3. What blocked them

### The first failing stage on each episode's best day in E

| Furthest the episode got | Episodes | Share |
|---|---|---|
| blocked at the Trend Template | 233 | 52.1% |
| blocked at RS | 22 | 4.9% |
| blocked at fundamentals | 134 | 30.0% |
| blocked at VCP | 46 | 10.3% |
| QUALIFIED | 12 | 2.7% |

Days in E on which exactly one filter blocked a winner:

| That one filter | Episodes with at least one such day |
|---|---|
| VCP | 58 |
| Fundamentals | 38 |
| Trend Template | 10 |
| RS | 0 |

### Trend Template criteria

The "winner E-days" column is the share of days in window E, pooled over all episodes.

| Criterion | Winner E-days failing | All liquid days failing |
|---|---|---|
| tt_1 close > 150-day MA | 31.4% | 46.5% |
| tt_2 close > 200-day MA | 34.6% | 46.6% |
| tt_3 150-day MA > 200-day MA | 45.3% | 45.4% |
| tt_4 200-day MA rising 21 days | 42.5% | 45.6% |
| tt_5 50-day MA > 150-day MA | 43.1% | 45.8% |
| tt_6 50-day MA > 200-day MA | 44.4% | 45.8% |
| tt_7 close > 50-day MA | 25.0% | 47.8% |
| tt_8a ≥ 30% above the 52-week low | 17.1% | 50.0% |
| tt_8b within 25% of the 52-week high | **44.1%** | 33.8% |

- The price criteria (tt_1, tt_2, tt_7, tt_8a) fail on winners *less often* than on the average stock.
- What holds winners back is the lagging moving-average stack (tt_3–tt_6), which is no more selective for winners than for any stock, and tt_8b, which fails more often for winners because they come off deep lows.

### Fundamentals

These are winner E-days that passed regime, TT and RS but failed fundamentals.

| Reason | Days | Share | Episodes |
|---|---|---|---|
| Q1 FAIL: EPS growth < 20% | 2,534 | 42.1% | 86 |
| only Q4 fails (annual EPS) | 1,112 | 18.5% | 31 |
| only Q2 fails (2-quarter acceleration; the store tags these BREAKOUT_YEAR) | 1,010 | 16.8% | 37 |
| only Q2 fails (no BREAKOUT_YEAR tag) | 299 | 5.0% | 10 |
| SKIP: EPS growth undefined | 267 | 4.4% | 10 |
| Q3 fails (sales), plus other combinations | about 490 | about 8% | about 18 |
| Q1 FAIL: current EPS is a loss | 200 | 3.3% | 11 |

- On the first day a winner passed regime, TT and RS, only 18% passed fundamentals.
- 25% had a GAAP loss in the latest quarter.
- The semiconductor-equipment cycle names (ICHR, UCTT, FORM, VIAV) failed Q1 on deeply negative EPS growth while their price had already turned.

### VCP

These are winner E-days that passed every earlier stage.

| Reason | Days | Share | Episodes |
|---|---|---|---|
| volume < 1.2× on the day | 1,389 | 77.0% | 57 |
| DAILY_BASE_REJECTED: contraction count out of range | 200 | 11.1% | 30 |
| NO_WEEKLY_BASE | 67 | 3.7% | 9 |
| weekly or daily base: monotonicity failed | 97 | 5.3% | 19 |
| other | 52 | 2.9% | — |

## 4. Is the blocking filter the problem? (discrimination)

**How to read these tables:**
- Each group is ticker-days that pass the *other* filters.
- "Excess" is the ticker's return minus the median return of all liquid tickers on the same day. This removes market timing.
- Population: liquid days with a full 126-day horizon.

| Filter | Filter passes: days / doubled / +50% / median excess 63-day | Filter fails: days / doubled / +50% / median excess 63-day | Verdict |
|---|---|---|---|
| Regime (OR) | 926 / 2.3% / 15.7% / +0.7% | 22 / 0.0% / 0.0% / −7.1% | Closed on too few days to judge |
| Trend Template | 926 / 2.3% / 15.7% / +0.7% | 497 / **7.4%** / 16.7% / −0.6% | Fatter right tail when it fails, worse median; mixed |
| RS ≥ 70 | 926 / 2.3% / 15.7% / +0.7% | 95 / **0.0%** / 4.2% / +2.8% | Separates the tail; keep |
| Fundamentals PASS | 926 / 2.3% / 15.7% / +0.7% | 3,137 / 1.9% / 10.6% / +0.9% | Weak: removes 77% of days, similar median |
| VCP ready | 926 / 2.3% / 15.7% / +0.7% | volume ≥ 1.2×, base rejected: 5,878 / 2.6% / 13.6% / +0.3% | Does not separate |
| *Alternative trigger:* close > prior 50-day high on ≥ 1.2× volume | 2,075 / **3.3%** / 13.4% / **+1.0%** | — | 2.2× the entry days, at least as good |

### Fundamentals by reason

This uses the broad breakout set: regime + TT + RS ≥ 70, on a day with volume ≥ 1.2× and either a 50-day-high close or VCP-ready. That is 12,109 days on 823 tickers.

| Fundamentals class | Days | Doubled | +50% | Median excess 63-day |
|---|---|---|---|---|
| PASS | 2,654 | 2.8% | 14.3% | +0.9% |
| Q1: EPS growth < 20% | 4,906 | 2.3% | 10.9% | +0.6% |
| fails only Q2 (acceleration) | 1,585 | 3.2% | 15.3% | +1.4% |
| fails only Q4 (annual) | 1,467 | 4.1% | 16.0% | +2.4% |
| fails Q2 + Q4 | 227 | 0.0% | 4.4% | −2.7% |
| fails Q3 + Q4 | 217 | 1.4% | 12.0% | −2.5% |
| Q1: current EPS is a loss | 195 | 3.6% | 24.6% | +3.9% |
| SKIP: stale, no data, or latest EPS missing | 238 | 0.4% | 4.6% | −3.5% |
| SKIP: EPS growth undefined | 191 | 5.8% | 17.8% | −0.1% |

### RS on the same breakout set

The set here is regime + TT + a 50-day-high close on volume, without the fundamentals gate.

| RS | Days | Tickers | Doubled | +50% | Median excess 63-day |
|---|---|---|---|---|---|
| ≤ 70 | 2,261 | 626 | 1.3% | 6.1% | −0.5% |
| 70–80 | 1,867 | 581 | 0.9% | 5.5% | +0.9% |
| 80–90 | 2,925 | 626 | 1.7% | 8.8% | +0.6% |
| 90–95 | 2,008 | 457 | 2.3% | 12.4% | −0.0% |
| **> 95** | 2,732 | 349 | **6.2%** | **24.0%** | **+1.6%** |

### Volatility and stop-out risk

The set is breakout candidates: regime + TT + volume ≥ 1.2× + (50-day high or VCP-ready). ATR is the panel's 14-day ATR as a percentage of price.

| ATR | Days | Doubled | +50% | Median excess 63-day | Closed ≥ 8% below entry within 20 days |
|---|---|---|---|---|---|
| ≤ 2% | 1,547 | 0.0% | 1.9% | +1.1% | 16% |
| 2–3% | 6,426 | 0.4% | 5.6% | +0.4% | 26% |
| 3–4% | 4,343 | 2.0% | 11.8% | −0.3% | 36% |
| 4–5% | 1,729 | 5.3% | 25.2% | +1.3% | 44% |
| 5–7% | 959 | 11.9% | 35.9% | +4.0% | 55% |
| > 7% | 181 | 25.4% | 42.5% | +2.4% | 65% |

VCP-ready and not-ready candidates have the same ATR distribution (median 2.9–3.0%). **VCP is not what filters out volatile names.**

## 5. What the winners had in common at the start

The two winner groups:
- **WINNER_B** is the winners on their breakout day B.
- **WINNER_T** is the 192 winners on their first day in E that passed regime + TT + RS, i.e. the day a Stage-2 screen could first have listed them.

The two reference groups (random samples, seed 7, full horizon, **did not reach +50% in 126 days**):
- **QUAL_LOSE** is days the funnel qualified.
- **BO_LOSE** is 50-day-high breakouts on volume.

EPS and sales growth are the latest known quarter, year on year, from the point-in-time snapshot.

| Median | WINNER_B (446) | WINNER_T (192) | QUAL_LOSE (781) | BO_LOSE (1,500) |
|---|---|---|---|---|
| EPS growth (latest quarter YoY) | +20% | +50% | +154% | +15% |
| Sales growth | +10% | +13% | +20% | +8% |
| RS percentile | 55 | 90 | 90 | 72 |
| **ATR14 % of price** | **4.5%** | **4.6%** | 3.2% | 2.9% |
| Raw price | $39 | $48 | $69 | $59 |
| Distance below the 52-week high | −22% | −8% | −3% | −3% |
| Base length (days since the 252-day high) | 142 | 18 | 5 | 75 |
| Base depth (deepest close since that high) | 45% | 17% | 5% | 17% |
| 50-day dollar volume | $41M | $52M | $42M | $32M |
| Listed less than 4 years* | 13% | 11% | 11% | 9% |

*The price cache starts in 2014-06, so listing ages are capped there.

| Share of the group | WINNER_B | WINNER_T | QUAL_LOSE | BO_LOSE |
|---|---|---|---|---|
| Fundamentals PASS | 17% | 18% | 100% | 16% |
| Latest quarter a GAAP loss | 34% | 25% | 0% | 15% |
| EPS growth ≥ 20% | 48% | 63% | 100% | 45% |
| Sales growth ≥ 20% | 32% | 35% | 49% | 22% |
| RS ≥ 95 | 17% | 33% | 32% | 11% |
| ATR ≥ 5% | 35% | 40% | 9% | 7% |
| Price < $30 | 40% | 28% | 16% | 22% |
| Within 10% of the 52-week high | 27% | 59% | 90% | 69% |

**The pattern.** Compared with the funnel's losing picks, the winners were:
- more volatile;
- cheaper;
- further off their highs, coming out of deeper and longer bases;
- carrying **lower** reported EPS and sales growth.

Their price turned before their reported earnings did.

**What does not distinguish them:**
- RS on the Stage-2 day: both groups have a median of 90, but winners reach RS ≥ 95 about as often as the losing picks do.
- Listing age.

## 6. Experiment 1 and the winners

Experiment 1 (TUNE_final + HOLDOUT_primary, a slightly bigger universe and older data) traded 12 of the 447 episodes, 19 trades in all. Six of them are among the 12 that today's funnel qualifies.

| Exits (of 19 trades) | Count |
|---|---|
| Stop loss | 9 |
| Defensive profit target (+11–13%) | 7 |
| Trailing stop | 3 |

- The best results were AR +51% (of +185%), RRC +24% (of +110%) and LTH +18% (of +108%).
- DAVE was sold at +13.5% out of a +344% run.
- BTSG was traded 5 times inside one +110% run.

Exits are already addressed by Amendment 3 (V5–V10 exit_mode "run", and defensive off). They are not repeated as a hypothesis here.

## 7. Hypotheses (at most 5)

Each of these was picked in-sample from about 40 cuts of the same window, so each is **a hypothesis, to be validated forward from 2026-09-25, not on 2017-2021.** None may be added to experiment 2's locked rules.

1. **Entry trigger: replace VCP price-ready with "close above the prior 50-day closing high on ≥ 1.2× volume"**, keeping the other filters.
   - VCP-rejected volume days did as well as VCP-ready days: doubled 2.6% vs 2.3%.
   - The simple trigger gives 2.2× the entry days, doubled 3.3%, median excess +1.0%.
   - 77% of the VCP blocks on winners were simply "no volume day".
   - *Hypothesis, to be validated forward from 2026-09-25, not on 2017-2021.*
2. **RS: raise the floor to 95, or rank candidates by RS before anything else.**
   - Among volume breakouts, doubling was 6.2% above RS 95 against 0.9–2.3% for 70–95, and +50% was 24% against at most 12%.
   - RS is the one filter whose failures were clearly worse.
   - *Hypothesis, to be validated forward from 2026-09-25, not on 2017-2021.*
3. **Fundamentals: keep Q1, double failures, and the stale/no-data/missing-EPS skips as vetoes; demote a single Q2 or Q4 failure to a ranking penalty.**
   - Days failing only Q2 or only Q4 did at least as well as PASS days: doubled 3.2% and 4.1% vs 2.8%, median excess +1.4% and +2.4% vs +0.9%.
   - Double failures and the stale/no-data skips did clearly worse.
   - Q2 alone (25) or Q4 alone (23) blocked the best day of 48 winner episodes.
   - *Hypothesis, to be validated forward from 2026-09-25, not on 2017-2021.*
4. **Stop from volatility, not a fixed percentage:** an initial stop of about 2× ATR14, with the position sized to a fixed account risk. This replaces the 6–10% cap.
   - The doublers' median ATR is about 4.5–4.6%.
   - 55% of the 5–7%-ATR candidates close 8% or more below entry within 20 days, yet 12% of them double.
   - This conflicts with the config's 10% hard maximum. It is a rule change, not a grid value.
   - *Hypothesis, to be validated forward from 2026-09-25, not on 2017-2021.*
5. **An early Stage-2 path for leaders:** for RS ≥ 95, accept close above the 50-, 150- and 200-day moving averages (tt_1, tt_2, tt_7) without waiting for tt_3–tt_6 and tt_8b.
   - On RS ≥ 95 50-day-high volume breakouts, those days doubled 10.3% vs 6.2% with the full Trend Template, with median excess +3.1% vs +1.6% (526 days, 135 tickers).
   - The full Trend Template first passes with a median 56% left to the peak, against 127% at the low.
   - *Hypothesis, to be validated forward from 2026-09-25, not on 2017-2021.*

## Caveats

- **Winners are defined after the fact.** Window E uses the future peak. It describes the moves; it is not a signal.
- **Days are not independent.** They overlap heavily; for example, 926 qualified days are 313 ticker-months on 174 tickers. Differences of 1–2 points in the doubling rate are within noise, and many cuts were examined.
- **Survivorship.** The universe is today's S&P 400 + 600 members. Stocks that rose into the index are included, and names that were dropped are missing. This inflates the winner count, most of all early in the window.
- **Regime concentration.** 219 of the 447 runs start between 2025 Q2 and 2026 Q1, and several RS/ATR effects are strongest in 2025–2026. In 2022–2023, the RS > 95 breakouts had a negative median excess return.
- **Forward statistics are not strategy returns.** No stops, slots, costs or sizing are applied. The 20-day drawdown column is the only path statistic.
- **Fundamentals are GAAP.** EPS is as-filed GAAP from the store. One-off losses (for example ICHR, UCTT and VIAV) fail Q1 even when adjusted earnings grew.

## Files (`kashif_data/experiment2/model_book_dev/`)

| File | What it holds |
|---|---|
| `01_winners.py` → `winners.csv`, `labels.parquet` | Episodes; forward labels per ticker-day |
| `02_vcp.py` → `vcp.parquet` | 281,495 VCP evaluations (`--patch` recomputes named tickers) |
| `03_tt_features.py` → `tt_px.parquet`, `episode_price_features.csv` | Price-only Trend Template, breakout flags, episode features |
| `04_funnel.py` → `fund.parquet`, `days.parquet` | Fundamentals verdicts and the joined ticker-day table |
| `05_analysis.py` → `episode_funnel.csv`, `discrimination.csv`, `funnel_counts.csv` | Per-episode funnel and the discrimination tables |
| `06_commonalities.py` → `commonalities.csv` | Winner vs reference-group profiles |
| `07_tables.py` → `tables.md` | Every table above, unrounded |
| `08_modelbook.py` → `modelbook.csv`, `modelbook_top.md` | One line per episode: best day and what blocked it |

The `*_nofund` files are the pre-fundamentals dry run, kept for reference.
