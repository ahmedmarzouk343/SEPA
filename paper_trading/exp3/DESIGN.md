# Experiment 3: daily forward runner (design, DRAFT)

**Status:** draft for the lead, 2026-09-26. Companion files: `run_day.py` (skeleton), `test_run_day.py`, `arms.json` (DRAFT), `.gitignore`. Nothing here edits the engine; engine changes are proposals only (§8).

**Hard rule: virtual money only.** The runner has no order-routing path. It imports no broker SDK and holds no credential, API key or token, not even as a placeholder. Its only network calls are Yahoo daily bars through `yfinance` (as in `kashif_engine/data/prices.py`) and SEC EDGAR with the repo's existing `SEC_UA` (`kashif_engine/catalyst/edgar.py`, `us_fundamentals/merged_pipeline.py`). Git push uses the operator's existing git/`gh` credential helper, as `kashif_engine/scripts/run_validation2.py` does. The runner stores nothing.

## 0. Decisions at a glance

| Topic | Decision |
|---|---|
| Simulation | Every session D, replay every arm over [Day 1, D] with frozen code. No mutable simulation state (§1). |
| Frozen code | A detached `git worktree` at the Day-1 commit, outside this shared working tree (§1.7). |
| Prices | Genesis history plus one write-once raw partition per session plus an append-only corporate-actions log. Re-based at load time to the **genesis basis** (§5). |
| Fundamentals | A forward copy of the store, updated one ticker at a time. Rows are immutable once written. A new row is usable from its first-seen session + 1 (§6). |
| Journal | `paper_trading/exp3/log/YYYY-MM-DD.jsonl` in canonical JSON, with a SHA-256 chain rooted in `GENESIS.json`. Committed and pushed before the next open (§4). |
| Divergence | Every run re-derives every published session and compares per-(arm, session) digests (§1.6). |
| Partial data | Never written. A session is published complete or not at all (§2.5). |

## 1. Preferred approach: full replay from Day 1 with frozen code

### 1.1 How it works
Each session D, after the close:
1. Append D's bars to the snapshot. Append any corporate actions first seen today. Update the forward fundamentals store.
2. Materialize the engine's inputs from those append-only stores. The inputs are the price cache, the signal panel and the fundamentals store, written into the frozen worktree's gitignored `kashif_data/`.
3. For each enabled arm: `load_strategy(config, params)`, then `strategy.prepare(universe, Day1, D)`, then `engine.run(strategy, US, Day1, D)`, then `auditor.audit(run_dir)`. This is `run_backtest.run_one`'s path (§8).
4. Convert each run directory into journal records for every session in [Day 1, D] (`records_from_run_dir`, real code).
5. Compare sessions before D with the published files (§1.6). Write D's file, then commit and push.

Only append-only inputs and published files carry from one day to the next. A crash at any step leaves nothing to repair: the fix is to run again.

### 1.2 Why it suits this engine
- **No checkpointing.** backtrader cannot checkpoint a running `Cerebro`. The pre-registration's "one engine step per arm" would need a new serializer for broker positions, live stop orders, the Decimal ledger with T+1 pending settlements, the kill switch, and the module's sizing state (`streak_idx`, `defensive`, `recent`, `reentry`, `pilot_wins`). Replay reuses the engine as it is.
- **The engine is causal.** Decisions at the close of t read only bars ≤ t: panel columns are trailing windows (`kashif_engine/panel.py`), VCP windows end on t (`signals._vcp_worker`), and fundamentals gate on release ≤ t−1. So a run ending at D reproduces every decision of a run ending at D−1, **provided that every input for sessions ≤ D−1 is byte-identical**. Every store below is append-only, with effective dates no earlier than first-seen dates, for exactly this reason.
- **End-dependent details checked.** `feed_start()` and `tickers_needed()` grow with D, but they only add feeds that start later. The clock is SPY. `ClockBroker` never fills on a day a feed has no bar. Candidate receipts are copied when recorded, so later order cancellations do not rewrite them.
- **UNCERTAIN:** whether a data feed that first appears late in a run leaves earlier backtrader bars exactly unchanged has not been tested. The Day-0 rehearsal (§2.1) and the daily divergence check both test it.

### 1.3 Honest evaluation

| | Replay from Day 1 (recommended) | Stateful daily step |
|---|---|---|
| State to corrupt | None. Inputs are append-only and outputs are write-once. | Serialized broker/ledger/module state, rewritten daily |
| Engine changes | Small and additive (§8) | A state serializer for backtrader internals, which is hard |
| Crash recovery | Run again (idempotent) | Restore state, and prove it matches the log |
| Self-check | Free: the replay re-derives every published day | Needs a separate replayer anyway |
| A missed day | Covered by the next replay (flagged LATE) | Needs catch-up stepping |
| Runtime | Grows linearly with elapsed sessions (§1.4) | Constant |
| Past inputs | Must be immutable: a late correction changes history and fires the alarm | A late correction only affects the future |
| Frozen-code bug | Replays forever; any fix must be date-gated (§1.5) | A fix applies from the fix date by construction |
| Determinism | Needs a pinned environment and a pristine worktree (§1.7) | Same, and less visible |

The two real costs are runtime growth and the discipline that no past input may ever change. The second is also what the experiment needs, so the replay turns an obligation into a daily check.

### 1.4 Runtime growth
Cumulative compute is O(T²), but each day's wall time is O(T) and is capped by one full backtest per arm. At month 60 (about 1,260 sessions) each arm replays a window about as long as experiment 2's 4.7-year development window.

| Elapsed | Sessions | Panel build (shared) | Signals: fundamentals + VCP (shared per entry mode) | Engine + audit per arm | 6 arms, sequential |
|---|---|---|---|---|---|
| 1 month | ~21 | 1–3 min | < 1 min | seconds | ~5 min |
| 12 months | ~252 | 1–3 min | 1–3 min | ~5–10 s | ~8 min |
| 60 months | ~1,260 | 2–4 min | 3–8 min | ~20–40 s | ~15–25 min |

