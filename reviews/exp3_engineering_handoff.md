# Experiment 3 engineering: handoff

**From:** Fork 3. **Branch:** `claude/busy-gauss-irtoua` (not merged, no PR). **Base:** `main` at `71ba071`.

This covers two things: the entry switches, and a design plus skeleton for the daily paper-trading runner. Items marked **UNCERTAIN** are decisions for you to confirm or change.

## 1. Entry switches (commit `4384da8`)

Files: `kashif_engine/strategies/minervini_sepa_v1/module.py`, `kashif_engine/panel.py`, `kashif_engine/tests/test_exp3_switches.py`. `signals.py` is unchanged.

### The switches

| Param | Values (default first) | What it does |
|---|---|---|
| `entry_mode` | `"vcp"` \| `"high50"` | high50: close > the highest close of the previous 50 sessions, with `vol_ratio ≥ breakout_volume`. It replaces **only** the VCP price-ready gate; trend template, RS, fundamentals and regime still apply. The pivot and stop anchor is that prior 50-day high (stop 3% under it, clamped to [4%, `stop_max_pct`]). |
| `rank_by` | `"vcp_quality"` \| `"rs"` | Rank candidates by `rs_pct`. Ties: RS, then ticker, as before. |
| `fund_mode` | `"strict"` \| `"soft_single"` | A fundamentals FAIL whose **only** failing question is Q2 or Q4 stays eligible. Those candidates are sorted after **every** strict pass that day, as an ordering rather than a numeric penalty. Q1 fails (including the loss override), Q3 fails, double Q2+Q4 fails and every SKIP verdict stay vetoes. The logic is in `fund_soft_single()`, which parses `fund_reason` from `fundamentals.screen()`. |
| `early_path` | `False` \| `True` | At `rs_pct ≥ 95`, `tt_1 & tt_2 & tt_7` (close above the 150-, 200- and 50-day lines, all defined) stand in for the full template. Fundamentals, regime, volume and entry timing still apply. |
| `rs_threshold` | 70..100 | A floor of 95 is accepted. The looseness guard (< 70 raises) is unchanged, and values above 100 now raise. |

### Panel and bundles

**Panel.** Two new columns, `high50_prev` and `tt_early`, computed on each ticker's own bars. Every existing column is unchanged; a test compares against `panel.py` at `71ba071`, and a synthetic test checks the new columns don't change when future bars are removed. **Rebuild `US_idx` before any high50 or early_path run.** Without it the strategy raises a clear error naming the missing column.

**Bundles** record the structural switches (`entry_mode`, `fund_mode`, `early_path`), and `use_bundle` refuses a mismatch. `rank_by` needs no extra precomputation. Experiment-2 bundles load as defaults.

### Evidence

- **Defaults reproduce experiment 2 exactly.** `test_defaults_reproduce_experiment2_exactly` loads `module.py` from `71ba071` via `git show`. On 3 random synthetic worlds × 5 parameter sets (defensive, gate, exit, scaling variants), it requires equality of:
  - the VCP pre-filter (hence the same cache key);
  - `vcp`, `tickers_needed` and `feed_start`;
  - every day's `candidates()` and `allocate()`;
  - `on_entry_filled`, `manage()` and state over 40 random bars;
  - `on_trade_closed` and the sizing state;
  - bundle round-trips in both directions.
- **Mutation-checked.** Widening the fundamentals pre-filter, or flipping the RS tie-break direction, makes the test fail.
- **Test results here:** `test_exp3_switches.py` 22 passed; `test_minervini_rules.py` and `test_exp2_guards.py` still pass.
- **Not runnable here:** the price-cache-dependent tests (`test_panel.py` ×3, `test_chaos.py`) fail on untouched `main` in this container too. **Please run the full suite locally, especially `test_panel_rows_do_not_change_when_future_is_removed` after rebuilding the panel.**

### UNCERTAIN

