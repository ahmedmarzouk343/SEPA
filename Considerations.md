# Kashif — Architectural Considerations

## 1. Core Engine & Infrastructure

To avoid "reinventing the wheel" and reduce catastrophic software bugs, an architectural decision was made to rely on the **backtrader** library as the underlying infrastructure to run Feature 4 (Risk Management) and the Backtest Engine, while maintaining our custom rules (Custom Strategy & Sizer).

**Order Execution**: Relying on built-in Bracket Orders to execute buy orders simultaneously linked with a Stop-Loss and Trailing Stop.

**Look-Ahead Bias Prevention**: Utilizing the backtrader environment, which strictly passes data day-by-day (via the `next` function) to make it programmatically impossible for the system to peek at tomorrow's data.

**Slippage & Commissions Simulation**: Using the Broker Simulator to automatically deduct commissions and simulate price slippage for realistic testing.

**Position Sizing & Ledger**: Utilizing the Sizer module to program our custom Minervini rules (e.g., reducing position size 100% → 40% → 20% during losing streaks or activating Defensive Mode).

---

## 2. Tech Stack & Auxiliary Libraries

A specific set of professional libraries has been selected to automate and accelerate the building of the remaining phases:

**Data Fetching**: Relying on `yfinance` for price and volume data (sufficient for the Paper Trading phase).

**Data Caching**: Using the Parquet format via `pyarrow` or `DuckDB` for lightning-fast reads, replacing slow pickle files.

**Technical Indicators**: Using `pandas-ta` to calculate Simple Moving Averages (SMA) and volatility indicators like ATR with a single line of code.

**VCP Pattern Detection**: Using `scipy.signal.find_peaks` to identify peaks and troughs and measure price contractions with mathematical precision.

**Scraping & Disclosure Retrieval**: Using Playwright with `playwright-stealth` to bypass anti-bot protections (F5/TSPD JS challenge) on the EGX website. For reading disclosures, `pdfplumber` will be used for standard PDFs, and `pytesseract` (with the `ara` Arabic engine) for scanned images.

