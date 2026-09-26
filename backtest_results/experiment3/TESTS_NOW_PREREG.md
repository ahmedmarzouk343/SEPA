# Experiment 3: historical tests run now (frozen before any run)

**Committed on 2026-09-26, before either test ran.** At the owner's request, the new entry ideas are tested on real historical data today instead of waiting for forward paper trading.

## Arms

Frozen in `kashif_engine/experiment3.py`; nothing may change after this commit.

All three keep the experiment-2 pick's other settings: max stop 10%, 4 positions, defensive mode off, OR regime gate, v1 exits and v1 scaling.

- **B1:** entry on a close above the prior 50-session closing high, with volume at least 1.2× the 50-day average (this replaces the VCP gate). RS floor of 95; candidates ranked by RS.
- **B2:** B1, plus a single Q2 or Q4 fundamentals failure becomes a rank penalty instead of a veto (ranked after every strict pass).
- **B3:** B2, plus an early path: at RS ≥ 95, a close above the 50-, 150- and 200-day lines stands in for the full trend template.

## Test 1: 2024-01-02 .. 2026-09-24 (the owner's request)

- Labelled **in-sample**, because the ideas were derived from 2022-2026 data. It is reported, and it carries no verdict.
- Reference arms: experiment 1's frozen strategy and the experiment-2 pick.

## Test 2 (experiment 3a): 2017-01-03 .. 2021-12-31, run once

- **Why this window is fair:** B1-B3 were committed (7857cac) before experiment 2 opened this window, so it is unseen by these ideas.
- **Lock:** its own lock, `kashif_data/experiment3/EXP3A_LOCK`, is committed and pushed before anything runs. Experiment 2's lock is not touched.
- **Verdict per arm:**
  - **INVALID** if the auditor fails to match the ledger.
  - **KILLED** if the arm's *swept* CAGR is not above the equal-weight member basket's CAGR. Swept means idle cash is held in that basket; in the engine, cash earns nothing.
  - Otherwise **NOT FALSIFIED**. That is never quoted as proof of an edge.
- **Also reported:**
  - raw returns;
  - swept returns into MDY/IJR, compared with MDY/IJR;
  - trades and exposure.
- **Contamination:** the lead has already seen 2017-2021 market conditions and experiment 2's results there. The arms were fixed before that, and nothing in them can change now.
