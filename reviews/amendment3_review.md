# Experiment 2, Amendment 3: adversarial code review

**Reviewer:** Fork 3 (cloud session), with two sub-reviewers: items 4–5, and items 5–6 plus runner guards. I re-checked every sub-reviewer finding against the code before including it.

**Scope:** `ahmedmarzouk343/SEPA` `main` at `16f50cb`, covering `ea85ec9` (Amendment 3) and `16f50cb` (history breaks and the restatement split check). This is a code-only review.

**Status labels:**
- **CONFIRMED:** reproduced by calling the real functions, or traced line by line with no ambiguity.
- **PLAUSIBLE:** the mechanism is real, but I could not show it on the real inputs.

**What I could and couldn't run:**
- I had no price cache, panels, bundles or 2014+ store. `kashif_data/` is gitignored and absent here.
- Repros use synthetic frames, temp dirs and git repos, and the **committed 2020+ fundamentals store** (`us_fundamentals/scaled_fundamentals*`). That store is the pre-Amendment-3 one: FIZZ still has its bad EPS and there are no Check 5 notes.
- Line numbers are at `16f50cb`. No file on `main` was modified. This file is the only change, on branch `claude/busy-gauss-irtoua`.

---

## Answers to the six questions

1. **`exit_mode` / `scaling` switches:**
   - Defaults reproduce v1 exactly (**CONFIRMED**). I ran a differential test of HEAD against the pre-amendment module `abfafca`, with the same inputs fed to both: 20,000 random positions × 60 bars plus random trade-close sequences. It found **0 mismatches** in `on_entry_filled`, `manage`, position state, `size_multiplier` and `state_log`. All 23 tests in `test_minervini_rules.py` pass.
   - No state leaks between trades or runs. Position state is a fresh dict per fill (`engine.py:316-318`), and `run_one` builds a new `Strategy` per run (`run_backtest.py:52`); `use_bundle` copies no sizing state.
   - The stop is never lowered in either mode. Breakeven and both trailing paths require `new > stop_price` (`module.py:344, 355, 365`), and the engine changes stops only through those actions (`engine.py:269-276`).
   - Only LOW findings: L12–L14.
2. **Price corrections and `history_breaks.csv`:**
   - The VCP and fundamentals cache keys do change with the corrections, breaks and split tables, and the validation lock hashes the CSV.
   - **The dev bundle is not keyed on any of them (M3).**
   - `bad_bar` can delete a split or dividend (M13); a blank date deletes a whole ticker (M14); the VTOL split marker is assumed, not checked (L10); the CSV is not committed (L7).
3. **`snapshot()` break filter:**
   - It is never applied *before* its date. It applies on the break date itself rather than R+1 (L11).
   - In the daily verdict table it is applied **late, by up to one release cycle (M2)**.
   - An empty `q` is handled. A blank date raises (M14).
   - **Removing history can flip FAIL to PASS (H1).**
4. **Check 5 / `XBRL_EPS_UNRELIABLE`:**
   - It does **not** reject good data at scale: 12 of 25,894 rows on the committed store, 3 of them questionable.
   - But its median uses the ticker's **full future history (M1, lookahead)**.
   - It misses some target cases (L1).
   - A store rebuild *appends* partitions, so the FIZZ drop isn't guaranteed to reach the engine (M4).
   - "Rejection only makes a screen fail" is **false (H1)**.
5. **`verify_splits_vs_restatements.py`:**
   - The ratio convention and the between-splits windows are right.
   - But it checks only one direction of basis error (M5), cannot detect an effective date that is too late (M6), passes `NO_EVIDENCE` silently because it uses one tag per company (M7), and is wired into nothing.
6. **Runners:**
   - The validation window **can** be run twice: the lock is gitignored and deletable, and two launches can race (M9). The permission flag is not tied to the lock, and the window guard is not in the engine (M8).
   - Uncommitted **decision-changing files pass the dirty check**: `kashif_config.py`, `sp_universe.json` and the store (M11), plus the porcelain quirks in L6.
   - **The DSR trial count is right.** `len(df)` is all 1,188 jobs, errored ones included. `deflated_sharpe` matches an independent implementation to 1e-6, units are consistent (daily SR, daily T, `kurt()+3` = raw kurtosis), and the null hurdle is about 1.52 annualised Sharpe at N = 1,188 and 1.05 at N = 50. `var_sr = 1/(T-1)` is the pre-registered, generous choice.

---

## Findings, ranked

