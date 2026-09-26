# Review: `fund_mode="rank_only"` and the S&P 1500 plan (F0/F1/F2)

**Reviewer:** Fork 3.

**Scope:** `main` at `b27e301`, covering:
- `kashif_engine/strategies/minervini_sepa_v1/module.py`: `fund_score`, the `prepare` branch, the `candidates` sort and the receipt fields;
- `kashif_engine/scripts/build_sp500_data.py`;
- the plan: F0 = book defaults on S&P 400/600; F1 = the same on S&P 1500; F2 = F1 + rank_only. It is measured by a faithfulness metric (his disclosed buys listed as candidates within ±30 days), on 2022–2026, and once on 2017–2021 labelled contaminated.

**Status labels:**
- **CONFIRMED:** traced in the code, or reproduced (the probe is `scratchpad/rev/rank_only_probe.py`, which reuses the synthetic world from `test_exp3_switches.py`).
- **PLAUSIBLE:** the mechanism is certain, but the specifics (such as index inclusion dates) still need checking against a source.

**Local test run:** `test_exp3_switches.py`, `test_minervini_rules.py` and `test_exp2_guards.py` give 51 passed. The default-behaviour differential against `71ba071` still passes.

## Bottom line

- **The code does what it says.** `rank_only` removes only the fundamentals veto. Trend template, RS, volume, regime and entry timing still apply, the defaults are unchanged, and the bundle refuses a switch mismatch. There are four small code issues (C1–C4). None changes a trade in F0 or F1.
- **The plan has three traps that could make F1/F2 look good for reasons unrelated to the rules:**
  - H1: current S&P 500 membership selects past winners, the opposite of 400/600;
  - H2: the fundamentals data for the 475 new names isn't verified, and the split table misses most of their splits;
  - H3: the faithfulness metric is circular and has no base rate.
- **Fix H2 before any run.** Report H1 and H3 as described below.

