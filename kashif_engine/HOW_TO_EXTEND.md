# How to extend the Kashif engine

The engine is split into three layers. Each one can change without touching the other two.

| Layer | Lives in | Owns |
|---|---|---|
| Market | `markets.py`, `data/` | currency, settlement (T+N), commission, slippage model, liquidity cap, when fundamentals become usable, price/fundamental loaders |
| Engine | `engine.py`, `ledger.py`, `costs.py`, `auditor.py`, `killswitch.py` | fills, stops, costs, dividends, settlement, double-entry ledger, reconciliation after every bar with fills, kill switch, trade list, equity curve |
| Strategy | `strategies/<strategy_id>/` + a JSON config | every trading decision: candidates, ranking, sizing, stops, exits |

Virtual money only. Nothing in this package connects to a broker.

## Add a strategy (config + module)

1. Write a JSON config with a unique `"strategy_id"` (see `minervini_sepa_v1_strategy_config.json`).
2. Create `strategies/<strategy_id>/module.py` with a class named `Strategy` that subclasses `strategies.base.StrategyModule`, and implement:
   - `prepare(universe, start, end)`: precompute signals. Anything computed here must use only data up to each row's own date. Put a truncation test in `tests/` like `test_panel.py::test_panel_rows_do_not_change_when_future_is_removed`.
   - `tickers_needed()`: the feeds the engine should load.
   - `candidates(ctx, day)`: ranked entry candidates at the close of `day`.
   - `allocate(ctx, candidates)`: `[(candidate, dollars)]`.
   - `on_entry_filled(...)` / `manage(...)`: return actions, at most ONE per position per bar:
     - `("stop", price, label)` replaces the stop;
     - `("exit", reason)` sells at the next open.
   - `on_trade_closed(record)`: update any streak or defensive state.
3. Run it:
   ```python
   from kashif_engine.run_backtest import run_one
   run_one("2022-01-03", "2024-06-28", params={...}, config="my_strategy.json")
   ```
4. Each run gets its own ledger, starting capital and output folder (`kashif_data/runs/<run_id>/`). Two strategies never share cash or positions.

## Add a market (e.g. EGX)

1. Add a `MarketSpec` to `markets.py`. It holds the currency, `settlement_days` (EGX T+2), the fee function, the slippage function, the liquidity cap, and `fundamentals_usable_from` (EGX: the actual disclosure date; the FRA 45-60 day deadline is the fallback). `EGX` is already sketched there.
2. Prices: `data/prices.download(tickers, market="EGX", suffix=".CA")`. The cache is per market (`kashif_data/prices/EGX/`).
3. Fundamentals: a point-in-time store with the same contract as `us_fundamentals/fundamentals_store.py`, i.e. `get_known_fundamentals(ticker, as_of)` gated on the real release date. The EGX store does not exist yet, so a fundamentals-based strategy cannot run on EGX until it does.
4. Build the market's panel: `panel.build(tickers, market="EGX", calendar_ticker=<an index or liquid stock>)`.
5. Do not scrape sources behind bot protection (egx.com.eg's JS challenge). Use legitimate feeds only.

## Rules the engine enforces for every strategy

- **Fill timing.** Decisions happen at the close; entries fill at the next open; a stop that gaps fills at the open, never at the stop price.
- **Split-adjusted feeds, raw costs.** Feeds are split-adjusted, so a split can never trigger a stop. Commission uses raw (as-traded) share counts, and the trade list records both raw and adjusted units.
- **Reconciliation.** The ledger reconciles with the broker after every bar with fills. Any drift trips the kill switch and aborts the run.
- **Long only.** A sell that would leave a short position aborts the run.
- **Suspect bars.** Bars with a >75% move and no split, zero volume, or NaN are never traded on and never drive a strategy decision.
- **Stale feeds.** A held position whose feed stops printing for more than 10 sessions is closed at the first real bar.
- **Kill switch.** New entries halt if `kashif_data/KILL_SWITCH` exists, if the environment variable `KASHIF_KILL_SWITCH=1` is set, or if the legacy `kashif_config.KILL_SWITCH` is set.

## Tests

```bash
python -m pytest -q kashif_engine/tests
```

After any change, re-run the whole suite, not just the part you touched, plus the dataset battery in `us_fundamentals/`: `verify_checkpoints.py`, `test_split_adjustment.py`, `scaled_verification.py`.