| ID | Sev | Status | Item | One line |
|---|---|---|---|---|
| H1 | HIGH | CONFIRMED | 3, 4 | Dropping an EPS (Check 5, FIZZ, NaN) or quarters (break) turns Q2/Q4 into SKIP = pass, so FAIL flips to PASS |
| M1 | MED | CONFIRMED | 4 | Check 5's reference median uses the ticker's future quarters (lookahead baked into the store) |
| M2 | MED | CONFIRMED | 3 | Break dates are not in `event_dates`, so `daily_verdicts` applies a break up to one release cycle late |
| M3 | MED | CONFIRMED | 2, 6 | The dev bundle records no data fingerprint, so a stale bundle is accepted and the "freeze" can't be verified |
| M4 | MED | CONFIRMED | 4 | `scaled_pipeline` appends parquet files, so FIZZ's bad EPS can survive a rebuild and `snapshot` becomes nondeterministic |
| M5 | MED | CONFIRMED | 5 | Release date ≠ EPS basis date; the verifier checks only the "restated but released before split" direction |
| M6 | MED | CONFIRMED | 5 | A median-only verdict cannot catch a first filing already on the new basis, or an effective date that is too late |
| M7 | MED | CONFIRMED | 5 | One XBRL tag per company, and `NO_EVIDENCE` exits 0; the verifier gates nothing |
| M8 | MED | CONFIRMED | 6 | The validation guard lives only in `run_one`; `allow_validation2=True` works even after the lock is finished |
| M9 | MED | CONFIRMED | 6 | Run-once rests on one gitignored file written after a long rebuild: delete or race, and it runs twice |
| M10 | MED | CONFIRMED | 6 | `selection2.json` is trusted without checking where it came from (grid, commit, bundle) |
| M11 | MED | CONFIRMED | 6 | `dirty_code()` misses `kashif_config.py`, `sp_universe.json` and the tracked store |
| M12 | MED | CONFIRMED | 6 | A leftover kill switch or `KASHIF_*` env flag silently voids or changes the one validation run |
| M13 | MED | CONFIRMED | 2 | `bad_bar` drops a split or dividend booked on that bar |
| M14 | MED | CONFIRMED | 2, 3 | A blank date in `history_breaks.csv` silently deletes a ticker (price_cut) or crashes (fundamentals) |
| L1 | LOW | CONFIRMED | 4 | Check 5 blind spots: majority-bad, even split, fewer than 6 points, the 0.05 floor, 2–29× errors |
| L2 | LOW | PLAUSIBLE | 4 | Near-zero NI of preferred issuers can reject good EPS (RBC, OPLN) |
| L3 | LOW | CONFIRMED | 4 | One of FIZZ's three stated reasons is really the then-missing 2:1 split |
| L4 | LOW | CONFIRMED | 5 | Quarters first filed after `eff` are never checked |
| L5 | LOW | CONFIRMED | 5 | Cent rounding gives loud false CONTRADICTED results (MIN_EPS applied to `o` only) |
| L6 | LOW | CONFIRMED | 6 | Porcelain parsing: renames, quoted paths, collapsed untracked dirs, root shadow modules |
| L7 | LOW | CONFIRMED | 2, 6 | `history_breaks.csv` is not committed; a missing file silently means "no breaks" |
| L8 | LOW | CONFIRMED | 6 | Half-returns drop the 2024-06-28 → 2024-07-01 day |
| L9 | LOW | CONFIRMED | 6 | Re-running the dev grid is not recorded, so N stays 1,188 whatever happened |
| L10 | LOW | CONFIRMED / PLAUSIBLE for VTOL | 2 | The correction assumes Yahoo's split marker is on `ex_date`; the test checks only adjusted Close |
| L11 | LOW | CONFIRMED | 3 | A break applies at the close of its own date; releases apply from R+1 |
| L12 | LOW | CONFIRMED | 1 | `exit_mode: run` records the distribution-bar exit-candidate flag, but no report ever reads it |
| L13 | LOW | CONFIRMED | 1 | `scaling: config` still steps and logs `streak_idx` in the receipts |
| L14 | LOW | CONFIRMED | 1 | The "defaults reproduce v1" test checks only the default strings |
| L15 | LOW | PLAUSIBLE | 2, 6 | Signal caches depend on a hand-bumped `CODE_VERSION` and the store's modification time |

**If you only fix a few before the bundle freeze:** H1, M1, M2, M3, M4, M9 and M11. H1 and M1 change which ticker-days pass. M3, M4 and M9 decide whether the freeze and run-once claims are true.

---

## HIGH

### H1. Removing data is not conservative: one missing EPS, or one history break, flips FAIL to PASS
- **Status:** CONFIRMED, found independently by me and by sub-reviewer A.
- **Where:**
  - `fundamentals_screen.py:86-92`: Q2 SKIPPED sets `q2_ok = True`.
  - `fundamentals_screen.py:132-137`: Q4 SKIPPED sets `q4_ok = True`.
  - `kashif_engine/data/fundamentals.py:134-141`: `yoy()` keeps only the newest contiguous run of defined growth values, so a `None` ends the run.
  - `kashif_engine/data/fundamentals.py:155`: an annual sum needs all 4 EPS.
  - `kashif_engine/data/fundamentals.py:86-92`: the new break filter removes the older quarters.
  - **Contradicted text:** `PREREGISTRATION.md:124`, "Rejection only makes a screen fail, so it is conservative", and `merged_pipeline.py:1565`, "screens then fail: conservative".
- **Mechanism:** a Check 5 rejection, the FIZZ drop or any NaN EPS in the middle of the history cuts `eps_yoy_growth_by_quarter` to fewer than 4 values, or `annual_eps_by_year` to fewer than 2. A `fundamentals_break` does the same to everything before it. Q2 (deceleration) and Q4 (annual EPS down) then **cannot fail**. Only a rejection of the latest quarter or its year-ago quarter is conservative, because that gives SKIP.
- **Failing scenarios** (real `screen()` on the committed store; only the one EPS or the one break changed):

  | Ticker, sim date | Change | Before | After |
  |---|---|---|---|
  | AA 2022-06-15 | EPS 2 quarters before latest → NaN | `Q2=FAIL` → FAIL | `Q2=SKIPPED, Q4=SKIPPED` → **PASS** |
  | ADC 2022-09-15 | same | `Q2=FAIL` → FAIL | **PASS** |
  | ADUS 2024-03-15, 2024-06-15 | same | `Q2=FAIL` → FAIL | **PASS** |
  | AA 2024-09-15 | `fundamentals_break` 460 d before latest quarter end | `Q2=FAIL, Q4=FAIL` | **PASS** |
  | ABCB 2024-09-15 | same | `Q4=FAIL` | **PASS** |
  | FOUR 2024-09-01, 2024-12-01 (real, no edits) | fiscal-Q4 EPS NaN every year (2020–23 NaN; Check 5 nulls 2024–25) | n/a | `PASS Q2=SKIPPED, Q4=SKIPPED`: Q2/Q4 can never be evaluated |

- **Scale:**
  - After any break, the ticker gets about 5 quarters in which Q2 and Q4 cannot fail.
  - The committed store already has 107 NaN-EPS rows with at least 4 earlier quarters, across 44 tickers. Amendment 3 adds Check 5 rejections and breaks on top.
  - At dev-window event dates on the committed store, **675 of 5,723 PASS verdicts (11.8%) have Q2 or Q4 SKIPPED even though at least 8 quarters are known.** Some of those come from other gaps (missing quarter rows, irregular quarter spacing) rather than NaN EPS. So this is an upper bound on H1's reach, but it shows the "SKIP counts as pass" path carries real weight.
- **Fix** (either option):
  - In `snapshot()`, flag a run cut short by missing data inside an otherwise available history. That means a NaN or rejected EPS, or a break cut, within the 8 quarters Q2 needs (4 growth values plus their year-ago quarters) or the chain Q4 needs. Then have `screen()` return `SKIP` (`EPS_GAP_IN_WINDOW` / `HISTORY_BREAK_WINDOW`).
  - Or pass a flag so that Q2/Q4 `SKIPPED` counts as not-ok in those cases.
  - Keep "SKIP counts as pass" only for genuinely short listing histories. Correct the Amendment 3 sentence before the bundle is frozen.
