# Review of the review fixes in `821e553`

**Reviewer:** Fork 3 (cloud session).

**Scope:** `ahmedmarzouk343/SEPA` `main` at `821e553`. Focus:
- `kashif_engine/scripts/run_validation2.py` (`preflight`, `claim_lock`, `main`)
- `kashif_engine/experiment2.py` (`assert_window_allowed`)
- `kashif_engine/data/fingerprint.py`
- `module.py` (`to_bundle` / `use_bundle`)
- `run_exp2_dev.py`, because the preflight trusts its output

Code only. Line numbers are at `821e553`. **CONFIRMED** means reproduced by calling the real code (temp git repos, synthetic grids, the committed store) or traced line by line with no ambiguity. **PLAUSIBLE** means the mechanism is real, but I couldn't show it on real inputs.

**Environment and data handling:**
- I have no price cache, panels or bundles.
- One smoke test used the committed 2014+ store over 2017–2021. It collected **only exception types and counts**. No fundamentals verdict for the validation window was printed, saved or read. It ran in my container and wrote no signal cache.
- Nothing on `main` was touched.

---

## Answers to the four questions

1. **Can the window be opened twice, or without the lock?**
   - *Without the lock:* no, for any US strategy run. `run_one`, `engine.run` and `prepare` all require the live nonce, and a bare `True`, a wrong nonce, and a finished or failed lock are all refused (tests pass).
   - *Twice:* not from this clone once the claim is committed, and two concurrent launches are now serialised by `O_EXCL`. But the claim is **never pushed** and the preflight only reads local refs, so a second clone or a copied directory can claim and run again (F4).
   - After an interrupt (Ctrl-C, or anything that isn't an `Exception`), the lock stays claimed and never failed, so its nonce keeps opening the window (F7).
2. **Can the preflight pass with stale data?** The *data* check is sound: price cache, store, splits, breaks and corrections are all SHA-256-compared with the bundle. But:
   - the dev **results** (`dev_grid.csv`, `selection2.json`) are not tied to that bundle or to any commit (F6);
   - a dev grid in which hundreds of runs failed still produces a pick that the preflight re-derives and accepts (F5).
3. **Does `claim_lock`'s commit break with unrelated changes?**
   - **No** for staged, unstaged or untracked unrelated changes (CONFIRMED). The commit contains only the lock, and staged changes stay staged.
   - **Yes** during an in-progress merge (`fatal: cannot do a partial commit during a merge.`), and also with no git identity. Commit signing or hooks would do the same. In each case the preflight had passed, and the uncommitted lock file is left behind (F3).
4. **Crashes after the claim that burn the run.** Yes:
   - **Everything between `claim_lock()` and `try:` is unprotected** (F1, HIGH, CONFIRMED). That is the panel rebuild for about 1,000 tickers, three full-tree SHA-256 passes and the lock rewrite. A crash there leaves a committed claim with no error record and nothing traded, and every later launch is refused.
   - Inside `try:`, the one-shot run is the **first time** the no-bundle `prepare()`, benchmark and `verdict()` path ever runs on this data (F2). The new guard makes it impossible to rehearse that path on the window beforehand.

---

## Findings, ranked

| ID | Sev | Status | One line |
|---|---|---|---|
| F1 | HIGH | CONFIRMED | A crash between `claim_lock()` and `try:` burns the run with no record (panel rebuild, hashing, lock rewrite) |
| F2 | MED | PLAUSIBLE | The validation code path (fresh `prepare`, benchmarks, `verdict`) first runs inside the one-shot; it can't be rehearsed on the window |
| F3 | MED | CONFIRMED | The claim commit fails in a mid-merge tree or with no git identity, after the preflight passed; an uncommitted lock is left behind |
| F4 | MED | CONFIRMED | The claim is never pushed; `git log --all` sees only this clone, so another clone can run again |
| F5 | MED | CONFIRMED | `quick()` keys on mtimes; a mid-grid touch errors every later run, and the partial grid still yields an accepted pick |
| F6 | MED | CONFIRMED | Dev results carry no bundle or commit link, and the bundle's `git_commit` is never compared, so code or bundle drift passes |
| F7 | LOW | CONFIRMED | `except Exception` misses Ctrl-C and SystemExit: no `failed_utc`, and the nonce keeps opening the window |
| F8 | LOW | CONFIRMED | `dirty_code()` still misses untracked root-level shadow modules and assume-unchanged / skip-worktree files |
| F9 | LOW | CONFIRMED | `store_integrity()` checks FIZZ by name only, and a stray file in the store directory gives a false "0 parquet files" |
| F10 | LOW | CONFIRMED | `bad_bar` guard: NaN counts as a split, and duplicate index labels raise an ambiguous-truth error |

---

## HIGH

### F1. A crash between `claim_lock()` and `try:` burns the one-shot run and records nothing
- **Status:** CONFIRMED (real `main()` in a temp git repo).
- **Where:** `run_validation2.py:177-198`. After `nonce = claim_lock()` (`:177`, which commits the lock) comes:
  - `PANEL.build(X.index_universe(), ...)` at `:181`: minutes of work and memory-heavy, over about 1,000 tickers;
  - the `frozen` dict at `:185-194`: three `sha_tree` passes over the whole price cache, store and panel, plus `sha_file` and two git calls;
  - the lock rewrite at `:196-198`.

  All of this runs **before** `try:` at `:200`. Only the code inside `try:` records `failed_utc`.
- **Failing scenario** (`scratchpad/rev/claim_lock_repro.py` case d): `PANEL.build` raises (the repro uses `MemoryError`; an OOM, a disk-full error on `to_parquet` or a read error would do the same).
  - `main()` exits. The lock holds only `['claimed_utc', 'nonce']`. The claim commit `Experiment 2 validation window claimed` is in git. No `VAL2_*` run exists, so nothing was traded.
  - Every later launch is refused by `preflight` (`:113-116`: "lock exists" and "git history already holds a validation lock"). The one-shot run is spent on a panel rebuild, and there's no failure record explaining why.
- **Fix:**
  1. **Do everything that isn't a window result before `claim_lock()`.** That means `PANEL.build`, `index_universe()` and all `frozen` hashes. The panel rebuild is the same call `build_exp2_bundle.py` makes, and it produces features, not results. The preflight already hashes the price cache and store through `fingerprint.content()`, so reuse those values instead of hashing twice.
  2. Wrap **everything after the claim** in `try: ... except BaseException:` that writes and commits `failed_utc` plus the traceback, then re-raises (see F7).
  3. Split "claimed" from "started". Write `started_utc` immediately before the first `run_one`. Let the preflight allow a re-claim (recorded in the lock history) only when the lock has no `started_utc` and no `VAL2_*` run exists. Nothing from the window has been computed at that point, so re-claiming doesn't reopen anything. This needs a line in the pre-registration.

---

## MEDIUM

### F2. The validation code path runs for the first time inside the one-shot run
- **Status:** PLAUSIBLE. The mechanism is certain; whether it actually crashes is unknown.
- **Where:** `run_validation2.py:201-219` → `run_backtest.run_one` with `bundle=None` and `benchmarks=True`.
- **How it differs from the dev grid:**
  - The dev grid used `use_bundle` and `benchmarks=False` (`run_exp2_dev.py:34`).
  - The validation runs a **fresh** `prepare()`: `fundamentals_panel` plus `vcp_table` over 2017–2021, then `reports.compare` with the EW universe, `audit`, `verdict()` (`ew_index_members`, the bootstrap), the `run.json` read and A−B.
  - Since `821e553`, `prepare()` refuses the window without the nonce, so this path **cannot be rehearsed** on 2017–2021 before claiming. Any exception inside `try:` is recorded as `failed_utc`, and the run is spent.
- **Evidence gathered:**
  - The fundamentals half is clean: `F.daily_verdicts` over 2017-01-03..2021-12-31 for all 1,003 current S&P 400/600 names, on the `821e553` store, raised **0** exceptions (`scratchpad/rev/smoke_fund_window.py`; exception counts only).
  - `verdict()`'s keys exist: `compare()` emits `MDY_IJR_5050` and `EW_sp400_sp600_monthly` when `universe` is passed, and `run.json` carries `kill_switch`.
  - I could not exercise VCP, the panel and the engine over 2017–2021 (no price cache here).
- **Two quieter risks:**
  - `_fund_worker` (`signals.py:45-55`) catches per-ticker exceptions and returns one `SKIP` row for `days[0]`. That ticker can then never pass in the window. The error count is only printed (`signals.py:76-78`), never recorded in the lock or the results.
  - A SIGKILL (the OOM killer, a laptop sleeping) records nothing at all.
- **Fix:**
  - Add a `--rehearse` mode that runs `main()`'s exact arm code (`bundle=None`, `benchmarks=True`, audit, `verdict`, bootstrap, A−B, `run.json`) on a dev-window slice such as 2024-01-02..2024-06-28, into a temp output directory, without claiming.
  - Have the preflight require a rehearsal record whose commit and `content()` equal the current ones.
  - Record the fundamentals and VCP `ERROR` counts per arm in the results, and mark an arm INVALID if either is non-zero.
  - Add a `--finalize` mode that recomputes verdicts from finished `VAL2_*` run folders. Then a crash in post-processing doesn't waste completed arms.

### F3. The claim commit fails in a mid-merge tree or without a git identity, after the preflight has passed
- **Status:** CONFIRMED (`claim_lock_repro.py` cases a–c).
- **Where:** `run_validation2.py:161-167`. The preflight (`:108-151`) checks neither condition.
- **Results:**
  - **(a) Unrelated staged, unstaged and untracked changes:** the claim commit contains only `kashif_data/experiment2/VALIDATION_LOCK`, and `a.txt` stays staged. **Fine.** (`git commit -- <path>` has `--only` semantics.)
  - **(b) An unrelated merge in progress (conflict in another file):** `RuntimeError: could not commit the lock claim: fatal: cannot do a partial commit during a merge.` The lock file is left on disk, and the lock is not in git.
  - **(c) No `user.email` / `user.name`:** same `RuntimeError`, and the lock file is left on disk.
  - Also expected to fail the same way: `commit.gpgsign=true` with no agent, a failing pre-commit hook, a stale `.git/index.lock`, or a cherry-pick or revert in progress.
- **Consequence:** nothing ran, but the next launch says `lock exists`, which reads as "the window was claimed". The operator has to know it's safe to delete an *uncommitted* lock.
- **Fix:**
  - In the preflight, refuse if `.git/MERGE_HEAD`, `CHERRY_PICK_HEAD`, `REVERT_HEAD`, `rebase-merge/` or `rebase-apply/` exists, or if `git config user.email` is empty.
  - Commit with `git -c commit.gpgsign=false commit --no-verify -m ... -- LOCK_REL`.
  - If the commit still fails, unlink the lock this process just created with `O_EXCL` (nothing has run) and exit with that message.

### F4. The claim is never pushed, so another clone can claim and run the window again
- **Status:** CONFIRMED (traced).
- **Where:**
  - `claim_lock` (`:154-168`) commits locally, and so do the failure and finish paths (`:224-225, 234-235`). Nothing pushes.
  - The preflight checks `git log --all -- LOCK_REL` (`:115`), which sees only this repository's refs.
- **Failing scenario:** the forks work in more than one local checkout. A second clone, or a directory copy with its own `.git` and a copied `kashif_data/`, has no lock file and no lock commit in its refs. With the same price cache it passes every preflight check and runs the window a second time. The claim commit isn't in `origin` until someone pushes.
- **Fix:**
  - Push the claim commit right after committing it. If the push fails, unclaim (nothing has run) and exit.
  - In the preflight, `git fetch origin` and also check `git log origin/<branch> -- LOCK_REL`, or look for a `validation-claimed` tag on the remote.

### F5. Fingerprints based on modification times turn a mid-grid touch into silently failed runs, and the partial grid still yields an accepted pick
- **Status:** CONFIRMED (`scratchpad/rev/quick_fp_and_errors.py`).
- **Where:**
  - `fingerprint.quick()` hashes the relative path, size and `st_mtime_ns` of every price and store file (`fingerprint.py:25-30, 48-49`). `use_bundle` refuses on any difference (`module.py:206-211`).
  - `run_exp2_dev._run` catches that exception as a run error (`run_exp2_dev.py:45-46`, unchanged), and `objective()` scores it −inf.
  - `main()` still writes `selection2.json` (`run_exp2_dev.py:88-125`).
  - The preflight re-runs `select()` on `dev_grid.csv` (`run_validation2.py:133-142`) but never checks the error count or `len == 1188`.
- **Failing scenario:**
  - A price file whose content is unchanged but whose mtime changed gives a different `quick()` (repro: `same content, touched: False`). Things that do this: `git stash`/`checkout`/`pull` rewriting store parquet files, a benchmark refresh, `cp -p` without `-a`, a sync tool.
  - Every run after that raises `bundle ... was built on other data`.
  - Repro: 540 of 1,188 runs errored (V6–V10 never competed). `select()` still returns a pick from V0–V5, and the preflight's re-derivation equals it, so **the validation would run a pick from half a grid**. `selection2.json` records `errors: 540`, but nothing refuses on it.
- **Fix:**
  - `run_exp2_dev` should refuse to write a pick when any run errored or `len(df) != 1188`. The preflight should refuse the same conditions.
  - Optionally, make `quick()` key on size plus a cheap content hash, such as the first and last 64 KB and the length, instead of the mtime.

### F6. Dev results are not tied to the bundle or to the code that produced them
- **Status:** CONFIRMED (traced).
- **Where:**
  - The preflight compares current data with the bundle's `provenance.content` (`run_validation2.py:144-150`), which is good.
  - But `dev_grid.csv` and `selection2.json` carry no bundle hash and no commit. `run_exp2_dev.py` is unchanged in `821e553`, and it has no `dirty_code()` check.
  - `provenance.git_commit` (`build_exp2_bundle.py:33-34`) is never compared with anything. `use_bundle` stores it (`module.py:205`) but doesn't check it.
- **Failing scenarios:**
  1. The dev grid runs on bundle A. Later the bundle is rebuilt as B (any reason, even identical data with different code). The preflight compares current data with B, passes, and validates a pick chosen on A's signals.
  2. Strategy or signal code (`module.py`, `signals.py`, `entry_timing.py`, ...) is edited after the grid, committed, and the validation runs. `dirty_code()` passes because the tree is clean, and the validation runs code the dev grid never ran.
  3. The dev grid itself runs with an uncommitted edit, and nothing records it.
- **Fix:**
  - `run_exp2_dev` should refuse on a non-empty `dirty_code()`. It should record `git rev-parse HEAD`, the bundle file's SHA-256 and `provenance` in both `selection2.json` and a header or sidecar of `dev_grid.csv`.
  - The preflight should assert:
    - that the recorded bundle SHA equals the current bundle file;
    - that `git diff --quiet <dev_commit> HEAD -- kashif_engine us_fundamentals/*.py <RULE_FILES> <DATA_FILES>` holds. The claim commit only adds the lock, so this stays empty.

---

## LOW

### F7. An interrupt or `SystemExit` after the claim leaves an open window that nothing marks as failed
- **Status:** CONFIRMED (traced).
- **Where:**
  - `run_validation2.py:220` catches `Exception` only. Ctrl-C (`KeyboardInterrupt`) and a `SystemExit` raised deeper in the stack skip the `failed_utc` write.
  - `experiment2.py:62-63` accepts any caller holding the nonce while the lock has neither `finished_utc` nor `failed_utc`. The nonce sits in plain text in the lock and in the committed claim.
- **Scenario:** after Ctrl-C mid-arm, the preflight refuses a rerun, which is correct. But the window stays open indefinitely to any script that reads the nonce from the lock, and the lock never records that the run was aborted.
- **Fix:** `except BaseException`, as in F1. Also make `assert_window_allowed` require that the calling PID matches a `pid` stored in the lock, or give the nonce an expiry.

### F8. `dirty_code()` still misses two classes of change
- **Status:** CONFIRMED (traced; the shadowing itself was reproduced in the first review, L6).
- **Where:** `run_validation2.py:91-105`.
- **Scenarios:**
  - An untracked root-level module such as `?? fundamentals_store.py` shadows `us_fundamentals/fundamentals_store.py`, because the root is first on `sys.path` (`kashif_engine/data/fundamentals.py:34-35`). It matches neither the `code` prefixes nor `RULE_FILES` (and untracked rule files are excluded).
  - Files marked `--assume-unchanged` or `--skip-worktree` never appear in `git status`.
  - Renames and quoted paths are now handled.
- **Fix:** flag any untracked `*.py` at the root, and refuse when `git ls-files -v` shows `h` or `S`.

### F9. `store_integrity()` checks FIZZ by name only, and a stray file in the store directory is a false positive
- **Status:** CONFIRMED (traced; `store_integrity()` returns `[]` on the committed store in 0.9 s).
- **Where:** `fingerprint.py:60-73`.
- **Scenarios:**
  - A future `XBRL_EPS_UNRELIABLE` entry isn't checked.
  - `for part in STORE.iterdir()` also visits plain files, such as `_common_metadata` or `.DS_Store`, and reports "0 parquet files". This fails safe, but it blocks the run.
- **Fix:** iterate `merged_pipeline.XBRL_EPS_UNRELIABLE`, and skip non-directories (or only accept `ticker=*` directories).

### F10. `bad_bar` guard edge cases
- **Status:** CONFIRMED (traced).
- **Where:** `price_corrections.py:62`: `df.loc[d, "Splits"] not in (0, 0.0)`.
- **Scenarios:**
  - A NaN in `Splits` or `Dividends` counts as a corporate action and raises.
  - Duplicate index labels make `df.loc[d, ...]` a Series, which raises `ValueError: truth value ... ambiguous`.
  - Both fail loudly, and at bundle build rather than after the claim: the preflight's `content()` equality means `PANEL.build` sees the same data. So they are not a burn risk.
- **Fix:** compare with `float(df.loc[d, c].sum() or 0) != 0` after `fillna(0)`, and assert `df.index.is_unique`.

---

## Checked and correct

- **`assert_window_allowed` (`experiment2.py:56-64`):** the dev window is always allowed. The window is refused with no lock, with a bare `True`, with a wrong nonce, and after `finished_utc` or `failed_utc`.
  - It is enforced in `run_one` (`run_backtest.py:48`), `Strategy.prepare` (`module.py:130-132`) and `engine.run` (`engine.py:413-415`) for market `US`.
  - The nonce reaches all three from `main()` through `allow_validation2`.
  - `pytest kashif_engine/tests/test_exp2_guards.py`: 5 passed.
- **Two concurrent launches:** both may pass the preflight, but `os.open(..., O_CREAT|O_EXCL)` (`:161`) lets exactly one proceed. The other gets `FileExistsError` before anything is written or run. The M9 race is fixed.
- **Preflight order:** every refusal is collected before anything is written. An invalid `history_breaks.csv` raises inside the preflight (`content()` → `tables()` → `breaks_fingerprint()`), before the claim.
- **The data check is complete for data:** `fingerprint.content()` compares SHA-256 of the price cache and store, plus the split, break and correction tables, with the bundle's build-time record. So the post-claim `PANEL.build` and `P.load` see exactly the bundle's data, and a `bad_bar`/split conflict would already have failed at bundle build.
- **`use_bundle`** refuses a `US_idx` bundle with no `data_fp`, and refuses any `quick()` difference.
- **Pick re-derivation survives the CSV round trip** (pandas 3.0.6): ints, floats and the object-dtype `audit_passed` all compare equal, including when the grid has errored rows.
- **Fundamentals path over the validation window:** 0 of 1,003 names raise with the `821e553` store (exception counts only).
- **`store_integrity()`** on the committed store returns `[]` in 0.9 s.
- **`verdict()` inputs exist:** `compare()` with a universe gives `MDY_IJR_5050` and `EW_sp400_sp600_monthly`, and the engine writes `run.json` → `kill_switch` → `halted_days`/`tripped_reason`.

---

## Appendix: repro for F1 and F3 (temp git repos, real functions)

Run from the repo root.

```python
import json, os, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, ".")
import kashif_engine.scripts.run_validation2 as RV
from kashif_engine import experiment2 as X

def repo():
    d = Path(tempfile.mkdtemp()); g = lambda *a: subprocess.run(["git", *a], cwd=d, capture_output=True, text=True)
    g("init", "-q", "-b", "main"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
    (d / ".gitignore").write_text("kashif_data/\n"); (d / "a.txt").write_text("a\n")
    g("add", "."); g("commit", "-qm", "init")
    RV.ROOT = d; X.OUT = d / "kashif_data" / "experiment2"; X.LOCK = X.OUT / "VALIDATION_LOCK"
    return d, g

# F3: an unrelated merge in progress
d, g = repo()
g("checkout", "-qb", "side"); (d / "a.txt").write_text("side\n"); g("commit", "-qam", "s")
g("checkout", "-q", "main"); (d / "a.txt").write_text("main\n"); g("commit", "-qam", "m"); g("merge", "side")
try: RV.claim_lock()
except Exception as e: print("F3:", str(e).strip()[:90], "| lock left on disk:", X.LOCK.exists())

# F1: crash after the claim, before try:
d, g = repo()
RV.preflight = lambda: ([], {"pick": {"rs_threshold": 70}})
import kashif_engine.panel as PANEL
PANEL.build = lambda *a, **k: (_ for _ in ()).throw(MemoryError("panel rebuild OOM"))
X.index_universe = lambda: ["AAA"]
try: RV.main()
except BaseException as e: print("F1: main raised", type(e).__name__)
print("    lock:", sorted(json.loads(X.LOCK.read_text())),
      "| committed:", g("log", "--oneline", "--", "kashif_data/experiment2/VALIDATION_LOCK").stdout.strip())
# F3: could not commit the lock claim: fatal: cannot do a partial commit during a merge. | lock left on disk: True
# F1: main raised MemoryError
#     lock: ['claimed_utc', 'nonce'] | committed: <sha> Experiment 2 validation window claimed (run_validation2.py)
```
