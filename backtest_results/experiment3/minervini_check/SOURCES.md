# Minervini disclosed trades: sources and caveats

Built 2026-09-26 by a research subagent. It used WebSearch and WebFetch only. It did not bypass any login, paywall, CAPTCHA or bot wall. The companion file is `minervini_disclosed_trades.csv`, with 114 rows and 88 unique tickers covering 2021-01-04 to 2026-06-11.

## Counts

| category \ year | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | total |
|---|---|---|---|---|---|---|---|---|---|---|---|
| own_trade  | 0 | 0 | 0 | 0 | 34 | 1 | 3 | 40 | 13 | 13 | 104 |
| discussed  | 0 | 0 | 0 | 0 | 6  | 4 | 0 | 0  | 0  | 0  | 10  |
| model_book | 0 | 0 | 0 | 0 | 0  | 0 | 0 | 0  | 0  | 0  | 0   |

- Actions: BUY 46, HOLD 37, SELL 21, DISCUSSED 10.
- Confidence: high 54, medium 53, low 7.
- Date precision: exact 85, month 27, quarter 2.
- 7 SELL rows are SHORT sales, not exits of longs. Their `quote_or_evidence` starts with "SHORT": DIA 2023-12, SCHW 2024-09-12, SPY on 2024-12-09, 2025-02-24, 2025-08-18 and 2025-10-29, and RTX 2026-06-02. Filter them out for a long-only SEPA comparison.
- 13 rows are ETFs rather than stocks: XLE, IBIT, IWM, IWN, SPY and DIA.
- The 2021 block of 21 rows is the single best test set. It comes from Minervini's own published list of 2021 USIC sample trades, with exact entry dates.

## Main sources, most reliable first

1. **Minervini's published "USIC 2021 sample trades" list.** It gives 21 tickers with entry dates and was originally at minervini.com/68543/, which now returns 404/301.
   - The full list is reproduced by monty-trader.com (2022-01-22), which is the URL used in the CSV.
   - Other sources agree with it independently: the Business Wire 2022-01-24 release gives the context of a +334.8% return in the $1M+ division, the wallstreettrader.substack post shows ANF Jan 4 and GM Jan 11, a Boomerberg thread on threadreaderapp (2022-04-20) lists the same tickers, and a TaPlot tweet (2022-01-22) plotted the same "sample trades". A search snippet from sahamroket.com also matched the order and dates.
   - Minervini said it was a *sample*, not his full trade log. No exits were published.
2. **Minervini's own X posts.** I could not open x.com: fetches return HTTP 402 and I did not try to get around that. The post text comes from search-engine result titles, which show the post verbatim, often cut short.
   - Post dates come from decoding the status ID: timestamp_ms = (id >> 22) + 1288834974657. The decoded dates matched the dates the search engine itself reported. Rows with an exact date are either the post date or an entry date the post states (for example "bought ... on Apr. 26", "short initiated on Feb 24").
   - `source_type` is `other` for these rows.
3. **moomoo Community reposts of his X posts ("Mark.Minervini X updated").** These are dated reposts from 2023-12 to 2024-01.
   - Repost timestamps may be in an Asian time zone, so the original post could be up to one day earlier.
   - For HOLD rows that is harmless ("held as of"). For the 2024-01-25 SELL rows the true sale date is probably 2024-01-24.
4. **Benzinga "Hearing Swing Trader Mark Minervini ..." headlines, Aug-Dec 2021.** There are 10 rows covering SQ, SE, SNAP, AIG, RVLV, AAPL, NUE, CARR, YELL and SRTS.
   - The pages return 403 to the fetcher, so I only have the headline and the year/month from the URL path. The rows are therefore `month` precision and medium or low confidence.
   - These are second-hand reports of Minervini Private Access alerts. By design those alerts are his own trades, but Benzinga marks several as "unconfirmed". "Calls stock a pick" was treated as BUY.
5. **Secondary articles quoting his posts.**
   - newsonwallstreet.com (2025-10-24): TATT, CCL, UBER, IWN, MRUS, plus the residual positions ABVX, STX, IBIT, OLLI and IWM.
   - financialtechwiz.com: the XLE entry on 2022-01-03.
   - caseystubbs.substack.com: PYPL on 2021-06-09 and SCHW on 2021-10-15. Neither is on his 21-name list, so both are low confidence.
   - A Seeking Alpha Alpha Trader podcast from Apr 2021 mentions YETI, PYPL and DLTH as setups. The page returns 403, so this comes from a search snippet only and is low confidence.

## What was searched

- The 2021 USIC trades: Business Wire, TraderLion, Medium and Substack write-ups, and Scribd/Studocu copies.
- X posts found through the search engine, using phrases such as "we bought", "I bought", "long this morning", "we added", "sold", "booked", "stopped out", "short", "Focus List" and "names long", plus many ticker lists.
- Benzinga "hearing" headlines.
- moomoo reposts.
- IBD, Stockopedia and MarketWatch/Sincere interviews.
- Charlie M's "900+ setups from Minervini tweets 2010-2021" model book.
- Reddit and forum quotes.

## Accessible vs blocked

- **Accessible:** moomoo.com, monty-trader.com, newsonwallstreet.com, threadreaderapp.com, buzzchronicles.com, the Substack posts, stockopedia.com (2017 interview) and the finermarketpoints/financialtechwiz articles.
- **Blocked or failed:**
  - x.com (402).
  - web.archive.org (the fetch tool refuses this domain, so no archived copies could be used).
  - benzinga.com (403), traderlion.com (403), the Medium post (403) and seekingalpha.com (403).
  - Scribd and Studocu (metadata only).
  - The Notion copy of Charlie M's model book, which renders empty without JavaScript.
  - minervini.com/68543 and the /blog path (404), michaelsincere.com (404), the Stockopedia USIC article (404) and sahamroket.com (DNS failure).

## Caveats and limitations

- **2017-2020 gap: there are no dated ticker-level rows before 2021.** Minervini did tweet setups in those years; Charlie M's model book says 900+ setups from 2010-2021. However, the search index surfaces almost only 2021+ posts, and the model book (Notion/Scribd/PDF) could not be read.
  - A 2020-07-07 post (status 1280506672302219264) says he "started buying on Apr 6" 2020 but names no ticker.
  - A 2018-06-22 post (status 1010223336272678912) says "I bought at point C" on a chart with no visible ticker.
  - No `model_book` examples dated 2017 or later were found. The book examples found (AMZN 1997, TASR and others) are all pre-2017.
- **Selection bias.** The sample is heavily skewed toward posts that search engines index and that secondary sites chose to quote, which tend to be winners and recent (2024-2026) posts. It is not a complete or random sample of his trades. Most rows have no exit, and HOLD rows are "as of" snapshots.
- **Unclear buys.** The 2024-09-12 BUY rows (AXON, APP, LMB, NMM, DVA) come from "emerged from our Focus List; we added some new names", so a buy of each named stock is implied rather than stated. They are medium confidence.
- **Ticker as written.** "FRST" in the 2026-06-11 post is recorded exactly as written, and I did not confirm which company it refers to.
- **Duplicates by design.** A ticker can appear several times (BUY, HOLD, SELL, DISCUSSED), and NUE, AAPL, UPST, NVDA and SCHW each appear in more than one source. Deduplicate on (ticker, action, date) before scoring.
- **Holdout overlap.** Rows dated 2024-07 to 2026-09 fall in the project's locked holdout window. Using them for validation is the caller's decision.