- **Repro:** Appendix A.

---

## MEDIUM

### M1. Check 5's reference median is computed over the ticker's future quarters (lookahead)
- **Status:** CONFIRMED (synthetic repro plus trace).
- **Where:** `us_fundamentals/merged_pipeline.py:1593-1604`. `med` is the median implied share count over **all** of the ticker's rows, whatever their release date. A row is rejected when it is more than 30× off that median.
- **Failing scenario:** a ticker with 12 quarters at 5M shares, then a genuine 40× issuance (reverse merger or IPO) to 200M. Appendix C runs the real `_eps_basis_check` on three views of it:

  | History given to Check 5 | Result |
  |---|---|
  | Full history | all 12 early quarters rejected |
  | Only what was known by quarter 12 | 0 rejected |
  | Through quarter 20 | the 9 post-issuance quarters rejected instead |

  - So in the 2014+ rebuild, whether a 2016 EPS survives into the **validation window** is decided by 2022–2026 share counts.
  - Real-data candidate: KNTK 2021-12-31 is rejected at 32×, apparently because the post-2022 merger share basis dominates the median.
  - Combined with H1, a future-driven rejection can also turn a 2017–2021 FAIL into a PASS.
- **Fix** (either option):
  - Use a point-in-time reference: the median over rows released on or before this row's release, with a minimum count.
  - Or reject only unit-error signatures (about 100× or 1000× off, sign-consistent) and record genuine share-basis changes as `history_breaks` rows. Those are already point-in-time after 16f50cb.
- **Measured scale on the committed store:**
  - 12 rejections out of 25,894 rows.
  - 7 pre-IPO quarters (CAVA×3, DUOL, HAYW, HRMY, RSI) and 2 FOUR Q4s are the intended cases.
  - RBC, OPLN and KNTK are questionable (see L2).
  - It is small, but it is a lookahead channel into the validation store.

### M2. A fundamentals break is applied late because it is not an event date
- **Status:** CONFIRMED (real store).
- **Where:** `kashif_engine/data/fundamentals.py:209-226`. `event_dates` holds only release+lag and release+121 days. `daily_verdicts` (`:229-243`) screens only on those dates and carries the verdict forward. The break cut in `snapshot` (`:86-92`) therefore takes effect only at the next event date.
- **Failing scenario:** a break placed between two releases (`break_event_dates2.py`, Appendix D):

  | Ticker | Break date | `daily_verdicts` on that day | `screen()` on that day | Wrong for |
  |---|---|---|---|---|
  | ACLS | 2022-01-21 | PASS | SKIP (NO_FUNDAMENTALS) | 18 days |
  | ABG | 2022-01-25 | PASS | SKIP | 22 days |
  | AAON | 2022-01-31 | FAIL | SKIP | 29 days |

  - The worst case is a full release cycle, about 3 months.
  - `test_history_breaks_cut_prices_and_fundamentals` calls only `snapshot()`, so it cannot catch this.