- **UNCERTAIN:** these are estimates, not measurements. The one engine measurement in the repo (`engine.py`: 54 s before the `ArrayFeed` speed-up, 39 s of which was cell reads) does not state its window. The genesis rehearsal must time every stage.
- The runner logs per-stage seconds in `arm_status` and alarms when a run exceeds 90 minutes.
- Mitigations: build the panel once per day for all arms, run arms in parallel processes, and share signal tables between arms with the same entry mode. Caching signals across days is **not** recommended: a cache is state, and its keys (store mtime, file mtime) are exactly what the materialization rewrites daily.

### 1.5 When the frozen code has a bug
The pre-registration allows a fix only for a crash or an auditor mismatch, from the next day on, with past days never re-run. Under replay that rule is enforced mechanically:
- **Date-gated fix (default).** The fix ships as a new strategy/engine parameter whose default reproduces the old behaviour, like experiment 2's switches. It is active only for sessions ≥ `effective_from`, which is the first unpublished session. The amendment goes into `paper_trading/exp3/AMENDMENTS.jsonl` (append-only: id, effective_from, commit, reason, arms), and the worktree moves to the amendment commit. The daily divergence check over **all** published sessions then proves that the fix did not change the past. Panel fixes follow the same pattern: add a new column and keep the old one, as `panel.py`'s experiment-3 columns already do.
- **Crash at D.** D is not published, so a fix may affect D itself (D becomes `effective_from`). D is published LATE if it misses the deadline.
- **A logic bug that is neither a crash nor an auditor mismatch.** Under the pre-registration it is not fixed. It is recorded as a known issue and stays in the replay for the rest of the experiment. This is the price of pre-registration, not a flaw of replay.
- **A fix that cannot be date-gated** (for example, the loader produced wrong bars for past sessions). End the epoch: published history stands, and the arm is flattened at the next open as an `AMENDMENT_LIQUIDATION`. A new epoch replays from its own start date with capital equal to the published equity. Carrying positions across the break would need engine state injection, which does not exist. **UNCERTAIN:** the lead must decide whether an epoch break counts as the same arm for the statistics.

### 1.6 Divergence alarm
- **What is compared.** Each run builds records for all sessions ≤ D from today's replay, using the same builder that wrote the published files. For each (arm, session) with session < D, it compares a digest: SHA-256 over the sorted canonical lines of the compared record types (candidate, order, fill, dividend, trade_closed, position, equity, event). `arm_status` and the header carry timings and are excluded. Yesterday is mandatory; all earlier sessions are compared too, because it costs nothing.
- **Equality** is exact on canonical text. Floats are fixed at 8 decimals (§4.3), so ulp-level noise cannot trip it except at a rounding boundary.
- **On a mismatch** (`compare_replay`, real code):
  - The arm's records for D are still written, so the chain continues. `arm_status.state` is `DIVERGED`, and a `divergence` record gives the first mismatching session and up to 20 differing lines from each side.
  - The arm is INVALID from that session.
  - The operator must find the cause, usually a changed input: a late split, a store row rewritten, an environment change.
  - Resolution is to restore the input, or to add a date-gated amendment. Prereg §5 stops an arm that stays INVALID for more than 10 sessions.
  - Published files are never edited.
- **Other arms are unaffected**, and the day is still published.

### 1.7 Determinism requirements
1. **Frozen worktree.** `git worktree add --detach <path> <day1_commit>`, placed outside `/home/user/SEPA`, because another engineer edits `kashif_engine/` in this tree. Before each replay: `HEAD` must equal the active epoch's commit, and `git status --porcelain` must be empty apart from the synced forward store path (§6.2).
2. **Pinned environment.** Python 3.11.15, pandas 3.0.6, numpy 2.4.6, pyarrow 25.0.1, backtrader 1.9.78.123 and yfinance 1.7.0 are recorded in every header. A version change is an amendment that the divergence check must pass.
3. **Neutral process environment.** Replays run as subprocesses with `PYTHONHASHSEED=0` and `TZ=UTC`, with fixed worker counts, and with `KASHIF_KILL_SWITCH` unset. The runner asserts that `kashif_data/KILL_SWITCH` is absent and that `kashif_config.KILL_SWITCH` is False: the engine's kill switch reads mutable external state on every bar (`killswitch.py`). The prereg's per-arm kills are rules in code instead (P7).
4. **Clean caches.** Each replay starts with an empty `kashif_data/signals/` and `kashif_data/runs/` in the worktree. This guards against stale cache keys: `signals.fundamentals_panel` keys on a hard-coded store path (P4).
5. **Day-0 proof.** Before Day 1, replay 2026-01-02..2026-09-25 twice from the genesis materialization (identical outputs required). Also compare it with a run on the experiment-2 cache: any differences must be explained by Yahoo revisions.

## 2. Daily schedule and failure policy

### 2.1 Before Day 1 (2026-09-26 to 09-28)
- **Freeze.** Freeze `arms.json` (status `FROZEN`, no TBD), `universe.txt` (S&P 400+600 as of 2026-09-25) and the NYSE calendar table. Record the Day-1 commit.
- **Genesis fetch.** Fetch all tickers and benchmarks from 2019-06-01 to 2026-09-25 (`prices.download` defaults). Every indicator window is at most 400 bars (`HISTORY_BARS`), so this leaves about 1,840 bars before Day 1.
- **Seed the forward store.** Copy the store from the Day-1 commit, add null `first_seen`/`accession` columns to every partition so the schema is uniform, and catch up EDGAR from 2026-09-24.
- **Write `GENESIS.json`**, the chain root, holding the hashes of all of the above.
- **Rehearse** (§1.7 item 5) and time every stage.
- **UNCERTAIN:** the schedule is tight. The first signal is at the close of Monday 2026-09-28.