1. **The high50 volume average includes the signal day.** It uses the panel's `vol_ratio`, which is the same convention the VCP breakout uses (`VOLUME_WINDOW = 50`, today included). If you meant the average of the *previous* 50 sessions, that needs a new panel column (`avgvol50_prev`) and a one-line change in `_high50_table`.
2. **high50 with `rank_by="vcp_quality"`.** There is no VCP quality under high50, so ranking falls through to RS, then ticker. It is effectively `rank_by="rs"`. I suggest pairing them explicitly in `arms.json`.
3. **The catalyst weight doesn't scale with `rank_by="rs"`.** `catalyst_weight = 0.5` is added to an RS percentile (0–100), so it only reorders within half an RS point. If arm C uses catalysts with RS ranking, set the weight in RS points (e.g. 5–10) in the pre-registration.
4. **soft_single edge cases.** Q3 SKIPPED counts as not failing, and the other of Q2/Q4 may be SKIPPED. If the `fund_reason` format ever changes, the parser returns False, which is a veto and therefore conservative.
5. **One bundle per structural-switch combination.** A single superset bundle serving several arms is possible (`candidates()` already filters `fund_soft`/`trend_early` rows), but I kept exact matching for safety.
6. **Decision receipts** (non-lite runs only) still label stages by the strict experiment-2 pipeline. `candidates.csv` carries `trend_path`, `fund_soft`, `entry_mode` and `rank_by` for non-default runs.

## 2. Daily forward runner: design and skeleton

Files are all under `paper_trading/exp3/`:
- `DESIGN.md` (391 lines, 13 **UNCERTAIN** marks, 12 open questions in §11);
- `run_day.py` (skeleton);
- `test_run_day.py`;
- `arms.json` (status DRAFT);
- `.gitignore`, which re-includes `*.jsonl`. The repo root ignores `*.jsonl`, which would have silently kept the journal out of git; I checked with `git status --ignored`.

A sub-agent drafted these. I reviewed and checked them:
- 38/38 tests pass offline, and `--help` / `--dry-run` work without network.
- Grepping for broker SDKs, keys and tokens finds nothing, except a test that asserts none exist. The only "IBKR" is the engine's existing cost model.
- The claim that `run_one` refuses end dates ≥ 2024-07-01 without experiment 1's gitignored holdout lock is correct (`run_backtest.py:44-46`), which is why the wrapper calls `prepare`/`engine.run` directly.

### Decisions

- **Replay from Day 1 every session, as you prefer.** backtrader can't save a run midway, so replay is the only way to reuse the engine unchanged. It works only if every past input stays byte-identical, so every store is append-only.
- **Frozen code** runs from a detached worktree at the Day-1 commit.
- **Prices** come from write-once raw partitions per session plus an append-only corporate-actions log, re-based to a fixed **genesis** split basis. Re-basing on every split, as Yahoo does, would change past share counts and break the replay.
- **Fundamentals** use a forward copy of the store, updated one ticker at a time. Each partition is written atomically: a temp directory, then a rename, never `write_to_dataset` appends. There's an append-only store log with accession numbers, and a row is usable from its first-seen session + 1.
- **Journal:** `log/YYYY-MM-DD.jsonl` in canonical JSON, with a SHA-256 chain rooted in `GENESIS.json`. Each day records the code commit and the snapshot hash. A day is published whole or not at all.
- **Divergence alarm:** every run re-derives every published session and compares per-(arm, session) digests.
- **Real code versus stubs:**
  - *Real code:* canonical JSON, the hash chain, journal render/parse and verification, the divergence comparison, snapshot partitions, the genesis-basis price frames, the fundamentals merge and atomic write, and the `arms.json` checks.
  - *Stubs:* the Yahoo and EDGAR fetchers, per-ticker SEC re-extraction, the replay subprocess, and running git.

### Top risks

These are the sub-agent's, and I agree with them.

1. **Yahoo around split ex-dates.** A late split report can look like a −50% gap, and the engine's 75% suspect-move check won't catch a 2-for-1. The design blocks publishing on any unconfirmed split-sized gap in a held, ordered or candidate name, but this is untested against real Yahoo data.
2. **Forward fundamentals arrive later than in the backtests.** The design uses the 10-Q/10-K XBRL date, whereas the backtests used the 8-K press-release date, so forward results are biased against the backtests. Separately, new splits must reach the split table by their effective date; otherwise a 1-for-10 reverse split reads as +900% EPS growth.
3. **Day-1 timeline.** Genesis fetch, freeze and a timed rehearsal must happen before the first close. The engine changes P6 (order log), P7 (drawdown kill) and P8 (delisting exits) in `DESIGN.md` §8 are proposals only and not implemented. P7 and P8 change behaviour, so they must be in the Day-1 commit or be date-gated. Runtime (about 15–25 minutes a day at 60 months) is not measured.

### Open decisions

- Which branch the daily journal is pushed to (`main` or a dedicated `exp3-log`). This is marked UNCERTAIN in `DESIGN.md` §4.5.
- The conflicts with `backtest_results/experiment3/PREREGISTRATION_DRAFT.md` listed in `DESIGN.md` §9: 8-K same-day timing, "past days never re-run", the missing universe file, the kill and delisting rules, and arm C's LLM running outside the runner.
