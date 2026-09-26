# Did our system pick the same stocks Mark Minervini bought?

**Question (the owner's):** for stocks Minervini publicly disclosed buying or holding, did our system flag or buy them in the same period?

## The data

- **Minervini's disclosed trades:** 114 rows, 2021–2026, in `minervini_disclosed_trades.csv`, with sources in `SOURCES.md`.
  - The best source is his own list of 21 US Investing Championship 2021 trades, with exact entry dates.
  - The rest come from his X posts, read through search-engine copies (X blocks automated reading and was not bypassed), and from news reports.
  - Nothing credible turned up for 2017–2020.
  - The sample leans toward publicised winners.
- **Filtering:** excluding ETFs and short sales leaves 77 stock buys/holds in 71 tickers.
- **Our side** (`comparison.csv`, via `kashif_engine/scripts/compare_minervini.py`):
  - our filters within ±10 trading days of his date;
  - 14 real runs from experiments 1–3, checked for a candidate or a trade within ±30 days.

## Result

| | Count |
|---|---|
| His stock buys/holds | 77 |
| **Outside our universe** (not current S&P 400/600 members) | **62** |
| Inside our universe | 15 |
| of which passed our Trend Template | 14 |
| of which passed our fundamentals screen | **3** |
| of which showed our breakout signal near his date | 1 |
| of which passed all our filters | 0 |
| of which any of our runs listed as a candidate (±30 days) | 4 (STAA, PAG, OLN, KRYS) |
| of which any of our runs actually bought (±30 days) | 2 (STAA −10%; PAG +12%) |

## Why we missed his stocks

1. **The universe, which is the biggest reason.** 62 of 77 were stocks our system was never allowed to buy:
   - S&P 500 leaders: NVDA, AAPL, META, GOOGL, MU, AXON, APP, LULU, MNST, BKNG;
   - foreign stocks: ASML, SE, BNTX, CAMT, SMFG;
   - small caps and recent IPOs: NNOX, UAVS, RVLV, GBOX, EYPT.

   He trades the whole US market. Our tests used only current S&P 400/600 members.
2. **Our fundamentals screen is far stricter than how he actually trades.** 12 of the 15 in-universe stocks failed it. Examples:
   - OLLI, MATX and PSMT had EPS growth under 20%;
   - STAA and CW had no quarterly acceleration;
   - ANF, URBN and OLN had no annual growth;
   - GWRE was loss-making.

   He bought them anyway. Our code turns his guidelines into hard vetoes; he treats them as flexible.
3. **The trend filter agrees with him:** 14 of 15 passed our Trend Template.
4. **Entry timing differs.** Only 1 of 15 showed our 50-day-high breakout near his date. He often buys at other points in a base, for example pullbacks or early pivots.

## Caveats

- The sample is small and biased toward his publicised trades.
- HOLD rows are snapshots, not entry dates.
- Several dates are month-level only.
- This compares *selection*, not results: his exits and sizing are unknown.

## What it means

Our backtests did not test what Minervini actually does:
- **They used a narrower universe:** mid/small-cap index members only.
- **They used stricter, mechanical rules.**

A faithful test would need an all-US, point-in-time universe (IPOs and delisted stocks included) and softer fundamentals rules. That requires survivorship-free data that free sources don't provide.