> ⚠️ **CONFLICT WITH STANDING PROJECT RULE**: `STATUS-technical-thread.md` Section 7 has an explicit rule against bypassing active bot-detection (EGX's JS challenge wall). Do NOT implement Playwright scraping until this is explicitly resolved. Leave as a TODO comment only.

**Catalyst Check (News Analysis)**: Using LangChain to connect the system with Google AI Studio APIs (fast and free) to instantly read, analyze, and score news based on our strict rubric.

> ⚠️ **DECISION REQUIRED**: The project currently uses Claude Haiku 4.5 (with prompt caching and Batch API) for catalyst scoring. Switching to LangChain + Google AI Studio changes cost, latency, and rubric behavior. Do NOT switch providers silently — flag as a TODO and await an explicit decision.

**Reporting**: Using `QuantStats` to generate professional HTML performance reports detailing Win Rate, Max Drawdown, and equity curves without writing custom math.

**Strategy Optimization**: Using `Optuna` in the future to run thousands of backtests to find the precise parameters (e.g., RS percentiles) that perform best specifically in the Egyptian market.

---

## 3. Testing Architecture & Transparency

To ensure the system works in a realistic environment and to eliminate the "Black Box" effect:

**Chaos Engineering**: Creating a `data_mutator.py` script to intentionally corrupt clean data (deleting trading weeks, zeroing out volume, multiplying closing prices by 10) to ensure the system "Fails Gracefully" rather than buying on fake data or crashing.

**The Independent Auditor**: An isolated script that only reads buy/sell orders and independently calculates P&L. If its results differ from the system's ledger, it flags a cheating or accounting vulnerability.

**Decision Receipts**: The system will generate a detailed "receipt" for every evaluated stock, explaining exactly why it passed or failed at each stage (e.g., "Passed Stage 1 & 2, Failed Stage 3 because volume on breakout was 0.8x average, required 1.4x").

---

## 4. Egyptian Market (EGX) Edge Cases & Guards

Strict engineering constraints designed to protect the virtual portfolio from specific EGX traps:

**Corporate Action Guard**: Prevents the system from triggering a false stop-loss and recording a fake massive loss due to a stock split or a dividend drop.

**Volume Guard (Liquidity Lock)**: Prevents the system from taking a position size that exceeds 1% or 2% of the stock's Average Daily Dollar Volume (over 50 days) to avoid the illusion of liquidity and severe slippage.

**T+2 Settlement Trap**: The Virtual Ledger will split cash into Settled Cash (available to buy) and Uncleared Cash (pending settlement) to mimic real Egyptian market clearing times, preventing impossible hyper-trading.

**Opening Gap Execution Logic**: If a stock gaps down below the hard stop-loss limit (e.g., opens at -15% when the stop is -10%), the system is forced to execute at the worst available opening price to record the true loss, testing the strategy against "Black Swan" events.

**Fundamental Data Lag**: Programming a delay layer that prevents the system from reading quarterly earnings data until 45 to 60 days after the quarter ends, completely eliminating fundamental Look-Ahead Bias.

**Macro Devaluation Filter**: A future safeguard to automatically raise the required Earnings Growth criteria in the quarters following a currency devaluation (float) to ensure the growth is truly operational, not just a currency exchange variance. **Explicitly deferred — do not implement in v1.**

**Scoring Queue (Watchlist Traffic Jam)**: A weighting system to rank stocks that simultaneously pass all criteria. If 15 stocks trigger a buy but the portfolio only has room for 6, the engine will buy the highest-scoring stocks based on catalyst strength and base quality until cash is depleted.

---

## 5. Sub-Strategies & Tactics

The architecture supports running multiple isolated virtual portfolios to test various Minervini tactics concurrently:

**Power Play / High Tight Flag (Limit-Up Hunter)**: A momentum sub-strategy targeting stocks that surged over 100% in under 8 weeks. It waits for a tight 10–20% correction on dried-up volume to place a Buy Stop order.

**Early Entry (3C — Cup Completion Cheat)**: An aggressive entry tactic allowing the system to build an initial position inside the Cup-with-Handle pattern before the handle is fully formed.

**The Turn**: Requires the stock to pass through 4 phases: decline, rally attempt, tight 5–10% pause, and a final breakout.

**Cyclical Bottom-Fishing**: Inverted P/E logic for cyclical sectors (Cement, Steel). Buys when earnings are crushed and P/E is sky-high (cycle bottom), sells when news is excellent (cycle top).

**Failure Reset (Second Chance)**: Stocks that hit their stop-loss are not permanently blacklisted. They return to the scanning universe to hunt for a new base or a pivot failure reset.

---

## 6. Cloud Automation & Deployment

**Free-Tier Hosting**: GitHub Actions or Oracle Cloud (Always Free Tier) for zero-cost hosting during the Paper Trading phase.

**Cron Jobs / Task Schedulers**: The system wakes up daily at 3:00 PM (just after EGX closes), fetches fresh prices, runs the filters, sends the shortlist to the AI for catalyst scoring, updates the database, and sends a summary notification via Telegram or Discord.

---

## 7. Future Vision: Market Depth (Order Book & Level 2)

V1 relies completely on End-of-Day (EOD) data. Future possibilities if an Institutional API becomes accessible:

**Detecting Hidden Liquidity (Iceberg Orders)**: Catching institutional accumulation hidden in the order book before the price breaks out.

**Zero Slippage Execution**: Verifying ask volume at the breakout price is large enough to fill the entire order without pushing the price up.

**Fakeout Prevention**: Canceling a buy signal if a resistance breakout is not supported by a strong wall of bid orders.

**Bid/Ask Imbalance**: Reading the instantaneous balance of power between buyers and sellers to gauge real-time momentum.