### 2.2 Session timeline (America/New_York)

| Time | Normal session | Half-day (13:00 close) |
|---|---|---|
| Close | 16:00 | 13:00 |
| Run #1: preflight, Yahoo fetch A | 18:30 | 15:30 |
| Fetch B, 15 min later (settle check) | 18:45 | 15:45 |
| EDGAR poll, store update, arm C ratings window | ~18:50 | ~15:50 |
| Replay, divergence check, write, commit, push | ~19:15 | ~16:15 |
| Retries every 30 min on data failures | until 23:59 | until 23:59 |
| Hard deadline to publish ON_TIME | 08:00 next session | same |
| After the next open (09:30) | the file is LATE | same |

The prereg says "about 18:00 ET". 18:30 is proposed because Yahoo's end-of-day volume keeps settling after the close, and volume decides `vol_ratio` (breakout ≥ 1.2× the 50-day average). **UNCERTAIN:** Yahoo's actual settle time was not measured. The settle check measures it daily.

### 2.3 Steps (each one aborts the run on failure; nothing is written before step 8)
0. **Preflight.** Is D a session in the calendar? Does the chain verify up to the last published file? Is the worktree pristine at the epoch commit, the environment pinned, the kill-switch inputs neutral, and `arms.json` FROZEN with its hash matching `GENESIS.json`?
1. **Fetch.** Yahoo daily bars for the universe plus MDY, IJR and SPY over the last 10 sessions, with `auto_adjust=False, actions=True` exactly as `prices.download` does. Done twice (A and B).
2. **Validate** (`validate_partition`): every expected ticker is accounted for; OHLC is sane; the bar dated D is present for SPY; A and B agree on D's bar for ≥ 99.5% of tickers.
3. **Corporate actions** (§5.4): split/dividend detection from the 10-session re-fetch. An unconfirmed split-like gap in any held, ordered or candidate name ⇒ `NEEDS_REVIEW`: stop and do not publish.
4. **Snapshot.** Write `snapshot/bars/D.parquet` once (`write_partition_once`), plus `snapshot/observations/D.parquet` and `snapshot/actions/D.jsonl`.
5. **EDGAR.** Poll and apply per-ticker store updates (§6), then run the integrity checks.
6. **Replay.** Materialize inputs, then replay the arms (the arm C two-pass is in §7).
7. **Divergence check** (§1.6).
8. **Journal.** Write `log/D.jsonl` atomically (temp file, fsync, rename; never overwritten).
9. **Publish.** `git add -f` the day's files, commit, push, then verify that the remote has the commit.

### 2.4 Holidays, half-days and unscheduled closures
- **Calendar.** A committed NYSE table (`run_day.NYSE_HOLIDAYS_DRAFT` / `NYSE_EARLY_CLOSES_DRAFT`, valid through 2027-12-31) is the source of truth, hashed into `GENESIS.json`. **UNCERTAIN:** the draft table was written from NYSE rules, not copied from nyse.com, and must be checked against it. Past its validity date the runner refuses to run, which forces a timely extension.
- **Not a session:** exit 0 with `NOT_A_SESSION`; nothing is written. The chain links consecutive **sessions**: `prev_session` is the previous NYSE session.
- **Half-days:** same pipeline, run earlier. The engine is daily, so a half-day is an ordinary (low-volume) bar, as in the backtests.
- **Cross-check:** if the calendar says session but no ticker (including SPY) has a bar for D after the deadline, it is treated as an unscheduled closure (for example the NYSE closed on 2025-01-09). The operator appends a dated calendar amendment, and the chain skips D. If the calendar says holiday but SPY has a bar, the run stops with `NEEDS_REVIEW`.

### 2.5 Failed or partial fetch, and late days
- **Refuse, never partial.** If validation fails, nothing is written for D. The run exits non-zero, and cron retries every 30 minutes until the deadline.
- **Complete means** every expected ticker has a row: a bar, or an explicit `status = NO_BAR` with a reason after two fetches agree it is absent (a halt or delisting). Coverage must be ≥ 99% of the tickers that had a bar on D−1. For benchmarks and names held or ordered by any arm, a missing bar blocks until 23:59; after that the name is `NO_BAR` and the engine handles it (orders wait for the feed, as `ClockBroker` does).
- **Missed evening:** the next run first processes D from its own re-fetch window (bars first fetched at D+1, flagged `LATE_FETCH`), then D+1.
- **Late publication:** a file published after the next open is `status = LATE`. Its orders were not witnessed before their fills, and the weekly report counts LATE sessions.

## 3. Point-in-time rules

| Input | Usable for the decision at the close of D when | Enforced by |
|---|---|---|
| Daily bar of session t | t ≤ D | The replay ends at D; no later partition exists |
| Bar values | As first fetched on the evening of t | The loader reads only partitions; re-fetches feed only the actions log |
| Split, ex-date e | Logged with first_seen ≤ e | Genesis-basis loader (§5.3); a late split fires the alarm |
| Dividend, ex-date e | Credited at e, or at first_seen if Yahoo posted it late | `anchor_frame` late-dividend booking |
| Fundamentals row | `earnings_release_date` ≤ D−1 (engine R+1, `fundamentals.knowledge_date`) | Forward rows get `earnings_release_date` = first-seen session (§6.6) |
| Split used for EPS | effective_date ≤ D | `fundamentals_store._split_factor`, fed by forward splits (P3) |
| 8-K/news for arm C | Accepted ≤ 16:00 ET on D (prereg; `edgar.usable_from`) | The ratings file carries `usable_from` |
| Universe | Frozen at genesis | `universe.txt` hash in every header |