- **Fix:** add every `FUND_KINDS` break date in `[start, end]` to `event_dates` (and to its docstring's invariant). Add a test comparing `daily_verdicts` with `screen()` on the break date.

### M3. The dev bundle records no fingerprint of its data: a stale bundle is accepted and the "freeze" can't be verified
- **Status:** CONFIRMED (trace plus repro).
- **Where:**
  - `kashif_engine/strategies/minervini_sepa_v1/module.py:182-189` (`to_bundle`) stores the panel name, universe, VCP table, FEED_COLS and `regime_n`, nothing else.
  - `module.py:191-214` (`use_bundle`) checks the panel **name**, that the universe is a subset of the index, and `regime_n`.
  - `run_exp2_dev.py:25,34` always loads the fixed path `bundle_exp2_dev.pkl`.
  - Fills, however, come from a fresh `P.load(t)` per run (`engine.py:439`), which applies whatever `CORRECTIONS` and `history_breaks.csv` contain **now**.
- **Failing scenario:**
  - The universe-wide stock-dividend scan, or one more `bad_bar`/`price_cut` row, lands after `build_exp2_bundle.py dev`. The 1,188 runs then trade current OHLC against pivots, `sma_50`, `avgvol50`, `addv50` and fundamentals verdicts from the old tables, with no error.
  - Nothing records the split, break or store version the selection used, so Amendment 3 §1's "frozen when the development bundle is built" cannot be checked. `run_validation2` hashes the inputs only at validation time.
  - The bundle's date range isn't checked either: a bundle with 2019 days is accepted for the dev window (sub-reviewer repro).
- **Fix:**
  - `to_bundle`: write `split_table_fingerprint()`, `breaks_fingerprint()`, a hash of `CORRECTIONS`, `sha_tree` of the price cache, store and `panels/US_idx`, `git rev-parse HEAD` and the date range.
  - `use_bundle`: recompute these, raise on mismatch, and require the bundle days to cover `[start, end]`.
  - `run_validation2`: refuse unless its frozen hashes equal the dev bundle's.

### M4. A store rebuild appends parquet files, so FIZZ's bad EPS can survive and `snapshot` becomes nondeterministic
- **Status:** CONFIRMED (repro).
- **Where:**
  - `us_fundamentals/scaled_pipeline.py:270-274` calls `pq.write_to_dataset(..., partition_cols=["ticker"])` with no rmtree and no `existing_data_behavior`. pyarrow writes a new `<uuid>-0.parquet` next to the old file.
  - Only `apply_8k_release_dates.py:99` removes the directory. That is a separate manual step, and it crashes earlier if `kashif_data/edgar/events_8k.parquet` is missing.
  - `fundamentals.py:82` uses `drop_duplicates(keep="last")` after a sort that is not stable across files.
- **Failing scenario:** rebuild over an existing store, and the FIZZ partition holds two files (Appendix E):
  - EPS 39.0 and NaN for the same quarter.
  - `get_known_fundamentals` / `snapshot` return **42.0 on some runs and None on others**, depending on file order.
  - The store the engine reads at HEAD still has FIZZ EPS of 39, 42, 33 and 0.21.
  - Nothing in `kashif_engine`, `build_exp2_bundle.py` or `run_validation2.py` asserts that the drop took effect.
- **Fix:**
  - Remove each ticker's partition before writing (or `existing_data_behavior="delete_matching"`).
  - At bundle build and validation, assert: FIZZ EPS all null, no duplicate `(ticker, quarter_end_date)`, one file per partition.

### M5. Release date ≠ EPS basis date, and the verifier checks only one direction
- **Status:** CONFIRMED (the real pipeline functions on synthetic company facts).
- **Where:**
  - The row's `filed` date is the latest of revenue, NI and EPS filing dates (`merged_pipeline.py:740-743`). Three places treat it as the EPS basis date:
    - `adjust_eps_for_splits` (`fundamentals_store.py:163,206`, rule `release < eff <= as_of`)
    - `derive_q4`'s split correction (`merged_pipeline.py:1088`)
    - Check 5 (`:1601`)
  - The verifier flags only `rd < eff` combined with stored == restated (`verify_splits_vs_restatements.py:108`).
- **Failing scenario:** a 2:1 split on 2019-08-15, where the FY2019 10-K re-presents Q1 *revenue* but does not tag quarterly EPS.
  - Q1 2019 is stored `eps 1.1, release 2020-02-20`, so it is never adjusted: 1.1 on 2020-06-30 against a correct 0.55.
  - Derived Q4 2019 EPS comes out 0.47 instead of 0.70.
  - The verifier says `CONFIRMED`, with no wrong-basis rows.
  - In the mirror case, a derived EPS whose shares were re-presented, Q1 and Q2 are double-adjusted, and only Q1 is caught.
- **Fix:**
  - Carry a per-field basis date (`eps_filed`, plus the shares' filing date for derived EPS) and use it in all three places.
  - In the verifier, assert `stored ≈ n·ratio if rd < eff else stored ≈ n`, instead of comparing against the first-filed value.

### M6. A median-only verdict cannot see a first filing already on the new basis, or an effective date that is too late
- **Status:** CONFIRMED (repro).
- **Where:** `verify_splits_vs_restatements.py:86-96,108`.
- **Failing scenario:**
  - A 10-Q filed between the record date and the distribution date may already present post-split EPS, and the table's date may simply be too late. Either way that quarter has o == n.
  - The median over the other quarters still says `CONFIRMED`, and the store check skips the quarter (`abs(o-n) > 0.006`).
  - Repro: verdict `CONFIRMED, median 2.0`, while `adjust_eps_for_splits(0.50, 2019-07-25, 2019-12-31) = 0.25`, a double adjustment.
  - For recurring same-ratio stock dividends (CBSH, TR, SBSI), a date error of up to about a year is undetectable. The docstring's claim of evidence "for the ratio and the date" overstates it.
- **Fix:** give a verdict per quarter.
  - Filed < eff with o/n ≈ 1: "already restated: date too late".
  - Filed ≥ eff with o/n ≈ ratio: "date too early".

### M7. One XBRL tag per company, and `NO_EVIDENCE` exits 0; the verifier gates nothing
- **Status:** CONFIRMED (repro of `main()`).
- **Where:** `verify_splits_vs_restatements.py:62-71` returns facts from the first tag that has any; `:129-136` exits 1 only for CONTRADICTED or wrong-basis rows. No script calls the verifier (`build_exp2_bundle.py`, `run_validation2.py`).
- **Failing scenario:** the company tags `EarningsPerShareBasicAndDiluted` for 2014–2016 and `EarningsPerShareDiluted` from 2017, with a split on 2015-06-01.
  - Only the Diluted facts are read, so the verdict is `NO_EVIDENCE` and the exit code is **0**, while a store row it never looks at is double-adjusted (0.5 → 0.25).
  - `NO_EVIDENCE` also passes silently when `cik_for` returns None, for class-only EPS, for two splits close together, and for re-dated comparative period ends.
- **Fix:**
  - Merge all three tags per quarter, preferring Diluted.
  - Treat `NO_EVIDENCE` as a failure unless the split is on an explicit allow-list with a reason.
  - Run the verifier from `build_exp2_bundle.py` and refuse on failure.

### M8. The validation-window guard sits one layer above the code that trades, and the permission flag isn't tied to the lock
- **Status:** CONFIRMED (repro).
- **Where:**
  - `kashif_engine/engine.py:409-417` has no window check.
  - `run_backtest.py:39,47-50`: `allow_validation2` is a plain bool, and `run_one` never reads `X.LOCK`.
  - `experiment2.py:52-53`: `validation_finished()` is defined but never called.
- **Failing scenarios:**
  - After the validation has finished, `run_one("2017-01-03","2021-12-31", p, allow_validation2=True)` still runs. An analysis script that copies run_validation2's call would do exactly this.
  - `engine.run(...)` from a notebook trades in the window (repro: fills on 2017-01-06).
  - `Strategy.prepare(uni,"2017-01-03","2021-12-31")` plus `to_bundle` materialises the whole 2017–2021 candidate list with no guard.
- **Fix:**
  - Put the overlap check in `engine.run` and `Strategy.prepare` too.
  - Replace the bool with a token: run_validation2 writes a random nonce into the lock and passes it down. Allow the window only while the lock exists without `finished_utc`/`failed_utc` and the nonce matches.

### M9. Run-once rests on one gitignored file, written after a minutes-long rebuild
- **Status:** CONFIRMED (repro driving the real `main()`, with data calls stubbed).
- **Where:** `run_validation2.py:98-99` checks for the lock; `:106` rebuilds the panel (minutes); `:125` writes the lock. `kashif_data/` is gitignored.
- **Failing scenarios:**
  - Two launches both pass the check, and both trade the window. Repro: both PIDs print `STARTED validation arm VAL2_A_pick`.
  - `rm -rf kashif_data` to refresh caches, a fresh clone or a new worktree means no lock, so a second validation runs and nothing in git shows it.
  - The one good property holds: a crash *after* `:125` does block a rerun.
- **Fix:**
  - Create the lock atomically as the very first step: `os.open(LOCK, O_CREAT|O_EXCL)`.
  - Force-add and commit it immediately, and refuse if `git log --all -- kashif_data/experiment2/VALIDATION_LOCK` shows any history.
  - Also refuse if `kashif_data/runs/VAL2_*` exists.

### M10. `selection2.json` is trusted without checking where it came from
- **Status:** CONFIRMED (trace).
- **Where:** `run_validation2.py:107-112` reads it and hashes it. It is written by `run_exp2_dev.py:125` with no commit, bundle hash or dirty state, and it is gitignored.
- **Failing scenario:** a hand-edited pick, or one from a grid re-run on changed code, is run and merely hashed. Off-grid values (RS 75) and any other known strategy parameter (e.g. `use_catalyst`) are accepted.
- **Fix:**
  - In run_validation2, reload `dev_grid.csv`, re-run `select()`, and assert its pick equals `sel["pick"]`.
  - Assert every value is on the grid and every key is a grid or variant key.
  - Have run_exp2_dev record the commit, the bundle hash and an empty `dirty_code()`, and force-commit both files before the validation.

### M11. `dirty_code()` misses tracked files that change decisions
- **Status:** CONFIRMED (repro).
- **Where:** `run_validation2.py:79-80,90`. The rule is a prefix (`kashif_engine/`, `us_fundamentals/`) plus `.py`, with a fixed `RULE_FILES` list.
- **What passes the check when modified:**
  - **`kashif_config.py` (root).** It is imported by `trend_template_test.py:6` and `market_regime_gate.py:8` (`CONFIG_PATH`, which sets every trend-template and regime constant). Its `KILL_SWITCH` flag is read by `kashif_engine/killswitch.py`.
  - **`us_fundamentals/sp_universe.json`.** It defines `index_universe()` and the equal-weight benchmark used in the verdict.
  - **The tracked parquet store.** The lock hashes it, but the locked commit cannot rebuild it.
  - Repro: each is modified in a temp copy and `dirty_code()` returns `[]`.
- **Fix:** refuse on any non-ignored change outside an explicit allow-list (docs), rather than prefix plus `.py`. At minimum add those three paths.

### M12. A leftover kill switch or environment flag silently voids or changes the one validation run
- **Status:** CONFIRMED (repro).
- **Where:**
  - `kashif_engine/killswitch.py:33-41`: the gitignored file `kashif_data/KILL_SWITCH`, re-read every bar; the `KASHIF_KILL_SWITCH` environment variable; and `kashif_config.KILL_SWITCH`.
  - `entry_timing.py:59-61`: `KASHIF_SINGLE_CONTRACTION_ALLOWANCE` changes base validation (`vcp_detection.py:529`). It is not in the VCP cache key (`signals.py:115-117`), the bundle or the lock.
- **Failing scenarios:**
  - A stale KILL_SWITCH file gives 0 fills. The run "completes normally" with `halted_days: 30`, `tripped_reason: None`, and `verdict()` never reads it, so the one run is spent on a meaningless FAIL.
  - An exported allowance flag changes which setups are valid, and the cached VCP table keeps serving that result after the flag is unset.
- **Fix:**
  - Before creating the lock (and in `build_exp2_bundle`), refuse if any kill switch or `KASHIF_*` flag is set.
  - Record `KASHIF_*` in the lock and the bundle, and add the allowance flag to the VCP key.
  - Mark an arm INVALID if `halted_days > 0`.
  - Consider running `prepare()` for both arms *before* writing the lock. It doesn't trade, and it is the slowest, most crash-prone step.

### M13. `bad_bar` deletes any split or dividend booked on that bar
- **Status:** CONFIRMED (synthetic repro, Appendix B).
- **Where:** `kashif_engine/data/price_corrections.py:49-50` drops the whole row, including `Splits` and `Dividends`. `add_raw_columns` (`kashif_engine/data/prices.py:87-99`) then builds `SplitFactor` and the Raw columns from the remaining events.
- **Failing scenario:**
  - A 2:1 split whose ex-date bar is listed as `bad_bar` gives pre-split `RawClose` 30 instead of 60. Per-share commission (`kashif_engine/costs.py:24-33` uses raw shares and raw price) and `RawDividend` are wrong for the whole pre-split history.
  - A dividend on a bad bar goes from 0.25 to 0, so the ledger never credits it.
  - Bad bars cluster on corporate-action days, so this pairing is likely.
- **Fix:** carry the dropped bar's `Splits` (multiplied into the next kept bar) and its `Dividends` forward to the next kept bar, or raise if either is non-zero. Add a test.

### M14. A blank or unparseable date in `history_breaks.csv` silently deletes a ticker, or crashes
- **Status:** CONFIRMED (repro, Appendix B).
- **Where:** `price_corrections.py:37-41` validates only `kind`. `:47-48`: a NaN date becomes NaT, and `df.index >= NaT` is all False.
- **Failing scenario:**
  - A `price_cut`/`both` row with an empty date cell (read with `dtype=str`, so it becomes NaN) returns an **empty frame**: 0 of 12 rows. The ticker vanishes from the panel, RS ranks, regime breadth and the EW benchmark basket with no error.
  - The same row as `fundamentals_break` raises `TypeError: Cannot compare NaT with datetime.date` in `snapshot()` (`fundamentals.py:87-88`).
- **Fix:** validate on load and fail loudly:
  - strip all fields;
  - require a non-empty ticker;
  - parse `date` with `pd.to_datetime(errors="raise")`;
  - reject duplicates.

---

## LOW

### L1. Check 5 misses parts of its target class
- **Status:** CONFIRMED (Appendix C cases A–D).
- **Where:** `merged_pipeline.py:1598, 1602, 1604`.
- **Blind spots:**
  - **More than half of a ticker's quarters are bad:** the median is bad, so the good quarters are rejected and the bad ones kept. This is mostly harmless, because the survivors share one basis.
  - **Exactly half are bad:** the upper median (`len//2`) keeps the wrong side: 3 EPS of 0.06 kept, 3 of 3.00 rejected.
  - **Fewer than 6 points:** nothing is checked.
  - **The `|EPS| ≥ 0.05` floor:** a too-small EPS can only be caught when the true EPS is at least 1.50. A true 1.00 stored as 0.01 is kept, and next year's YoY becomes **+9,900%**, a non-conservative Q1 PASS.
  - **Errors between 2× and 29×:** only a FLAG note, and no consumer reads notes.
- **Fix:**
  - Where a filed weighted-diluted share count exists, compare EPS with NI divided by filed shares.
  - Exempt points below the floor only when NI/shares also rounds to less than 0.05.
  - Use the lower median, or refuse to decide on an even split.

### L2. Near-zero NI can reject good EPS
- **Status:** PLAUSIBLE.
- **Where:** `merged_pipeline.py:1594, 1598`.
- **Scenario:** preferred or NCI issuers without `_ni_common` have a tiny NI against a real EPS, so the implied share count explodes. On the committed CSV: RBC 2022-01-01 (NI −63k, EPS −0.20, about 100×) and OPLN 2022-03-31 (42×).
- **Fix:** skip quarters with |NI| below a small fraction of the ticker's median |NI|, or require `_ni_common`.

### L3. One of FIZZ's three stated reasons is really the then-missing split
- **Status:** CONFIRMED (real `derive_q4`).
- **Where:** `merged_pipeline.py:1567-1570`.
- **Scenario:**
  - "derived Q4 EPS off 2x (0.21 vs 0.42)" comes from FIZZ's 2021-02-19 2:1 split, which was missing from the old table. Without the split `derive_q4` gives 186.8M shares and EPS 0.21; with it, 92.8M and 0.42.
  - The `derived_shares < 2*fy_shares` guard at `:1102` is a coin flip in exactly this case.
  - The cents-as-dollars evidence stands, so the drop itself is fine.
- **Fix:** correct the stated reason, and review the `:1102` guard.

### L4. Quarters first filed after `eff` are never checked
- **Status:** CONFIRMED (repro).
- **Where:** `verify_splits_vs_restatements.py:88-89` skips when `orig.empty`.
- **Scenario:** a post-split EPS of 0.50 stored with release 2019-07-15, before eff 2019-07-20, is not flagged, and query time gives 0.25.
- **Fix:** assert `rd >= eff` for those rows.

### L5. Cent rounding gives loud false CONTRADICTED results
- **Status:** CONFIRMED (repro).
- **Where:** `verify_splits_vs_restatements.py:39-40, 92`. `MIN_EPS` is applied to `o` only.
- **Scenario:** a 3% dividend with EPS 0.21–0.24 gives `CONTRADICTED, median 1.0465`. Repeated false alarms train people to override the check.
- **Fix:** apply the floor to `min(|o|, |n|)`, and scale the tolerance with `0.005/min(|o|,|n|)`.

### L6. `git status` parsing quirks let uncommitted code through
- **Status:** CONFIRMED (repro).
- **Where:** `run_validation2.py:86-93`. Each of these returns `[]`:
  - **Untracked root shadow module:** `?? fundamentals_store.py` is imported instead of `us_fundamentals/fundamentals_store.py`, because the root comes first on `sys.path` (`fundamentals.py:34-35`).
  - **Collapsed untracked package directory:** `?? kashif_engine/data/fundamentals/` has no `.py` suffix, and a package beats a module.
  - **Staged rename into scope:** `R  scratch.py -> kashif_engine/helper.py`, where `line[3:]` is "old -> new".
  - **Quoted paths:** names with spaces or non-ASCII characters.
  - **Git settings:** `status.showUntrackedFiles=no`, and `--assume-unchanged` / `--skip-worktree` files.
- **Checked and fine:** `line[:2].strip()` is always truthy (a harmless no-op), and `A and B or C` parses as intended.
- **Fix:**
  - Use `git status --porcelain=v1 -z --untracked-files=all` and check both paths of a rename.
  - Refuse on `git ls-files -v` `h`/`S` flags.
  - Better still: after import, hash every repo file in `sys.modules` against `git ls-tree`.

### L7. `history_breaks.csv` is not committed at HEAD
- **Status:** CONFIRMED.
- **Where:** `price_corrections.py:28,37`.
- **Scenario:**
  - A missing file silently means "no breaks", so the dev bundle and dev runs proceed without breaks.
  - `run_validation2.py:118` raises FileNotFoundError before the lock, so it fails safe.
  - If the CSV arrives later, dev and validation use different break tables, and nothing records which one dev used (M3).
- **Fix:** commit the file (header-only is fine) and raise if it is missing.

### L8. Half-returns drop one day
- **Status:** CONFIRMED (repro).
- **Where:** `run_exp2_dev.py:38`.
- **Scenario:** half 2 is measured from the 2024-07-01 close, so the 06-28 → 07-01 move belongs to neither half. An equity curve with −10% on 2024-07-01 gives halves `[0.0, 0.0]` and total −10%.
- **Fix:** use `eq.loc["2024-07-01":].iloc[-1] / eq.loc[:"2024-06-28"].iloc[-1] - 1`, and settle the wording before any dev result is read.

### L9. Dev-grid re-runs are not recorded
- **Status:** CONFIRMED (trace).
- **Where:** `run_exp2_dev.py:98`.
- **Scenario:** `dev_grid.csv` is overwritten on each invocation, so N = 1,188 even if the grid ran more than once (after a crash or code change).
- **Fix:** append an invocation log (commit, time, number of runs, bundle hash) and report the number of invocations with the DSR.

### L10. The VTOL correction assumes Yahoo's marker sits on `ex_date`
- **Status:** mechanism CONFIRMED (repro); PLAUSIBLE for VTOL itself (no cache here).
- **Where:** `price_corrections.py:61-62` writes `Splits = filing_ratio` only `if ex in df.index`, and never checks or clears Yahoo's own marker. `tests/test_panel.py:85-94` checks only the adjusted Close jump.
- **Scenario:** Yahoo's 0.5 marker one bar off leaves two markers (0.5 and 1/3), and `RawClose` is 7.5 instead of 15. If the `ex_date` bar is missing, there is no marker at all. The test passes in both cases.
- **Fix:**
  - Assert `df.loc[ex, "Splits"] == yahoo_ratio` before overwriting, and raise if `ex` is missing.
  - In the test, assert `RawClose` continuity across the split (ratio about 3 × the day's move) and the marker count.

### L11. A break applies at the close of its own date, while releases apply from R+1
- **Status:** CONFIRMED.
- **Where:** `fundamentals.py:88` (`<= sim_date`) versus `as_of = knowledge_date(sim_date)` (`:63-67, 72`).
- **Scenario:** a break dated 2025-06-30 already gives `SKIP NO_FUNDAMENTALS` at the 2025-06-30 close. Because removing history can change verdicts (H1), this is one day earlier than the store's own convention.
- **Fix:** compare against `as_of`.

### L12. `exit_mode: run` records the distribution-bar flag, but no report ever reads it
- **Status:** CONFIRMED.
- **Where:** `module.py:337` increments `st["distribution_flags"]`. Trade records copy only `st["tags"]` (`engine.py:353`), which are fixed at entry (`module.py:315`).
- **Scenario:** the pre-registered "exit-candidate flag" never reaches `trades.csv`, so V5/V7/V8/V10 cannot report how often a winner rode through a distribution bar.
- **Fix:** put the count and the first flag date into `st["tags"]`.

### L13. `scaling: config` still steps and logs `streak_idx`
- **Status:** CONFIRMED.
- **Where:** `module.py:373-381` and `:393`. The multiplier ignores it (`:267`).
- **Scenario:** `sizing_state.csv` for V6/V7/V9/V10 shows `streak_idx = 2` (20% size) after 5 losses, while the size stayed at 100%.
- **Fix:** log `size_multiplier()` itself, and skip the streak update when `scaling == "config"`.

### L14. The "defaults reproduce v1" test checks only the default strings
- **Status:** CONFIRMED.
- **Where:** `tests/test_minervini_rules.py:282-288`. Amendment 3 §3 says "this is tested".
- **What I checked instead:** the behaviour itself is correct; the differential test described in answer 1 had 0 mismatches.
- **Fix:** commit a small differential test against a frozen copy of the v1 `manage` and `size_multiplier`, or golden trade lists.

### L15. Signal caches depend on a hand-bumped `CODE_VERSION` and the store's modification time
- **Status:** PLAUSIBLE.
- **Where:** `signals.py:37, 61-65, 115-117`.
- **Scenario:**
  - A later edit to `snapshot()`, `fundamentals_screen.py`, `adjust_eps_for_splits`, entry timing or VCP code that doesn't bump `sig-v2` reuses stale caches.
  - A restore that preserves timestamps (`cp -p`, `rsync -a`) or a deleted partition keeps the old fundamentals key.
  - The dirty-tree check can't catch any of this, because the code *is* committed.
  - For the two commits reviewed here I found no stale key: both changed the key.
- **Fix:**
  - Hash those source files, the config and `KASHIF_*` into both keys, and hash the store's content instead of using its modification time.
  - Point the validation at a fresh signals directory.

---

## Checked and OK

- **Item 1:**
  - Distribution-bar logic in run mode updates `largest_decline` exactly as v1, then falls through.
  - The breakeven bar returns before the trail in both modes.
  - The trail uses the bar's `sma_50` at the close, and the stop takes effect from the next bar, so there is no lookahead.
  - Parameter validation runs before `update`, so bad values raise.
- **Item 2:**
  - The VTOL ×1.5 direction is right: Yahoo's 1-for-2 gives raw×2, ×1.5 gives raw×3, and marker 1/3 gives raw back. The same holds for Volume ÷ 1.5 and Dividends/AdjClose × 1.5.
  - The panel (`panel.py:98`), the VCP worker (`signals.py:87`), engine feeds (`engine.py:439`), the auditor and the benchmarks all go through `P.load`, so they see the same corrected bars.
  - The VCP key includes `fingerprint(t)` (corrections plus per-ticker breaks). The fundamentals key includes the split and break fingerprints.
  - `run_validation2` rebuilds the panel with the same call as `build_exp2_bundle` and hashes it afterwards.
- **Item 3:**
  - A break dated after `sim_date` is ignored (tested).
  - An empty `q` after the cut returns `NO_DATA`.
  - A price cut leaves fewer than 252 bars, so TT and RS are NaN for a year, which is conservative.
- **Item 4:**
  - Check 5's split handling uses the same `_split_factor` as query time.
  - NaN, exact-zero NI and sign mismatches are skipped.
  - A rejected EPS is never refilled.
  - The FIZZ drop covers every FIZZ row within one pipeline run, and the CSV and parquet come from the same rows.
- **Item 5:**
  - Ratio = new shares per old (2:1 = 2, 1-for-4 = 1/4, 5% = 21/20), and o/n is compared in the right direction for splits, reverse splits and dividends.
  - The `filed < eff` / `>= eff` and `rd < eff` conventions match `_split_factor`'s `from < eff <= to`.
  - The `prv < end < eff` window and restatements from `[eff, nxt)` can never compare a product of ratios.
  - The 60–120-day filter keeps 10-K three-month Q4 facts and drops year-to-date durations.
- **Item 6:**
  - The lock is written before any trading, so a crash mid-run blocks a rerun.
  - `overlaps_validation` is inclusive at both ends: 2016-01-04..2017-01-03 and 2021-12-31..2022-06-30 are refused; ..2016-12-30 and 2022-01-03.. are allowed.
  - Requested dates equal traded dates.
  - tune, run_exp2_dev, final_runs and run_holdout all go through `run_one`.
  - Neighbour selection is per variant, one grid step, with failing neighbours at −inf. The even-count median with −inf is right.
  - The constraints hold at their boundaries (60 trades, maxDD −0.25, NaN rejected, `audit_passed is True`).
  - The 57 stale runs are never read.
  - A dead worker raises before `selection2.json` is written.

---

## Appendix: repros

Run each from the repo root with `pandas`, `pyarrow`, `yfinance`, `backtrader` and `scipy` installed. A–B and D use only the committed store or synthetic frames.

### A. H1: one missing EPS, or one break, flips FAIL to PASS (committed store)
```python
import sys; sys.path.insert(0, ".")
from datetime import date
import pandas as pd
from kashif_engine.data import fundamentals as F, price_corrections as PC
from kashif_engine.markets import US

t, d = "AA", date(2022, 6, 15)
PC._breaks = []
base = F.screen(t, d, US); print("as stored :", base["verdict"], base["reason"])
end = pd.Timestamp(base["snapshot"]["latest_quarter_end"])

orig = F.get_known_history
def with_gap(tk, as_of):                       # a Check-5-style rejection 2 quarters back
    h = orig(tk, as_of).copy()
    qe = pd.to_datetime(h["quarter_end_date"])
    h.loc[(qe - (end - pd.Timedelta(days=182))).abs() <= pd.Timedelta(days=20), "eps"] = float("nan")
    return h
F.get_known_history = with_gap
r = F.screen(t, d, US); print("one NaN EPS:", r["verdict"], r["reason"])
F.get_known_history = orig

PC._breaks = [{"ticker": t, "date": str((end - pd.Timedelta(days=460)).date()), "kind": "fundamentals_break"}]
r = F.screen(t, d, US); print("with break:", r["verdict"], r["reason"])
# as stored : FAIL Q1=PASS, Q2=FAIL, Q3=PASS, Q4=PASS [BREAKOUT_YEAR]
# one NaN EPS: PASS Q1=PASS, Q2=SKIPPED, Q3=PASS, Q4=SKIPPED
# with break: PASS Q1=PASS, Q2=SKIPPED, Q3=PASS, Q4=SKIPPED
```

### B. M13, M14, L10: price-correction edges (synthetic)
```python
import sys; sys.path.insert(0, ".")
import numpy as np, pandas as pd
from kashif_engine.data import price_corrections as PC, prices as P
idx = pd.bdate_range("2020-06-01", periods=12)
def frame(split_day=None, ratio=2.0, div_day=None):
    x = np.full(len(idx), 30.0)
    df = pd.DataFrame({"Open": x, "High": x, "Low": x, "Close": x, "AdjClose": x, "Volume": 1e5,
                       "Dividends": 0.0, "Splits": 0.0}, index=idx)
    if split_day is not None: df.loc[split_day, "Splits"] = ratio
    if div_day is not None: df.loc[div_day, "Dividends"] = 0.25
    return df
PC._breaks = [{"ticker": "X", "date": str(idx[6].date()), "kind": "bad_bar"}]
print(P.add_raw_columns(frame(idx[6]))["RawClose"].iloc[0],                     # 60.0
      P.add_raw_columns(PC.apply("X", frame(idx[6])))["RawClose"].iloc[0])      # 30.0  (M13)
PC._breaks = [{"ticker": "X", "date": float("nan"), "kind": "price_cut"}]
print(len(PC.apply("X", frame())))                                              # 0     (M14)
PC._breaks = []
PC.CORRECTIONS[:] = [{"ticker": "X", "ex_date": str(idx[6].date()), "yahoo_ratio": 0.5,
                      "filing_ratio": 1 / 3, "source": ""}]
out = P.add_raw_columns(PC.apply("X", frame(idx[5], 0.5)))                      # Yahoo marker 1 bar early
print(out.loc[out.Splits != 0, "Splits"].tolist(), out["RawClose"].iloc[0])     # [0.5, 0.333] 7.5 (L10)
```

### C. M1, L1: Check 5 on synthetic histories (real `_eps_basis_check`)
```python
import sys, copy; sys.path.insert(0, "us_fundamentals")
from datetime import date, timedelta
import merged_pipeline as MP
def mk(tk, n, shares, override=None, ni=10_000_000):
    rows = []
    for i in range(n):
        qe = date(2014, 3, 31) + timedelta(days=91 * i)
        eps = (override or {}).get(i, round(ni / shares(i), 2))
        rows.append({"ticker": tk, "quarter_end_date": str(qe), "net_income": ni, "_ni_common": None,
                     "eps": eps, "earnings_release_date": str(qe + timedelta(days=35)), "notes": ""})
    return rows
def n_rejected(rows):
    rows, rej = copy.deepcopy(rows), []
    MP._eps_basis_check(rows[0]["ticker"], rows, rej); return len(rej)
full = mk("ZZE", 40, lambda i: 5_000_000 if i < 12 else 200_000_000)   # genuine 40x issuance at q12
print(n_rejected(full), n_rejected(full[:12]), n_rejected(full[:21]))   # 12 0 9   (M1: future decides)
print(n_rejected(mk("ZZD", 12, lambda i: 10_000_000, {3: 0.01})))      # 0: 100x-small EPS below floor kept (L1)
```

### D. M2: break between releases, `daily_verdicts` against `screen()` (committed store)
```python
import sys; sys.path.insert(0, ".")
from datetime import date
import pandas as pd
from kashif_engine.data import fundamentals as F, price_corrections as PC
from kashif_engine.markets import US
start, end = date(2022, 1, 3), date(2026, 9, 24); days = pd.bdate_range(start, end)
for T in ["AAON", "ACLS", "ABG"]:
    PC._breaks = []; ev = F.event_dates(T, start, end, US)
    for a, b in zip(ev, ev[1:]):
        B = pd.Timestamp(a + (b - a) / 2).normalize()
        while B.weekday() >= 5: B += pd.Timedelta(days=1)
        PC._breaks = [{"ticker": T, "date": str(B.date()), "kind": "fundamentals_break"}]
        dv, direct = F.daily_verdicts(T, days, US).loc[B, "fund_verdict"], F.screen(T, B.date(), US)["verdict"]
        if dv != direct:
            print(T, B.date(), "daily_verdicts", dv, "screen", direct, "wrong for", (pd.Timestamp(b) - B).days, "days"); break
```

### E. M4: rebuilding the parquet store appends (synthetic)
```python
import shutil, pandas as pd, pyarrow as pa, pyarrow.parquet as pq
root = "/tmp/pq_append_store"; shutil.rmtree(root, ignore_errors=True)
old = pd.DataFrame({"ticker": ["FIZZ"] * 2, "quarter_end_date": pd.to_datetime(["2021-01-30", "2021-10-30"]),
                    "earnings_release_date": pd.to_datetime(["2021-06-30", "2021-12-09"]), "eps": [39.0, 42.0]})
for d in (old, old.assign(eps=[float("nan")] * 2)):          # the same call as scaled_pipeline.py:270
    pq.write_to_dataset(pa.Table.from_pandas(d, preserve_index=False), root_path=root, partition_cols=["ticker"])
print(pq.read_table(root + "/ticker=FIZZ").to_pandas())      # 4 rows: 39/42 AND NaN for the same quarters
```
