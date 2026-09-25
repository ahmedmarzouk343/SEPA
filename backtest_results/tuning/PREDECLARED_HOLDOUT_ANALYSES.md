# Holdout analyses, declared before the holdout run

Written after tuning was frozen (`selection.json`) and before any backtest touched 2024-07-01 .. 2026-09-24. `run_holdout.py` stores this file's SHA-256 in `HOLDOUT_LOCK`.

## Runs

Each arm runs exactly once, from a single invocation of `run_holdout.py`.

1. **PRIMARY.** The frozen parameters from `selection.json`:
   - rs_threshold 70
   - breakout_volume 1.6
   - stop_max_pct 0.10
   - max_positions 6
   - catalyst OFF

   The yes/no verdict in the report ("did it beat the benchmark on the holdout") comes from this arm only.
2. **SECONDARY.** Identical, plus catalyst ranking ON:
   - `catalyst_weight` = 0.5, the strategy module's default. It is not tuned and was never changed after any tuning-window catalyst run.
   - Scores come from `catalyst_scores_holdout.parquet`, frozen before this run and hashed in the lock.

## Reported for the primary arm, whatever the numbers turn out to be

- CAGR, max drawdown, Sharpe and Sortino, against these benchmarks:
  - MDY, IJR, their 50/50 blend, and SPY;
  - an equal-weight, monthly-rebalanced basket of current S&P 400 + S&P 600 members.

  The gap between that basket and MDY/IJR is labelled "survivorship + weighting". It is not labelled survivorship alone.
- Trade statistics: win rate (breakeven counts as a loss), average win / average loss, profit factor, trade count, exposure. Positions still open at the end are listed separately.
- **Membership split.** Trades and P&L in the 36 hand-picked "existing" names (which include NVDA, MSFT, AMZN, GOOGL and SMCI) versus sp400/sp600-only names. This is a disclosed selection bias.
- **Sharpe uncertainty.** Lo (2002) standard error of the holdout Sharpe, and whether it is distinguishable from zero at 95%.
- **Multiple-testing note.** 435 tuning backtests were run over a 108-combination grid, and the final pick was made by the pre-declared neighbour-median rule.
- **Walk-forward wording.** All three folds selected a combination different from the final pick. Their positive test results therefore do not validate the final parameters.
- The auditor-vs-ledger result for each arm.