**Orders.** Entries and exits decided at the close of D are market orders that fill at the **open of D+1** (as first fetched in D+1's partition). Stops are placed after an entry fill and are live from the next bar; they fill at the stop, or at the open when the bar gaps through it (`engine.py` docstring). Costs are the engine's US costs: IBKR fixed commission plus square-root slippage, T+1 settlement, and the 2%-of-ADDV cap.

## 4. Journal: layout, schema, canonical JSON, hash chain

### 4.1 Layout (all under `paper_trading/exp3/`)

| Path | Written | Content |
|---|---|---|
| `arms.json` | once, then frozen | Arms and switches (§7) |
| `universe.txt`, `GENESIS.json` | at genesis | Frozen universe; chain root with all genesis hashes |
| `log/YYYY-MM-DD.jsonl` | each session, once | The journal (this section) |
| `AMENDMENTS.jsonl` | append-only | Dated code/data amendments (§1.5) |
| `snapshot/genesis/<TICKER>.parquet` + `MANIFEST.json` | at genesis | Yahoo history to 2026-09-25 |
| `snapshot/bars/YYYY-MM-DD.parquet` | each session, once | Raw bars of that session as first fetched |
| `snapshot/observations/YYYY-MM-DD.parquet` | each session, once | The 10-session re-fetch (audit only; never loaded) |
| `snapshot/actions/YYYY-MM-DD.jsonl` | each session, once | Corporate actions first seen that session |
| `fundamentals_store/ticker=X/part-0.parquet` | per-ticker atomic rewrite | Forward store (§6) |
| `store_log/YYYY-MM-DD.jsonl` | each session, once | Every store change, with accession numbers |
| `ratings/YYYY-MM-DD.jsonl` | each session, once | Arm C ratings (external input) |
| `work/` (gitignored) | every run | Materialized caches, run directories |

- **Directory name.** The pre-registration draft names the log directory `log/`. The brief's example was `journal/`. `log/` is used so that no amendment is needed.
- **`.gitignore`.** The root `.gitignore` ignores `*.jsonl`, which would silently drop the journal. `paper_trading/exp3/.gitignore` re-includes it (`!*.jsonl`); verified with `git check-ignore`.

### 4.2 Records (one canonical JSON object per line)

| `record` | Key fields (all carry `arm` and `session` except header/benchmark/footer) |
|---|---|
| `header` | schema `exp3-journal/1`, session, prev_session, seq, prev_file_sha256, code_commit, runner_commit, arms_sha256, universe_sha256, calendar_sha256, amendments_sha256, snapshot {bars_file, bars_content_sha256, chain_sha256, n_expected, n_bars, no_bar[], fetched_utc, late_fetch}, actions_sha256, store_sha256, store_log_sha256, env {versions}, status ON_TIME/LATE/LATE_FETCH, written_utc |
| `arm_status` | state ACTIVE/DIVERGED/INVALID/KILLED/DISABLED, replay {start, end, seconds}, divergence {checked, mismatched} |
| `benchmark` | MDY/IJR close and dividend, blend total-return index |
| `candidate` | rank, ticker, rank_score, rs_pct, volume_ratio, vcp_quality, pivot, catalyst, decision, order_value, reason |
| `order` | for_session, ticker, side, type MARKET_ON_OPEN/STOP, est_value, stop_price (needs P6 for exits and stops) |
| `fill` | ticker, side, shares_adj, price_adj, shares_raw, price_raw, commission, slippage, reason, stop_level |
| `dividend` | ticker, shares_adj, per_share_adj, amount |
| `position` | ticker, shares_adj, cost_adj, entry_session (end of session) |
| `trade_closed` | ticker, entry_session, entry/exit price, shares, net_pnl, return_pct, exit_reason, bars_held |
| `equity` | equity, cash, n_positions, peak_equity, drawdown |
| `event` | event (SUSPECT_BAR_HELD, FEED_DARK_EXIT_QUEUED, KILL_SWITCH, ...), ticker, detail |
| `divergence` | first_session, published_only[], replayed_only[] |
| `footer` | n_lines (lines before the footer), body_sha256 (SHA-256 of those lines' bytes) |

- **Record order** is fixed: header; then per arm in `arms.json` order, the record types in the order above; candidates by rank; the rest by ticker, then canonical text; footer last.
- **Past sessions are fully derivable** from any later replay: candidates come from the receipt copies, positions from cumulative fills, and buy orders from `ORDER_SUBMITTED` receipts. Exit and stop orders need P6.
- **Arm C** additionally records which candidates B1 bought on the same day, from B1's own records.

### 4.3 Canonical JSON (`canonical_json`, real code)
- **Keys.** Objects have sorted keys (code-point order) and no whitespace (`,` and `:` separators). UTF-8 without escaping, LF line endings, and the file ends with `\n`.
- **Floats** are formatted as `f"{x:.8f}"`, then trailing zeros and a trailing dot are stripped; `-0` becomes `0`. Integral floats and ints therefore print alike (`100.0` → `100`). Round-trip is exact for |x| < 6.7e7 (half an ulp < 5e-9), which covers prices, shares and equity; `parse_day_file` rejects any line that is not already canonical.
- **Other types.** NaN and None become `null`, ±inf is an error, and `bool` stays `true`/`false`, never `1`. Numpy scalars are unboxed; dates are ISO `YYYY-MM-DD`; Decimals go through float. Sets are rejected because their order is undefined.

### 4.4 Hash chain
- `file_sha256` is the SHA-256 of the file bytes as committed.
- The header of session D carries `prev_file_sha256` of the previous published session, and `seq` = previous + 1.
- Day 1's `prev_file_sha256` is the SHA-256 of `GENESIS.json` (code commit, arms/universe/calendar hashes, genesis snapshot hash, seeded store hash, environment).
- The footer's `body_sha256` detects truncation or edits before the next file exists.
- `verify_chain(log_dir, genesis)` (real code) checks all of this, plus session order and canonical form. It runs at every preflight, and the weekly audit runs it too.
- The snapshot has its own chain: `chain_sha256 = H(prev_chain | session | content_sha256)`. `content_sha256` hashes canonical rows, not parquet bytes, so a pyarrow upgrade cannot change it.

### 4.5 Commit and push
- **Commands.** `git add -f -- log/D.jsonl snapshot/bars/D.parquet snapshot/observations/D.parquet snapshot/actions/D.jsonl store_log/D.jsonl fundamentals_store/<changed>` (plus `ratings/D.jsonl`), then `git -c commit.gpgsign=false commit -m "exp3 D: journal + snapshot"`, then `git push origin HEAD`. `git_publish_commands()` builds this list; running it is a stub.
- **Verification.** After the push, `git ls-remote origin` must show the commit. The next header records `prev_commit` as the push witness.
- **Where the commits run.** Run from a dedicated clone or branch, not this shared working tree, so that another engineer's uncommitted edits can never be swept into an exp3 commit. **UNCERTAIN:** which branch to push to (main or `exp3-log`) is the lead's call.

## 5. Bar snapshot: append-only "as first fetched"

### 5.1 Storage
- **Genesis.** Yahoo's split-adjusted history as of 2026-09-25, one parquet file per ticker in `prices.COLUMNS`, plus `MANIFEST.json` with the per-ticker content hashes. About 1,030 files of ~50 KB (an estimate).
- **Session partitions.** One parquet file per session, one row per expected ticker: `ticker, session, open, high, low, close, volume, adj_close, dividends, splits, status (OK/NO_BAR), fetched_utc, source`. About 60 KB per session, or ~80 MB over five years. Written once with `os.link` from a fsynced temp file, so an existing partition can never be overwritten, even by a racing run.

### 5.2 What "as first fetched" means
Yahoo's `Close` is split-adjusted as of the fetch time. For the newest bar no later split exists yet, so the bar first fetched on D's evening is **raw**. The loader reads only session partitions and genesis, and never the re-fetch. Later Yahoo revisions are therefore ignored by construction:
- volume corrections;
- dividend re-adjustment of `Adj Close`;
- split re-adjustment of history;
- late bar fixes.

They are still recorded in `observations/` so that the size of the first-fetch versus final-data gap can be reported.

### 5.3 Splits and dividends: the genesis basis
- **The problem.** The engine trades split-adjusted shares, and `add_raw_columns` reconstructs raw values as `adj × SplitFactor`, with the factor equal to the product of split ratios after the bar. If the loader re-based history to the *latest* split (as Yahoo does), every new split would rescale all earlier bars of that ticker. The rescale leaves the ratio signals unchanged, but past sizing does change: `floor(value / close_adj)` produces different share counts, and those change cash and equity. The replay would then diverge from the published record after every split of a previously traded name.
- **The fix: freeze the basis at genesis.** For a forward bar t with raw price p, the loader uses `anchor(t) = p × C(t)`, where C(t) is the product of the ratios (new per old) of splits with genesis < ex-date ≤ t, taken from the actions log.
- **Worked example:** a 2-for-1 split at ex-date e.

  | Session | Raw close | C | Genesis-basis close |
  |---|---|---|---|
  | e−1 | 100 | 1 | 100 |
  | e | 51 | 2 | 102 |

  The series is continuous across the split, and bars before e never change when a split is appended later. That is the invariance the replay needs; `test_anchor_frame_invariance` checks it.
- **Column rules (`anchor_frame`, real code):**
  - OHLC × C, volume ÷ C, dividends × C. The engine credits `anchor_shares × anchor_dividend`, which equals the raw amount exactly.
  - `Splits` is 0 on forward bars. `add_raw_columns` then yields SplitFactor = 1 for every forward bar, and the genesis-part factors are Yahoo's own.
  - `AdjClose` is chained forward as total return, `adj(t) = adj(t−1) × (close + div) / close(t−1)`, so `reports.compare` still sees total-return benchmarks.
- **The cost.** After a post-genesis split, the engine's `raw_shares` for that name equal genesis-basis shares, so the per-share commission is computed on the pre-split share count. That is a fraction of a dollar per fill, disclosed, and fixed exactly by P2. The journal reports the true raw values itself: `shares_raw = shares_adj × C(t)` and `price_raw = price_adj / C(t)`.
- **Names with no post-genesis split** (the large majority) have genesis basis equal to raw basis, so the engine trades whole real shares.

### 5.4 Corporate-actions log and detection
- **Format.** `snapshot/actions/D.jsonl`, one record per action first seen on D: `{kind: split|dividend_late|rename|delist, ticker, ex_date, ratio | per_share_raw, first_seen, evidence, source}`.
- **Split detection** (`detect_splits`, real code). For each date in the re-fetch window, compute `q = refetched_close / (first_fetched_raw / known C over (t, today])`.
  - All q ≈ 1: no new split.
  - q ≈ k before a boundary and ≈ 1 from the boundary on: a split with ratio 1/k (snapped to a simple fraction), ex-date at the boundary.
  - A boundary equal to today is normal: the split is logged the evening of its ex-date.
  - A boundary before today is a `late` split: past sessions were decided on wrong-basis bars. It fires the alarm, and the correction is a divergence event, not a silent fix.
  - Anything else is `UNEXPLAINED`, and the run stops with `NEEDS_REVIEW`.
  - A split needs two confirmations: Yahoo's `Stock Splits` value on the bar, the re-fetch ratio, or an SEC 8-K (items 3.03, 5.03 or 8.01 flagged by the EDGAR poll).
  - An unconfirmed split-like raw gap (open(D)/close(D−1) within 2% of a simple ratio) in a held, ordered or candidate name blocks publication. The engine's `SUSPECT_MOVE` (75%) would not catch a 2-for-1 split, and the stop would fire on a phantom −50% gap.
- **Dividends.** The first-fetched `Dividends` on the ex-date bar is authoritative. A dividend that appears later (re-fetch shows an ex-date inside the window whose first-fetched bar had 0) is logged `dividend_late` and credited on its first-seen session. Entitlement then uses holdings at the close before first_seen, not before the ex-date. The mismatch is rare and each case is logged as a `LATE_DIVIDEND` event.
- **Renames and delistings.** These are logged from EDGAR (CIK-based) and from Yahoo returning no data. A delisted position stays marked at its last close (engine behaviour) until P8 exists; see §9.

### 5.5 Materializing the engine's price cache
Before each replay, the runner writes `anchor_frame(genesis, partitions ≤ D, actions ≤ D)` for every ticker to `<worktree>/kashif_data/prices/US/<T>.parquet`, which is exactly the file format `prices.load` reads. `price_corrections.apply` (history breaks, VTOL) and `add_raw_columns` then run unchanged. The panel (`panel.build(universe, name="EXP3")`), VCP workers (`ProcessPoolExecutor`, which re-import `prices`), the engine and the auditor all read the same files. **The price path needs no engine change for Day 1.** Workers inherit the files, not monkeypatches, which is why file materialization beats in-process loader injection.

### 5.6 Main open risk
**UNCERTAIN, and the main risk: Yahoo's behaviour around split ex-dates.** The design assumes that on the ex-date evening Yahoo either shows `Stock Splits` on the bar or has already re-based the prior bars, so that the split is detected before publication. If Yahoo lags by a day, the first-fetched bar is still raw and correct, but the split is logged late, and a held name can hit a phantom stop. The gap guard (§5.4) blocks publication in exactly that case. It should be tested against every split in `kashif_data/experiment2/splits_*.json` for which re-fetch history is available, before Day 1 if possible. A secondary risk is Yahoo's late dividends (§5.4).

## 6. SEC fundamentals store: incremental per-ticker updates

### 6.1 How it is built today
- **`scaled_pipeline.run_pipeline`** makes one companyfacts call per ticker (`merged_pipeline.fetch_sec_full`, ~1,000 calls). It then runs `derive_q4`, `reconcile_ticker`, the class-EPS supplement, `sanity_check` (sign, 3× revenue, extreme EPS, `_eps_basis_check`, `XBRL_EPS_UNRELIABLE`) and writes the CSV plus parquet. This is the ~20-minute build.
- **`apply_8k_release_dates.main`** moves each row's release date back to the latest 8-K Item 2.02 in [quarter_end + 7 d, SEC date], at most 60 days earlier, with a split guard. It then **deletes the store directory and rewrites it** with `write_to_dataset`.
- **`fingerprint.store_integrity`** requires exactly one parquet file per partition, no duplicate (ticker, quarter_end_date), and null FIZZ EPS. `write_to_dataset` appends a uuid-named file, so writing a partition twice silently leaves two versions of a quarter.

### 6.2 Forward store and EDGAR poll
- **The forward store** lives in `paper_trading/exp3/fundamentals_store/`. It is seeded at genesis from the committed `us_fundamentals/scaled_fundamentals_parquet/` (1,024 partitions, 46,471 rows, last release 2026-09-24). The shared backtest store is never touched.
- **Sync.** Before each replay it is synced (`rsync --delete`) onto `<worktree>/us_fundamentals/scaled_fundamentals_parquet/`, the path that `fundamentals_store.PARQUET_ROOT` resolves to. That is the only path allowed to differ in the worktree's `git status` check; P3 removes this exception.
- **Poll.** `data.sec.gov/submissions/CIK##########.json` for each universe CIK (~1,030 requests at ≤ 10/s, about 3 minutes with `SEC_UA`). This is the same endpoint as `edgar.submissions()`, but uncached: that function caches forever. The watermark is the set of accession numbers already in `store_log/`.
- **Forms of interest:**
  - 10-Q, 10-K, their /A amendments, 10-QT and 10-KT (re-extract);
  - 8-K Item 2.02 (log the release date), items 3.03, 5.03 and 8.01 (possible split, for review), and every 8-K for arm C;
  - NT 10-Q and NT 10-K (log; they explain staleness).
- **UNCERTAIN:** the EDGAR daily index would be one request instead of ~1,030, but its evening publication time is unknown.

### 6.3 Per-ticker update (`merge_ticker_partition`, real code)
1. For a ticker with a new 10-Q/10-K accession, run `scaled_pipeline.process_ticker(ticker, custom, et)` (one companyfacts call), then `sanity_check(rows)`. Both operate per ticker.
   - If companyfacts does not yet contain the accession (`accn`), log `PENDING_FACTS` and retry next session.
   - **UNCERTAIN:** companyfacts' lag after a filing is typically short but not guaranteed.
2. Match extracted quarters to stored ones by `quarter_end_date` within ±5 days (the pipeline's `DATE_TOL`, which absorbs 52/53-week year ends).
3. **New quarter:** append it with
   - `sec_filing_date` = the extracted SEC date;
   - `earnings_release_date` = the **first-seen session D**, which is never earlier than the filing;
   - `release_date_source = FORWARD_FIRST_SEEN`, `first_seen = D`, `accession`.
4. **Existing quarter with changed values** (10-Q/A, restatement, re-derived Q4): keep the stored row and log `REVISION_IGNORED` with the old and new values. This is the store's "as first published" rule, matching the pipeline's as-originally-filed quarters.
5. **Stored quarter absent from the extraction:** keep it and log `ROW_ABSENT_IGNORED`.
6. **Invariants,** checked by `append_only_problems`: every earlier row survives byte-for-byte; every new row has `earnings_release_date == first_seen` and ≥ `sec_filing_date`; the filing date is ≤ D, otherwise the update raises.

### 6.4 Atomic partition write (`write_partition_atomic`, real code)
- **Never append.** The runner never calls `write_to_dataset`, never appends, and never writes inside the store while building a partition.
- **Build aside.** It writes `part-0.parquet` with `pq.write_table` into `fundamentals_store.staging/ticker=X.new-<nonce>/`. Staging lives outside the store root, so dataset discovery can never see a half-written partition. The file is fsynced.
- **Swap in by rename:**
  1. rename the live partition to `.old-<nonce>`;
  2. rename `.new` into place;
  3. delete `.old`.
- **Crash recovery.** `recover_staging()` runs at preflight. It restores `.old` when the live partition is missing and deletes leftover `.new` directories.

### 6.5 Store log and checks
- **Log records.** `store_log/D.jsonl` has one record per ticker touched: `{session, ticker, cik, accessions[], forms[], action (ADD_QUARTER / REVISION_IGNORED / ROW_ABSENT_IGNORED / PENDING_FACTS / SPLIT_FLAG), quarters_added[{quarter_end_date, fiscal_quarter, eps, revenue, net_income, earnings_release_date}], partition_sha256_before/after, code_commit}`.
- **Checks after the batch:**
  - `fingerprint.store_integrity()`, run inside the worktree on the synced copy, plus its mirror `store_problems(root)` on the forward store;
  - `append_only_problems` per touched ticker;
  - schema equal to the seeded schema;
  - partition count unchanged.
- **On failure:** restore the touched partitions from git (`git checkout -- fundamentals_store/ticker=X`), and do not publish D.

### 6.6 Forward versus backtest timing
- **The gap.** The backtest store dates a quarter at its 8-K Item 2.02 press release, often 0–45 days before the 10-Q. The pipeline extracts numbers only from XBRL, which arrives with the 10-Q/10-K, so the forward runner cannot know those numbers at the press-release date. First-seen dating is the honest forward rule. Forward arms therefore react to earnings days to weeks later than their backtests assumed.
- **UNCERTAIN:** this biases forward results against the backtests. Parsing EX-99.1 press releases would close the gap, but that is new, unvalidated extraction code; see the open questions.
- **Splits for EPS.** `adjust_eps_for_splits` applies splits with effective_date ≤ as_of from the hard-coded `STOCK_SPLITS`. A post-genesis split must reach that table (P3) no later than its effective date. Adding it on time changes no past decision; adding it late fires the alarm. Until P3 exists, a 1-for-10 reverse split would read as +900% EPS growth: a false PASS.

## 7. Arms config (`arms.json`, frozen by hash)
- **Contents.** `status` (DRAFT → FROZEN), `day1`, `genesis_session`, `capital` (100,000, as in the backtests), `strategy_config`, `universe_file`, benchmarks, `primary_arm` (B1), `kill_rules` (25% drawdown, 10 sessions INVALID), and `arms[]`.
- **Each arm** has `{id, family, enabled, inherits, params, notes, uncertain[]}`. `resolve_params` walks `inherits`, and arms B and C inherit A's non-entry settings as the prereg requires.
- **Arm A** is experiment 2's pick (`kashif_data/experiment2/selection2.json`: V1, RS 90, volume 1.2×, stop 10%, 4 positions, defensive off, OR gate), with `panel = "EXP3"`.
- **The B-arm switches** use the names from commit `4384da8`, which landed while this was being written: B1 `entry_mode="high50"` + `rs_threshold=95` + `rank_by="rs"`; B2 adds `fund_mode="soft_single"`; B3 adds `early_path=true`. Their defaults reproduce experiment 2.
- **UNCERTAIN (arm C):** under `rank_by="rs"`, `rank_score` is the RS percentile (0–100), so a ±0.5 `catalyst_weight` reorders only candidates within 0.5 RS points of each other. That makes the rating nearly inert. It is flagged in `arms.json` and in open question 12.
- **FROZEN** requires `enabled` settled for every arm and no `TBD` string or non-empty `uncertain` anywhere (`validate_arms(..., require_frozen=True)`). The runner refuses to publish otherwise.
- **The hash** of `arms.json` goes into `GENESIS.json` and every header. After Day 1 the file never changes: amendments go to `AMENDMENTS.jsonl`.
- **Arm C.** The hard rule forbids API keys in the runner, so the runner never calls an LLM. Arm C runs in two passes:
  1. The runner replays B1 and writes `ratings/D.request.json`: B1's candidates plus 8-K texts accepted ≤ 16:00 ET, with the frozen prompt hash and the pinned model id.
  2. A separately operated agent session writes `ratings/D.jsonl`.
  3. The runner compiles `ratings/*.jsonl` into the parquet that `catalyst_path` expects, and replays C.

  A missing or failed rating is NEUTRAL and is logged, as the prereg says.
- **UNCERTAIN:** the news source for arm C is undefined in the repo; only 8-Ks are available.

## 8. Engine reuse and proposed changes (not implemented)

**The thin wrapper** (`run_day.replay_arm`, a stub) runs inside the worktree as a subprocess. It does what `run_one` does: `load_strategy(config, params, US)`, `prepare(universe_frozen, Day1, D)`, `engine.run(..., capital=100000, out_dir=work/runs/<arm>)`, and `audit`. It bypasses `run_one` because `run_one` raises `PermissionError` for any end date ≥ 2024-07-01 unless experiment 1's holdout lock file exists, and that file lives in gitignored `kashif_data/tuning/`, which is absent from a fresh worktree. `engine.run` and `prepare` still call `experiment2.assert_window_allowed`, which passes for dates after 2021.

| # | File | Change | Needed | Changes decisions? |
|---|---|---|---|---|
| P1 | `kashif_engine/data/prices.py` | `CACHE_DIR = Path(os.environ.get("KASHIF_PRICE_CACHE") or ROOT / "kashif_data" / "prices")`, an env switch that `ProcessPoolExecutor` workers inherit. `load()`, `cached_tickers()` and `signals.vcp_table` (which reads `P.CACHE_DIR`) follow automatically. | Optional: the materialization in §5.5 works without it | No |
| P2 | `prices.py` | `add_raw_columns(df, anchor_date=None)`: `after /= prod(Splits with ex-date > anchor)`, with the anchor read from env `KASHIF_PRICE_ANCHOR`; the loader then stores post-genesis splits in `Splits`. | Before the first traded name splits | Commissions of post-split fills only |
| P3 | `us_fundamentals/fundamentals_store.py` | `PARQUET_ROOT` from env `KASHIF_FUNDAMENTALS_STORE`; merge env `KASHIF_EXTRA_SPLITS` (JSON from the actions log) into `STOCK_SPLITS` like `_merge_2014_2021_splits`. | Before the first post-genesis split in the universe | No, if each split is added by its effective date |
| P4 | `strategies/minervini_sepa_v1/signals.py` | The `fundamentals_panel` cache key reads `fundamentals_store.PARQUET_ROOT`, not the hard-coded `us_fundamentals/scaled_fundamentals_parquet`. | With P3 | No |
| P5 | `kashif_engine/data/fingerprint.py` | `STORE`/`PRICES` derived from P1/P3; `store_integrity(root=STORE)`. | With P1/P3 | No |
| P6 | `kashif_engine/engine.py` | An order log appended at every buy, exit, stop placement and cancel `{date, ticker, side, exectype, size, stop_price, reason, ref}` → `orders.csv`, plus `pending_at_end` in `run.json`. | Day 1, so the journal can publish exit and stop orders | No (logging only) |
| P7 | `engine.py` | Param `max_drawdown_kill`: at a close where equity < (1 − 0.25) × peak, exit everything at the next open and take no further entries. Deterministic, so it replays. | Prereg §5 kill | New behaviour, default off |
| P8 | `engine.py` | Param `forced_exits {ticker: session}`: book a delisted position's sale at its last close. | Prereg delisting rule | New behaviour, default off |
| P9 | `kashif_engine/run_backtest.py` | `run_one(..., forward=True)`, skipping the experiment-1 holdout lock, so the wrapper can call `run_one` itself. | Optional | No |

- **P1, P4, P5 and P6** are decision-neutral. They can land after Day 1 as amendments, because the divergence check proves them.
- **P7 and P8** are new rules. They must be in the Day-1 commit, or be date-gated amendments.
- **None is implemented here:** `kashif_engine/` is being edited concurrently by another engineer.

## 9. Conflicts with the pre-registration draft (resolve before Day 1)
1. **Stepping versus replay.** "Run one engine step per arm" and "past days are never re-run" become: replay daily, never change published files, and date-gate fixes (§1.5).
2. **8-K timing.** "An 8-K before 16:00 ET is usable the same day" does not match the engine, which uses R+1 for every fundamentals row (the store has no time of day). This design follows the engine; the 16:00 rule applies only to arm C's ratings.
3. **Missing universe file.** The universe file `kashif_data/experiment2/index_universe.txt` does not exist in this checkout. It is replaced by `paper_trading/exp3/universe.txt`, frozen at genesis.
4. **Delisting rule.** "A delisted position is closed at its last available price" needs P8. Today the engine keeps the position marked at its last close and holds the slot.
5. **Kill rule.** "Flattened at the next open and stopped" needs P7. The engine's `KillSwitch` blocks only entries, and it reads mutable external state.
6. **Arm A.** The experiment-2 report says to drop arm A (it failed validation). The B arms still need A's non-entry settings as their base.
7. **Arm C's LLM** must not run inside the runner (no keys). It runs as the external ratings step in §7.

## 10. Skeleton status (`run_day.py`)
- **Real and tested** (`python3 -m pytest -q paper_trading/exp3`):
  - canonical JSON; record builders; day-file render and parse; hash-chain verification; divergence comparison;
  - run-directory-to-records conversion;
  - snapshot validation and write-once partitions; the snapshot chain hash;
  - genesis-basis frames; split detection;
  - append-only fundamentals merge, atomic partition write and crash recovery, store checks;
  - NYSE session helpers (draft table); `arms.json` validation and inheritance; the git command plan; `--dry-run` and `--help`.
- **Stubs** (raise `NotImplementedError` with a TODO): the Yahoo fetch, the EDGAR poll, per-ticker SEC re-extraction, the genesis fetch, the replay subprocess, and executing the git commands.
- **`--dry-run`** is offline. It prints the plan and the arms problems. With `--demo-dir`, it writes a synthetic two-session chain and verifies it.
- **Live mode** refuses to run while `arms.json` is DRAFT, and otherwise stops at the first stub.

## 11. Open questions for the lead
1. **Day 1.** Can genesis, the freeze and the rehearsal (§2.1) finish before the 2026-09-28 close? If not, does Day 1 move?
2. **Journal directory.** `log/` (prereg) or `journal/` (brief)?
3. **Push target.** Main or a dedicated `exp3-log` branch, pushed from a dedicated clone?
4. **Genesis size.** Commit the genesis snapshot (~50 MB, estimated) to git for outside witnessing, or keep it out of git with only its hash?
5. **Fundamentals timing.** Accept first-seen dating, which is later than the backtests' 8-K dates (§6.6), or fund an EX-99.1 extractor with its own audit?
6. **Engine changes.** Which of P2, P3, P6, P7 and P8 must be in the Day-1 commit? This needs coordinating with the engineer editing `kashif_engine/`.
7. **Arm A.** Drop it (as the experiment-2 report says) or keep it as the reference arm? Also, the final names of the B-arm switches.
8. **Divergence policy.** Publish per arm with a flag (proposed), or block the whole day?
9. **Arm C.** Who operates the ratings session, which model id is pinned, and is there a news source beyond 8-Ks?
10. **Epoch breaks.** Does an epoch break (§1.5) keep the same arm for the statistics, or start a new segment?
11. **Run time.** Is 18:30 ET acceptable as the run time instead of the prereg's "about 18:00"?
12. **Arm C scale.** Should C keep `catalyst_weight=0.5` on the RS scale (nearly inert, §7), or should the weight or the ranking be redefined before Day 1?