| ID | Sev | Status | One line |
|---|---|---|---|
| H1 | HIGH | PLAUSIBLE (mechanism certain, dates to verify) | Current S&P 500 members were selected by later success and GAAP-profit eligibility: survivorship with the opposite sign to 400/600 |
| H2 | HIGH | CONFIRMED | The split table misses 19 of 26 well-known S&P 500 splits (GE's 1-for-8 reverse split too), and there are no history breaks for S&P 500 spin-offs |
| H3 | HIGH | CONFIRMED (design) | Faithfulness is measured on the same 77 buys that motivated the changes, and it rises mechanically with candidate volume |
| M1 | MED | CONFIRMED | F0→F1 changes three things at once: the tradable names, every name's RS percentile, and the regime breadth |
| M2 | MED | CONFIRMED | The EW benchmark and `index_universe()` are hard-coded to S&P 400+600 |
| M3 | MED | CONFIRMED | `rank_only` is mostly "no fundamentals": the score only matters when candidates exceed free slots |
| M4 | MED | CONFIRMED | Decision receipts label rank_only-admitted names as REJECTED/SKIPPED_fundamentals |
| M5 | MED | CONFIRMED | 2017–2021: experiment 2's finished lock refuses every run; a new lock must not weaken it |
| M6 | MED | PLAUSIBLE | Dual-class lines (GOOG/GOOGL, FOX/FOXA, NWS/NWSA) mean two positions in one company, and GOOG has no split entry |
| C1 | LOW | CONFIRMED | `fund_score` counts SKIPPED as pass inside a PASS verdict but as fail inside a FAIL verdict |
| C2 | LOW | CONFIRMED | No data, stale data and a Q1 growth fail all score 0 |
| C3 | LOW | CONFIRMED | `soft_single` candidates report `fund_score = 4` although they failed Q2 or Q4 |
| C4 | LOW | CONFIRMED | No test covers rank_only's `prepare()` or `candidates()` |

---

## HIGH

### H1. Current S&P 500 membership is a look-ahead, winner-selected universe (survivorship with the opposite sign to 400/600)
- **Status:** PLAUSIBLE. The mechanism follows from S&P's methodology; the specific inclusion dates must be checked against S&P announcements.
- **Where:** `build_sp500_data.py:5-9` (Wikipedia's *current* constituents, used for every date).
- **Mechanism:**
  - S&P adds a company to the 500 after its market value has grown, and only once it meets GAAP-profitability eligibility.
  - In current **400/600**, the biggest past winners are *missing*: they graduated to the 500. That is a bias *against* momentum.
  - In current **500**, the reverse holds: it contains names that entered *because* they ran.
  - So F1 − F0 is biased upward by construction, even if the rules add nothing.
- **Concrete class (dates to verify):** large 2021–2025 momentum names that were in **no** S&P index for much of the test period, because they weren't GAAP-profitable, and were added to the 500 later. Examples: PLTR (about 2024), UBER and ABNB (about 2023), APP, HOOD, COIN and DASH (about 2025).
  - A current-member universe lets F1/F2 trade them in 2021–2024. No S&P-1500 rule applied at the time would have.
  - Several of these are exactly the kind of names in his disclosed list, which also inflates faithfulness.
- **Fix:**
  1. **Point-in-time eligibility, at least for additions.** Wikipedia's "Selected changes to the list of S&P 500 components" table gives dated additions and removals. A name joining the S&P 1500 after the window start becomes tradable from its inclusion date only; before that, it can still count in RS and regime so the reference set stays full.
     - Check any name added to the 500 from the 400/600 separately. It was already in the 1500, so it was eligible throughout.
  2. Report F1 twice: with current membership and with inclusion-date gating. The gap measures this bias.
  3. Use an **equal-weight current-member S&P 1500 basket** as the survivorship-matched benchmark (see M2).

### H2. The fundamentals data for the new S&P 500 names isn't verified: splits and history breaks are missing
- **Status:** CONFIRMED (lookup in `fundamentals_store.STOCK_SPLITS` and `kashif_engine/data/history_breaks.csv` at `b27e301`).
- **What's missing:**
  - **Splits:** 19 of 26 well-known S&P 500 splits have no entry: `ANET, APH, AVGO (10:1 2024), CMG (50:1 2024), CPRT, CSX, CTAS, DECK, DXCM, FTNT, GOOG, ISRG, LRCX, MNST, ODFL, SHW, TSCO, TSLA (2020, 2022), WRB`.
    - `GE`'s **1-for-8 reverse split (2021)** is also missing.
    - `GOOGL` has its 2022 20:1 split, but `GOOG` doesn't.
    - The table holds 139 tickers, verified for the 400/600 universe plus the extras only.
  - **History breaks:** 30 rows, all small/mid names. There's nothing for S&P 500 spin-offs and reshapes: GE→GEHC/GEV, JNJ→KVUE, MMM→SOLV, T→WBD, DD/DOW/CTVA, UTX→CARR/OTIS/RTX.
- **Failing scenarios (EPS is stored as filed and split-adjusted at query time):**
  - **AVGO or TSLA after a forward split:** the year-ago EPS isn't rescaled, so YoY reads about −90% (10:1) or −67% (3:1). **Strict F1 vetoes these names on a data error**, which understates F1. Under rank_only their score is wrong.
  - **GE after 2021-08:** the year-ago EPS isn't rescaled by 8, so YoY reads about **+700%**. That is a **false Q1 PASS**, the non-conservative direction.
  - **CMG 50:1:** Check 5's implied-shares test sees a 50× jump and rejects the quarters on one side of the split. That produces EPS gaps, which (per the earlier review, H1) switch off Q2 and Q4 in the strict screen.
  - **Spin-off parents:** YoY is compared across a different company.
- **Fix, before any F1/F2 run:**
  - **An automatic coverage gate, which costs almost nothing:** for every universe ticker, list the price cache's Yahoo `Splits` events since 2014 and refuse if any has no `STOCK_SPLITS` entry within ±5 days.
  - Run the existing split research, `verify_splits_vs_restatements.py`, and the identity/history-break check on the 475 new names.
  - Report fundamentals coverage and the SKIP/FAIL rates **separately** for the new names and the 400/600 names. If they differ a lot, F1 versus F0 reflects data quality, not the universe.

### H3. The faithfulness metric is circular and has no base rate
- **Status:** CONFIRMED (design).
- **Circular:** the universe change and `rank_only` were both derived from these 77 buys (`minervini_check/RESULT.md`, "Why we missed his stocks"). Recall measured on the same buys is **in-sample**. It can describe the change; it can't validate it.
- **No base rate:** recall rises mechanically with candidate volume.
  - F1 adds 475 names, and F2 removes the fundamentals veto (in the synthetic probe, rank_only admitted 135 ticker-days against 62 under strict).
  - A wider ±30-day window around each of his dates catches more by chance as candidate lists grow.
- **Fix:**
  - Publish **candidates per day** next to recall.
  - Compute **lift against a matched null**, either of these:
    - *placebo dates:* his tickers on dates 6 and 12 months away from any disclosed buy;
    - *placebo tickers:* on each of his dates, random in-universe names that passed the trend template that day.

    Report recall divided by placebo recall.
  - Label the metric "descriptive, in-sample". Forward paper trading is the only test of the changes.
  - Measure "listed as a candidate" from `candidates.csv`, not from decision receipts (M4).
  - The denominator: say how many of the 77 remain outside the S&P 1500 even after the change (foreign/20-F such as ASML and SE, IPOs, non-index small caps). The 20-F gap doesn't affect F1/F2 trading, because those names aren't S&P 1500 members, but it caps recall.

---

## MEDIUM

### M1. F0→F1 changes three things at once
- **Status:** CONFIRMED.
- **Where:** `panel.build` ranks `rs_pct` over exactly the panel's tickers (`compute_rs_percentile`), and `regime()` computes breadth over the same set.
- **Scenario:** adding 475 large caps shifts the RS percentile of every existing name, which moves who clears 70/80/90, and changes the regime gate. F1 − F0 then mixes "more tradable names", "a different RS reference set" and "a different regime".
- **Fix:** add **F1a**: rank RS and regime over the S&P 1500, but trade only 400/600. `run_one(..., tradable=...)` already exists for this ("RS still ranks the FULL universe"). Also add **F3 = F0 + rank_only**, which completes a 2×2 of universe × fundamentals. Both are cheap.

### M2. Benchmarks and the index universe are hard-coded to S&P 400+600
- **Status:** CONFIRMED.
- **Where:**
  - `kashif_engine/reports.py:92` builds `ew_index_members` from `sp400 | sp600` only (and names it `EW_sp400_sp600_monthly`);
  - `kashif_engine/experiment2.py:79`: `index_universe()` is also 400+600;
  - `use_bundle` checks `index_universe()` when `panel == "US_idx"`.
- **Scenario:** F1/F2 would be judged against a mid/small-cap equal-weight basket, which lagged large caps in both windows, so it's an easier bar. And a 1500 bundle built on the `US_idx` panel name is refused (fail-safe, but confusing).
- **Fix:**
  - Parametrise the member set.
  - Add an EW current-member S&P 1500 basket (survivorship-matched) and a cap-weighted S&P 1500 proxy (such as ITOT or SPTM, or SPY/MDY/IJR at index weights).
  - Use a new panel name (for example `US_1500`) with its own universe check.

### M3. `rank_only` is mostly "no fundamentals"
- **Status:** CONFIRMED (mechanism). The frequency on real data is unmeasured.
- **Where:** `module.py` sorts with `(-fund_score, -rank_score, -rs_pct, ticker)`. The score only matters on days when there are more candidates than free slots.
- **Scenario:** with typical daily candidate counts (the synthetic probe averaged 0.88 a day and never exceeded 6), the score almost never decides who is bought. F2 is then effectively "fundamentals veto removed", not "fundamentals as ranking".
- **Fix:**
  - Report the **binding frequency**: the days where a lower-score candidate was passed over, or a higher-score one bought, because of the score. Also report the fund-score distribution of bought names.
  - Name the arm truthfully in the report.

### M4. Decision receipts mislabel names admitted by `rank_only`
- **Status:** CONFIRMED (traced).
- **Where:** `module.py`, in `write_receipts`: stages follow the strict pipeline (`SKIPPED_fundamentals` / `REJECTED_fundamentals` whenever the verdict isn't PASS). Its docstring already says so for the switches.
- **Scenario:** if faithfulness or "listed as a candidate" is computed from `decision_receipts.parquet`, F2's admits are counted as rejected, which undercounts F2.
- **Fix:** use `candidates.csv`, which carries `fund_score`, or relabel the stages when `fund_mode != "strict"`.

### M5. The contaminated 2017–2021 run needs its own lock, without weakening experiment 2's
- **Status:** CONFIRMED (traced).
- **Where:** `experiment2.assert_window_allowed` is called from `engine.run` and `prepare` for every US run. With experiment 2's lock finished, it refuses **any** run overlapping 2017–2021.
- **Scenario:** the easy workaround would be editing or relaxing experiment 2's committed lock, or the guard. That would silently reopen the window for everything.
- **Fix:**
  - Add a separate, explicit experiment-3 lock and token path: a new `experiment3.assert_window_allowed`, with its own lock file claimed and pushed before running. Both guards must allow a run. Leave experiment 2's lock untouched.
  - Record in the lock how many arms have now been run on 2017–2021 across experiments 2, 3a and 3F, and report that count with any 2017–2021 number.

### M6. Dual-class share lines
- **Status:** PLAUSIBLE (needs the member list).
- **Scenario:** S&P 500 includes GOOG/GOOGL, FOX/FOXA and NWS/NWSA. Both lines of one company can be candidates on the same day, which opens two positions in one issuer and counts it twice in RS and regime.
  - `GOOG` has no split entry while `GOOGL` does (H2), so the two lines' fundamentals already disagree.
- **Fix:** keep one line per CIK (the more liquid one) in the tradable set, or cap positions at one per issuer.

---

## Code (`rank_only`)

### C1. `fund_score` treats SKIPPED inconsistently
- **Status:** CONFIRMED (probe).
- **Scenario:**
  - `fund_score("PASS", "Q1=PASS, Q2=SKIPPED, Q3=PASS, Q4=SKIPPED")` is **4**.
  - `fund_score("FAIL", "Q1=PASS, Q2=SKIPPED, Q3=PASS, Q4=FAIL")` is **2**. The skipped Q2 costs a point only inside a FAIL.
- **Fix:** for a FAIL verdict whose four questions all parse, use `4 - count(FAIL)`, or equivalently count PASS plus SKIPPED. Keep PASS = 4.

### C2. No data, stale data and a Q1 growth fail all score 0
- **Status:** CONFIRMED.
- **Scenario:**
  - `SKIP/NO_FUNDAMENTALS`, `STALE_*`, `LATEST_EPS_MISSING` and "Q1 FAIL: EPS growth 5% < 20%" all score 0.
  - A company with falling EPS ranks the same as one with no filing data, and below a Q1-pass name that failed all of Q2–Q4 (score 1).
  - This interacts with H2: data errors on the new S&P 500 names become low scores rather than exclusions.
- **Fix:** decide and document the order. For example, rank SKIP (unknown) between a Q1 fail and a pass, or keep SKIP at 0 but report the count of bought SKIP names.

### C3. `soft_single` candidates report `fund_score = 4`
- **Status:** CONFIRMED (probe: 7 soft candidates, all reported 4).
- **Where:** `module.py` in `candidates()`: `int(getattr(r, "fund_score", 4))`. Only `rank_only` computes the column.
- **Scenario:** any cross-arm analysis of `fund_score` from `candidates.csv` is wrong for soft_single, and for every other non-default arm.
- **Fix:** compute `fund_score` in `prepare()` whenever the table is annotated, or emit `None` when it wasn't computed.

### C4. No test covers rank_only's `prepare()` or `candidates()`
- **Status:** CONFIRMED.
- **Where:** `test_fund_score_counts_passed_questions_and_never_vetoes` checks only the scoring function and that the parameter is accepted.
- **Fix:** add a synthetic-world test using the existing fixture:
  - FAIL and SKIP rows are admitted, while TT, RS, volume and regime still gate;
  - candidates are sorted by score first;
  - a strict bundle is refused under rank_only.

  The probe script is a starting point.

---

## Checked and correct

- **Defaults unchanged:** every `rank_only` branch runs only when `fund_mode == "rank_only"`. The differential test against `71ba071` still passes (3 seeds × 5 parameter sets).
- **Only the fundamentals veto is removed:** in the probe, rank_only admitted PASS 62, FAIL 52 and SKIP 21 ticker-days, all still gated by TT, RS, volume, regime and the VCP price-ready check. Scores: PASS 4; FAIL 0–3; SKIP 0.
- **Bundles:** `fund_mode` is a structural switch, so a strict or soft bundle is refused for a rank_only strategy, and the reverse.
- **Sort:** deterministic. Ties fall to `rank_score`, RS, then ticker.
- **Tickers:** `prices.download` maps `BRK.B` to `BRK-B` (`prices.py`, `t.replace(".", "-")`).
- **Compute:** the VCP pre-filter grows by about 2× in the probe (every fundamentals state), so plan the VCP cache time.
