# Experiment 3: literature memo

Researcher memo, 2026-09-26. Written for the lead and the owner before the pre-registration (`../PREREGISTRATION_DRAFT.md`) is frozen.

**Scope.** Published or otherwise credible evidence on the ingredients of arms A, B1–B3, C and P-1, and base rates for what a retail-implementable momentum/breakout strategy can earn. No backtests were run.

**Verification markers.**
- **[V]**: the number was read in the primary source during this session (the paper's PDF or abstract page).
- **[S]**: the number was taken from a secondary summary (a search-engine abstract, a publisher landing page or a practitioner summary) and was not checked against the paper's tables.
- **[M]**: the claim comes from memory of a well-known paper and was not re-checked this session.
- **[NF]**: searched for and not found.

---

## Executive summary

1. **Momentum works best in its plain form.** The strongest, most replicated evidence is for a monthly-rebalanced top-decile or top-tercile sort on 12-month return. Long-only and after costs, the realistic premium over a small-cap index is about **+2–3% a year, at an information ratio of about 0.4**. That is not 30% or 100% a year.
2. **Nothing published tests RS ≥ 95 at the top 5%.** Pushing to the top 5% concentrates the book in high-volatility, lottery-like names. The literature pulls both ways on those names: momentum is stronger in them, and the lottery-stock (MAX) effect makes them underperform.
3. **"Close at a 50-day high on ≥ 1.2× volume" has only indirect support.** Being near the 52-week high predicts returns (George & Hwang 2004), returns are positive after 52-week-high crossings, and volume shocks predict higher returns over the next month. No peer-reviewed test of the exact N-day-breakout-on-volume rule was found.
4. **CAN SLIM and O'Neil-style screens have no clean, after-cost, out-of-sample record.** The one live, mechanical implementation, the IBD 50 ETF (FFTY, since 2015), returned about **3.5% a year** since inception (5.2% over 10 years, against a 12.6% category average). No peer-reviewed test of Minervini's SEPA exists **[NF]**.
5. **Earnings momentum is a real complement to price momentum.** Novy-Marx argues it subsumes price momentum, and controlling for past performance removes the crashes. But post-earnings-announcement drift (PEAD) outside microcaps has been ~0 since about 2006. B2's "penalty, not veto" is consistent with the literature, but the literature expects the penalty to have a small effect.
6. **Tight fixed stops on individual stocks usually hurt after costs** (Lo & Remorov 2017). Stops help when returns are serially correlated or trending (Kaminski & Lo 2014) and at the momentum-portfolio level (Han, Zhou & Zhu, a working paper). Volatility scaling roughly doubles momentum's Sharpe in-sample, but out-of-sample evidence for volatility management in general is weak (Cederburg et al. 2020). **P-1 is directionally supported, with modest expectations.**
7. **Momentum's crashes come in market rebounds after bear markets,** mostly from the short (loser) leg. A long-only book avoids the worst of it but still lags its benchmark badly in V-shaped recoveries. Momentum profits were positive only after UP markets: +0.93%/month, against −0.37% after DOWN markets. A regime gate is supported. The cost is lagging the MDY/IJR blend in rebounds such as 2009 and 2020.
8. **LLM news ratings do predict returns, but over 1–2 days.** The long-short edge was 34 bp/day before costs, practical only for very-low-cost traders, and it declines as LLM adoption rises. Arm C holds positions for weeks and enters at the next open, a poor fit. Backtesting any LLM signal on pre-cutoff data is invalid (memorization). A forward test with a pinned snapshot and timestamps is the accepted fix, and it should add **anonymization** (Glasserman & Lin).
9. **Base rates are sobering.**
   - Backtest Sharpe ratios shrink by a median of 73% when strategies go live.
   - Anomaly returns are 58% lower after publication.
   - Few retail speculators are profitable after costs: 97% of persistent Brazilian day traders lost money.
   - No audited, systematic, public 100%+/year record was found **[NF]**.
10. **The design implication is power.** If the true excess IR is 0.3–0.5, which is the best the literature supports, the 5-year test has little power: it would take **18–50 years** to confirm at 80% power (α = 0.10). Expect INCONCLUSIVE unless the arm fails outright. Three low-cost additions are proposed below: a plain-momentum control arm, rank-hysteresis exits, and ranking by smoothness or the 52-week high.

---

## Q1. Cross-sectional momentum / relative strength

**Key findings**

- **The core effect.** Buying past 3–12-month winners and selling losers earned about **1% a month** (decile long-short, 6/6 formation and holding, US 1965–89) **[V, via George & Hwang's restatement]**.
  - Jegadeesh & Titman (1993), *Journal of Finance* 48(1):65–91. https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1993.tb04702.x
- **Robust across time and markets.** The effect appears in 212 years of US data and 20+ years out of sample, in 40 countries and in a dozen asset classes **[S]**.
  - Asness, Frazzini, Israel & Moskowitz (2014), "Fact, Fiction and Momentum Investing", *Journal of Portfolio Management*. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2435323
- **How the long side compares.** In AQR's quintile sort (1927–2008), the top quintile's return in excess of the beta-adjusted market was about +7%/yr, and the 4th quintile's about +2% **[V, read off a chart, approximate]**.
  - Long-short momentum, US 1975–2008: **Sharpe 0.7, 10.5%/yr** at 15% volatility, gross **[V]**.
  - Source: Berger, Israel & Moskowitz (2009), "The Case for Momentum Investing", AQR white paper. https://www.aqr.com/-/media/AQR/Documents/Insights/White-Papers/The-Case-for-Momentum-Investing.pdf
- **Long-only numbers: the most relevant base rate for this project.** From the same paper, for January 1980 to April 2009, backtested indices built on the top third by 12-1 momentum, cap-weighted and rebalanced quarterly **[V]**:

  | Index | Annual return | Benchmark | Excess | Tracking error | IR | Sharpe | Estimated costs |
  |---|---|---|---|---|---|---|---|
  | AQR Momentum (large/mid) | 13.7% | Russell 1000: 11.2% | **+2.5%** | 8.1% | 0.30 | 0.38 vs 0.30 | 0.7%/yr |
  | AQR Small Cap Momentum | 15.4% | Russell 2000: 11.2% | **+4.2%** | 7.0% | 0.60 | 0.40 vs 0.24 | 1.5%/yr |

  - Net of the estimated costs, that is about **+1.8%** (large) and **+2.7%** (small), with net IRs of about 0.2 and 0.4.
  - These are historical indices, not live portfolios.
- **The long side's share.** Long positions produce about **half** of momentum's profits. Momentum shows "no reliable relation with size" in 86 years of data **[S]**.
  - Israel & Moskowitz (2013), *Journal of Financial Economics* 108(2):275–301. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089466
- **Size and analyst coverage.** Past the very smallest stocks, momentum profits decline sharply with size, and are larger in stocks with low analyst coverage **[S]**. In Fama & French's international data, momentum spreads also fall from small to big stocks **[S]**.
  - Hong, Lim & Stein (2000), *Journal of Finance* 55(1):265–295. https://www.nber.org/papers/w6553
  - Fama & French (2012), *Journal of Financial Economics* 105(3):457–472. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1720139
  - Mid and small caps (S&P 400/600) are therefore a reasonable place to look. The S&P 600's profitability screen probably removes some of the micro-cap stocks that drive the strongest results **[M]**.
- **Transaction costs: the estimates disagree.**
  - **Illusory:** momentum stocks are the expensive ones to trade, and costs erase the profit (pre-decimal data) **[S]**. Lesmond, Schill & Zhou (2004), *Journal of Financial Economics* 71:349–380. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=256926
  - **Survives with cost-aware design:** costs are 20–57 bp per trade for mid-turnover anomalies. Anomalies with turnover under 50% a month survive, and a **buy/hold spread** (a stricter rule to enter than to stay) is the most effective cost mitigation. Momentum stays profitable net of costs **[S]**. Novy-Marx & Velikov (2016), *Review of Financial Studies* 29(1):104–147. https://www.nber.org/papers/w20721
  - **Cheap at scale:** real institutional costs on about $1 trillion of live trades were less than a tenth of the academic estimates **[S]**. This applies to an institution with algorithmic execution, not to a retail trader buying breakouts at the open. Frazzini, Israel & Moskowitz, "Trading Costs of Asset Pricing Anomalies" (working paper). https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2294498
- **Crashes.**
  - In July–August 1932, the loser decile rose **+232%** and the winner decile **+32%**. In March–May 2009, losers rose **+163%** and winners **+8%** **[V]**.
  - Crashes come in "panic" states: after market declines, with high volatility, and during the rebound. After declines, loser betas can exceed 3 and winner betas fall below 0.5.
  - A dynamic, volatility- and forecast-weighted version about **doubles the alpha and Sharpe** of static momentum **[V]**.
  - Source: Daniel & Moskowitz (2016), *Journal of Financial Economics* 122(2):221–247. https://www.nber.org/papers/w20439
  - **Implication for long-only arms:** the crash is mostly in the short leg. A long-only book still badly lags the market in V-shaped rebounds (winners +8% while the market ripped in March–May 2009).
- **Decay and instability.** The risk-adjusted premium was significant only in certain subperiods (about the 1940s to the mid-1960s, and the mid-1970s to the late 1990s), and has been declining since the early 1990s **[S]**.
  - Hwang & Rubesam (2015), *European Journal of Finance* 21(7):584–607. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=968176
  - Across 97 anomalies, returns are 26% lower out-of-sample and **58% lower post-publication** **[S]**. McLean & Pontiff (2016), *Journal of Finance* 71(1):5–32. https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365
- **After 2010.** A Robeco study reportedly finds a momentum premium of about 3.5%/yr for 2010–2019, below its long-run average but positive **[S, unverified: the source PDF returned 404]**. https://www.robeco.com/en-us/insights/2020/11/factor-investing-going-beyond-fama-and-french
  - A clean post-2010 US small/mid-cap figure should be computed from Ken French's data library (UMD, or the size × momentum portfolios) before quoting any number **[NF this session]**.
- **Extreme ranks (top 5%).** No paper was found that isolates the top 5% versus the top 10% **[NF]**. The related evidence points both ways:
  - **Momentum is stronger in high-volatility stocks.** Momentum returns are higher among high idiosyncratic-volatility stocks (especially losers), and those stocks reverse faster **[S]**. Arena, Haggard & Yan (2008), *Financial Review* 43(2):159–190. https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6288.2008.00190.x
  - **Lottery-like stocks underperform (the MAX effect).** Stocks with the largest recent single-day returns underperform by **>1%/month** **[S]**. Bali, Cakici & Whitelaw (2011), *Journal of Financial Economics* 99(2):427–446. https://pages.stern.nyu.edu/~rwhitela/papers/max%20jfe11.pdf
  - **How the path matters.** Momentum built from many small moves ("continuous information") earned **8.86%** over 6 months, against **2.91%** for momentum built from a few large jumps ("discrete information") **[S]**. Da, Gurun & Warachka (2014), "Frog in the Pan", *Review of Financial Studies* 27(7):2171–2218. https://academic.oup.com/rfs/article-abstract/27/7/2171/1578455
  - **Residual momentum.** Ranking on residual (factor-adjusted) returns gives about **2×** the risk-adjusted profit of total-return momentum, and is less concentrated in the extremes **[S]**. Blitz, Huij & Martens (2011), *Journal of Empirical Finance*. https://www.ssrn.com/abstract=2319883

**Failure modes.** Crashes in rebounds; transaction costs in small and volatile names; post-publication decay; long stretches with no premium; extreme-rank books drifting into lottery stocks.

---

## Q2. 52-week-high and new-high breakout effects; volume confirmation

**Key findings**

- **The 52-week high.** The ratio of price to its 52-week high "dominates and improves upon" past returns in forecasting future returns. Its predictions **do not reverse** in the long run **[V: abstract and intro]**. The mechanism is anchoring: traders are reluctant to bid a stock through its 52-week high on good news.
  - Secondary sources quote about 0.65%/month for the 52-week-high strategy against 0.38%/month for Jegadeesh–Titman momentum (1.06% excluding January) **[S, not checked against the paper's tables]**.
  - George & Hwang (2004), *Journal of Finance* 59(5):2145–2176. https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2004.00695.x
  - **This is a continuous "nearness" measure ranked cross-sectionally and held 6–12 months,** not a same-day breakout event.
- **Crossing the 52-week high.** Volume is "strikingly higher" when price crosses the upper or lower limit of its 52-week range, more so for small firms and stocks with high individual-investor interest. **"After either event, returns are reliably positive"** **[V: abstract]**. The abstract does not say whether returns depend on the volume at the crossing.
  - Huddart, Lang & Yetman (2009), *Management Science* 55(1):16–31. https://pubsonline.informs.org/doi/10.1287/mnsc.1080.0920
- **Volume shocks.** Stocks with unusually high volume over a day or a week **appreciate over the following month**, consistent with a visibility effect **[S]**. This is the closest published support for a "≥ 1.2× volume" confirmation.
  - Gervais, Kaniel & Mingelgrin (2001), "The High-Volume Return Premium", *Journal of Finance* 56(3):877–919. https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00349
- **Volume can also count against.** High formation-period *turnover* marks "glamour" stocks: lower future returns and faster reversals for high-volume winners. Intermediate-term momentum is larger among high-volume stocks **[S]**. This is turnover over 3–12 months, not a breakout-day spike.
  - Lee & Swaminathan (2000), *Journal of Finance* 55(5):2017–2069. https://onlinelibrary.wiley.com/doi/10.1111/0022-1082.00280
- **Trading-range breakout as a timing rule.** It worked on the DJIA from 1897 to 1986 (Brock, Lakonishok & LeBaron 1992). After a data-snooping correction, the best rule **failed in the following 10-year post-sample period** **[S]**.
  - Sullivan, Timmermann & White (1999), *Journal of Finance* 54(5):1647–1691. https://onlinelibrary.wiley.com/doi/10.1111/0022-1082.00163
- **Distance from moving averages.** The distance between the 21- and 200-day moving averages (MAD) predicts returns beyond momentum and the 52-week high: about **9% annualized value-weighted alpha**, stronger on the long side, and it survives institutional costs **[S]**. This bears on B3's moving-average path.
  - Avramov, Kaplanski & Subrahmanyam (2021), *Review of Financial Economics* 39(2):127–145. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3111334
- **Short-term reversal.** Stocks that surged in the past month tend to reverse the next month. This is why academic momentum skips the most recent month (AQR 2009, footnote 14, citing Jegadeesh 1990 and Lehmann 1990) **[V: footnote]**. A breakout rule buys right after a strong short-term move, and so fights this effect.

**Does "close at an N-day high on ≥ 1.2× volume" have independent support?** Only indirectly. The pieces are:
- nearness to the 52-week high (George & Hwang);
- positive returns after 52-week-high crossings (Huddart et al.);
- volume shocks (Gervais et al.).

Each piece is supported. The **specific rule** (50-day rather than 52-week, a same-day event, and the 1.2× threshold) has no peer-reviewed test **[NF]**. The MODEL_BOOK's evidence for H1 is in-sample only.

**Failure modes.** The rule fights the 1-month reversal effect. A 50-day high fires far more often than a 52-week high, which dilutes the anchoring story. The 1.2× threshold was chosen in-sample.

---

## Q3. Independent evaluations of CAN SLIM, O'Neil and Minervini screens

**Key findings**

- **Olson, Nelson, Witt & Mossman (1998), *Financial Review* 33(2):161–176.** Trading on Investor's Daily stock rankings gave market-adjusted abnormal returns of **1.81%/month** on S&P 500 stocks (1984–1992) **[S]**. The selected stocks were more volatile, and the **abnormal returns were lower in the second half** of the sample. Before costs. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=95548
- **AAII's CAN SLIM screens.** The original screen shows **19.2%/yr (1998 – May 2023)** against the S&P 500's 5.7% (price only). Variants: "No Float" 12.2% and "3rd Edition" 15.4% **[V: AAII article]**. https://www.aaii.com/journal/article/68036-a-tribute-to-william-o-neil-revisiting-the-can-slim-strategy
  - **Caveats:**
    - These are hypothetical, monthly-rebalanced, equal-weighted screens that exclude costs, published by the screen's sponsor.
    - The variants' spread (12–19%) shows how sensitive the results are to specification.
  - CXO Advisory's independent review of all 60 AAII screens (1998 – March 2018) found a gross CAGR of 12.1%, and 9.4% net of 0.5% friction per monthly rebalance. Average turnover was 41%/month, and "gross screen outperformance deteriorates markedly to underperformance over time". The review did not isolate CAN SLIM **[V: CXO page]**. https://www.cxoadvisory.com/investing-expertise/aaii-stock-screens/
- **The live, mechanical implementation.** The IBD 50 ETF (FFTY, now "CapForce IBD 50 ETF"), inception April 2015:
  - **3.50%/yr since inception**, as of 2026-09-26 **[V: stockanalysis.com]**. https://stockanalysis.com/etf/ffty/
  - As of 2026-08-31: 10-year 5.2%/yr against 12.6% for its Mid-Cap Growth category, 5-year −4.7%/yr, beta 1.69 **[V: AAII ETF page]**. https://www.aaii.com/etf/ticker/FFTY
  - Expense ratio 0.80%. **This is the cleanest out-of-sample, after-cost evidence on an O'Neil-style selection, and it is negative.**
- **Low-credibility academic tests.**
  - Lutey, Crum & Rayome (2014), *Journal of Accounting and Finance* 14(5), North American Business Press: 604% over 14 years against 73% for the NASDAQ-100 **[S]**. Low-tier venue, and costs and survivorship are unclear. http://www.na-businesspress.com/JAF/LuteyM_LWeb14_5_.pdf
  - Cheh, Kim & Lee (2011) and Najafi & Asgari (2013) are cited secondhand only **[S, not located]**.
- **Minervini / SEPA / VCP.** No peer-reviewed or independent after-cost evaluation was found **[NF]**. Public evidence consists of the author's own books, competition results (self-selected, and not a systematic rule set) and unaudited community backtests. Experiment 2 is, as far as we know, one of the more rigorous tests, and it failed out-of-sample.

**Verdict.** No evidence that CAN SLIM or SEPA screens beat a passive benchmark after costs, out of sample. The best live data point (FFTY) is clearly negative. The hypothetical screens degrade over time.

---

## Q4. Earnings acceleration, PEAD and fundamental momentum as filters

**Key findings**

- **Price and earnings momentum are distinct.** Past return and past earnings surprise **each predict drift after controlling for the other**, and there is little reversal **[S]**.
  - Chan, Jegadeesh & Lakonishok (1996), *Journal of Finance* 51(5):1681–1713. https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1996.tb05222.x
- **Price momentum as a noisy proxy.** Price momentum is "largely driven by systematic earnings surprises" and is a noisy proxy for earnings momentum (NYSE/AMEX, 1972–1999) **[S]**.
  - Chordia & Shivakumar (2006), *Journal of Financial Economics* 80(3):627–656. https://www.sciencedirect.com/science/article/abs/pii/S0304405X05002175
- **Earnings momentum subsumes price momentum.** Earnings-surprise measures subsume past returns. **Controlling for past performance in earnings momentum eliminates the crashes without reducing average returns** **[S]**.
  - Novy-Marx (2015), "Fundamentally, Momentum Is Fundamental Momentum", NBER w20984. https://www.nber.org/papers/w20984
- **Earnings acceleration.** The quarter-over-quarter change in earnings growth (the "A" in CAN SLIM, formalized) has significant explanatory power for future excess returns **[S; effect size not extracted]**.
  - He & Narayanamoorthy (2020), *Journal of Accounting and Economics* 69(1):26–47. https://doi.org/10.2139/ssrn.3057632
- **PEAD has largely disappeared.** For large stocks PEAD has been **non-existent since 2006**, and it only recently disappeared in microcaps **[S]**.
  - Martineau (2022), "Rest in Peace Post-Earnings Announcement Drift", *Critical Finance Review* 11(3–4):613–646. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3111607
  - The reconciliation: across all stocks, post-2006 drift has t = 2.18. **Excluding microcaps, t = 1.43** **[S: summary by UCLA Anderson Review]**. Subrahmanyam (2025), SSRN 5930255. https://anderson-review.ucla.edu/is-post-earnings-announcement-drift-a-thing-again/

**Implication.** Fundamentals are informative, which justifies keeping them. But the modern (post-2006), non-microcap return to earnings news is small, and much of it is priced on the announcement day. Converting one Q2/Q4 miss from a veto into a ranking penalty (B2) is consistent with the literature. The expected effect is small and will not be detectable in the forward window.

---

## Q5. Stop-losses, ATR stops and volatility-managed sizing

**Key findings**

- **When stops can help.** Under a random walk, **stop-loss rules always reduce expected return**. They can add value only when returns trend (momentum or serial correlation) **[V: abstract]**.
  - Empirically, on US equities switching to bonds (monthly, 1950–2004), some rules added **50–100 bp/month during stop-out periods**.
  - This is a market-level timing rule, not a stop on individual stocks.
  - Kaminski & Lo (2014), *Journal of Financial Markets* 18:234–254. https://ideas.repec.org/p/hhs/sifrwp/0063.html
- **Stops on individual stocks.** On a large sample of US stocks, **tight stops underperform buy-and-hold** in mean-variance terms because of trading costs. The exceptions are stocks with high serial correlation. Downside risk falls, but "not substantially" **[S]**.
  - Lo & Remorov (2017), *Journal of Financial Markets*. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2695383
- **Stops on momentum portfolios.** Top-decile 6-month momentum, US 1926–2011, with a 10% stop from the month's starting price:
  - the worst monthly loss fell from −49.79% to −11.36% (equal-weighted) and from −64.97% to −23.28% (value-weighted);
  - **the Sharpe ratio more than doubled** **[S]**.
  - Caveats: a working paper (not found in a peer-reviewed journal **[NF]**); the stop resets monthly; the intramonth execution assumption was not checked.
  - Han, Zhou & Zhu, "Taming Momentum Crashes: A Simple Stop-Loss Strategy", SSRN 2407199. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2407199
- **Volatility-scaling momentum.** Scaling momentum to a 12% volatility target raises the **Sharpe from 0.53 to 0.97**, cuts excess kurtosis from 18.24 to 2.68, and lifts the worst month from −78.96% to −28.40% **[S]**. This is for the long-short factor.
  - Barroso & Santa-Clara (2015), "Momentum Has Its Moments", *Journal of Financial Economics* 116(1):111–120. https://ideas.repec.org/a/eee/jfinec/v116y2015i1p111-120.html
- **Volatility management in general.** Volatility-managed factors produce large alphas in spanning regressions (market, value, momentum and others) **[S]**.
  - Moreira & Muir (2017), *Journal of Finance* 72(4):1611–1644. https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12513
  - **Counter-evidence:** real-time versions across **103 strategies** show "no statistical or economic evidence" of systematically higher Sharpe ratios, because the spanning regressions are structurally unstable **[S]**. Cederburg, O'Doherty, Wang & Yan (2020), *Journal of Financial Economics*. https://www.sciencedirect.com/science/article/abs/pii/S0304405X2030132X
- **Weighting momentum by volatility.** Own-volatility and underlying-volatility weighting was studied for momentum on US industry portfolios **[S; numbers not extracted]**.
  - du Plessis & Hallerbach (2017), *Journal of Alternative Investments* 19(3):40–58. https://jai.pm-research.com/content/19/3/40/tab-article-info
- **ATR-multiple stops on individual stocks (e.g. 2 × ATR).** No peer-reviewed evaluation was found **[NF]**. What exists is practitioner and blog material. Treat any specific multiplier as untested.

**Implications for P-1 (2 × ATR stop, 1% risk sizing)**

- **Wider, volatility-scaled stops are directionally supported.** Lo & Remorov say tight stops hurt. The MODEL_BOOK finding points the same way: among candidates with ATR of 5–7%, 12% doubled, but 55% first closed ≥ 8% below entry within 20 days.
- **1%-risk sizing is inverse-volatility weighting.** Position size = 1% ÷ stop%. At ATR 4.6%, the stop is 9.2% and the position is about 10.9% of equity. At ATR 3.2%, the stop is 6.4% and the position is about 15.6%.
  - This **underweights exactly the high-ATR names** that the model book found were the doublers.
  - The literature cuts both ways: momentum is stronger in high-idiosyncratic-volatility stocks (Arena et al.), while high-MAX stocks underperform (Bali et al.).
  - Net effect: lower variance, and an ambiguous effect on return.
- **Portfolio-level volatility targeting is the better-supported form** (Barroso & Santa-Clara; Daniel & Moskowitz), but it is fragile out of sample (Cederburg et al.).

---

## Q6. Trend filters and regime timing on momentum

**Key findings**

- **Market states.** From 1929 to 1995, the mean monthly momentum profit was **+0.93% after positive market returns (UP states) and −0.37% after negative ones (DOWN states)**, with the state defined by the lagged 3-year market return. UP-market momentum reverses in the long run **[S; state definition V, via Daniel & Moskowitz]**.
  - Cooper, Gutierrez & Hameed (2004), "Market States and Momentum", *Journal of Finance* 59(3):1345–1365. https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2004.00665.x
- **Crash states are forecastable.** Crashes follow bear markets combined with high volatility. Momentum's premium is low when market volatility is high (Stivers & Sun 2010, cited by Daniel & Moskowitz) **[V: intro]**. https://www.nber.org/papers/w20439
- **Implication for this long-only strategy:**
  - A regime gate (market above its long moving average, or similar) is **supported**: momentum's expected return is low or negative in DOWN and panic states.
  - The **measurable cost** is that a gated long-only book sits out, or holds low-beta winners, during the sharpest rebounds. Against an always-invested MDY/IJR blend, that is a large relative loss in 2009-type or 2020-type recoveries.
  - Experiment 2's arm invested only about 26% of the time, which is consistent with a very defensive gate.

---

## Q7. LLM news/sentiment trading, and look-ahead bias

**Evidence of predictability** (Lopez-Lira & Tang, "Can ChatGPT Forecast Stock Price Movements?", arXiv 2304.07619, v6 of October 2025 **[V: pp. 1–5]**; https://arxiv.org/abs/2304.07619):
- **Sample:** post-cutoff headlines for 4,123 US stocks, October 2021 – May 2024.
- **Hit rates:** GPT-4's portfolio-day hit rate for the direction of the **non-tradable initial reaction** is 93.3% for overnight headlines and 88.8% for intraday headlines.
- **Drift:** it lasts **1–2 trading days**. A daily-rebalanced long-short strategy earns **34 bp/day before costs**, with a next-day drift Sharpe of 2.97 for GPT-4 against 1.66 for GPT-3.5.
- **Who can exploit it:** "only feasible for market participants whose transaction costs are sufficiently low, such as market makers".
- **Concentration and decay:** strongest in small stocks and negative news, and **strategy returns decline as LLM adoption rises**.
- **Venue:** reportedly published in or forthcoming at the *Journal of Financial Economics* **[S, venue not verified]**.

**Evidence against durability.** Previously reported LLM advantages "deteriorate significantly" over two decades and more than 100 symbols. LLM strategies are too conservative in bull markets and too aggressive in bear markets **[V: abstract]**.
- Li, Kim, Cucuringu & Ma, "Can LLM-based Financial Investing Strategies Outperform the Market in Long Run?" (FINSABER), KDD 2026 Datasets & Benchmarks track. https://arxiv.org/abs/2505.07078

**Look-ahead bias and memorization**
- **Glasserman & Lin (2023), arXiv 2309.17322.** Two biases: look-ahead (knowing what happened after the news) and **distraction** (general knowledge of the company contaminates the sentiment reading) **[V: abstract]**. https://arxiv.org/abs/2309.17322
  - In-sample, **anonymized headlines outperform** the originals, so distraction does more damage than look-ahead, especially for large firms.
  - Out of sample, look-ahead stops being a problem, but distraction can remain. **Anonymization is recommended for live use too.**
- **Lopez-Lira, Tang & Zhu (2025), "The Memorization Problem", arXiv 2504.14765.** LLMs recall exact pre-cutoff economic and financial values. Instructions to respect a date fail, and **masking fails** because models reconstruct entities and dates from minimal context **[S]**. https://arxiv.org/abs/2504.14765
  - Remedy: a hard training cutoff, then rolling forecasts after it.
- **Sarkar & Vafa (2024), SSRN 4754678 (ICML 2025).** Direct tests find look-ahead bias in applications to earnings calls and elections. Prompting cannot remove it **[S]**. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4754678
- **Point-in-time models.**
  - ChronoBERT/ChronoGPT, trained only on text available at each date: He, Lv, Manela & Wu (2025), arXiv 2502.21206 **[S]**. https://arxiv.org/abs/2502.21206
  - Time Machine GPT (GPT-2-small scale): Drinkall et al. (2024), Findings of NAACL **[S]**. https://aclanthology.org/2024.findings-naacl.208/
  - These make leak-free backtests possible, but with far weaker models than current frontier LLMs.

**What a clean forward test of arm C needs** (the draft already covers most of these):

| Requirement | In the draft? |
|---|---|
| Pinned **snapshot** model id (not an alias); knowledge cutoff recorded and earlier than Day 1 | Yes (pinned id). Add: record the stated cutoff |
| **Vendor-deprecation plan.** Hosted snapshots get retired mid-test; state now how a forced model change is handled (a new segment) | Partly ("any model change = new segment") |
| Document timestamps (EDGAR acceptance time, news publication time) ≤ signal time, logged with hashes | Yes |
| Frozen prompt hash; no browsing or tools; model sees only the supplied documents | Yes |
| **Store raw outputs and never re-query.** Temperature 0 is not bit-deterministic on hosted APIs **[M]** | Partly (hash-chained log). Make "never re-query" explicit |
| **Anonymize** the company name and ticker in the documents (Glasserman & Lin distraction effect), or pre-register named vs anonymized with one primary | **No. Recommended addition** |
| Never back-fill or "re-rate" history with a newer model (memorization) | Implied. Make explicit |
| Pre-specify the rating's horizon. The literature's edge lasts 1–2 days and the arm enters at the next open and holds weeks, so expect about 0 | Expectation stated ("low") |

---

## Q8. Base rates: realistic returns, rarity of 100%+/yr, survivorship

**Key findings**

- **Long-only momentum ceiling.** Historically about +2.5% (large caps) to +4.2% (small caps) per year over the benchmark, gross. Net: about +1.8% to +2.7%. **Absolute Sharpe about 0.4**, and **IR 0.3–0.6 gross, about 0.2–0.4 net** (AQR 2009 **[V]**, above).
- **Backtest to live.** Across 215 bank "alternative beta" strategies, the **median Sharpe fell 73%** from backtest to live, and more for complex strategies **[S]**.
  - Suhonen, Lennkh & Perez (2017), *Journal of Portfolio Management* 43(2):90–104. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2757113
- **Backtest Sharpe predicts little.** Across 888 Quantopian algorithms, the backtest Sharpe explained almost none of out-of-sample performance (**R² < 0.025**) **[S]**.
  - Wiecki, Campbell, Lent & Stauth (2016), *Journal of Investing* 25(3):69. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2745220
- **Multiple testing.** New factors need **t > 3.0** (Harvey, Liu & Zhu 2016, *Review of Financial Studies* 29(1):5–68 **[S]**; https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2249314). The Deflated Sharpe Ratio corrects for selection across N trials (Bailey & López de Prado 2014, *Journal of Portfolio Management* 40(5):94–107 **[S]**; https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551).
  - This project's own evidence: a DSR of 0.41 at N = 1,188, then an in-sample 25.7% CAGR that became −0.6% on fresh data.
- **Retail speculators.**
  - Among Taiwanese day traders (1992–2006), few earn positive abnormal returns net of fees **[S]**. Barber, Lee, Liu & Odean (2014), *Journal of Financial Markets*. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=529063
  - Brazil (2013–2015): **97% of day traders who persisted 300+ days lost money**, and 1.1% earned more than the minimum wage **[S]**. Chague, De-Losso & Giovannetti (2019), SSRN 3423101. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3423101
- **100%+ a year.** No audited, systematic, publicly documented equity strategy with multi-year 100%+/yr returns at retail-implementable scale was found **[NF]**. Claims of this kind come from competitions and self-reports (selection bias: survivors report). The best live O'Neil-style vehicle made about 3.5%/yr (FFTY).
- **Survivorship bias from current index members.**
  - **Local measurement** (EXPERIMENT2_REPORT §4): over 2017–2021, current S&P 400 + 600 members equal-weighted earned **19.9% CAGR, against 12.5% for MDY/IJR**. That gap of about **7 points a year** is an *upper bound* on survivorship, because it also includes equal- versus cap-weighting.
  - A blog-level estimate for S&P 500 current-constituent backtests is +1–2%/yr **[S, low credibility]**. https://www.susanpotter.net/quant/backtest-bias-taxonomy/
  - The mechanism: today's members include stocks added *because* they had already risen, and exclude the ones that were removed. Momentum and breakout screens are especially exposed, because the added stocks were the past winners.
  - **Going forward:** the frozen universe removes this bias.

---

## Implication for each experiment-3 arm

| Arm | Verdict | Reason |
|---|---|---|
| **A** (experiment-2 pick, VCP + trend template + fundamentals veto + tight stop) | **Contradicted** | Failed on fresh data (−0.6% CAGR). VCP has no peer-reviewed support [NF]. Tight individual-stock stops lose to costs (Lo & Remorov). The one live O'Neil-style vehicle underperformed (FFTY). Keep it as a reference arm only. |
| **B1** (RS ≥ 95 ranked; close at a 50-day high on ≥ 1.2× volume) | **Mixed, leaning supported** | RS/momentum is the best-documented anomaly, and the top ranks carry the long-side profit (Jegadeesh & Titman; AQR). The breakout pieces have indirect support (George & Hwang; Huddart et al.; Gervais et al.). **But:** the exact rule is untested [NF]; the top 5% tilts toward lottery/MAX names; buying after a surge fights 1-month reversal; and a breakout-event entry is not the continuous-rank construction the literature validates. Realistic net excess is 0–3%/yr. |
| **B2** (single fundamentals miss becomes a ranking penalty) | **Mixed** | Earnings momentum is informative and complements price momentum (Chan, Jegadeesh & Lakonishok; Novy-Marx), so a soft penalty rather than a hard veto is sensible. Post-2006 PEAD outside microcaps is about 0 (Martineau; Subrahmanyam), so the B2 − B1 difference will be tiny and undetectable. |
| **B3** (early Stage-2 path via price above the 50/150/200-day MAs) | **Mixed** | Moving-average distance predicts returns and is stronger on the long side (Avramov et al. 2021), which supports a simpler MA-based trend condition. No test of the specific tt_1/tt_2/tt_7 subset [NF]. More trades in less-extended names means more whipsaw, and it moves the arm toward generic momentum. |
| **C** (LLM catalyst rating as a ranking input) | **Mixed to contradicted at this horizon** | LLM news signals are real but last 1–2 days, are exploitable mainly by very-low-cost traders, and decay with adoption (Lopez-Lira & Tang). They deteriorate over long samples (FINSABER). Experiment 1 found zero effect. The forward design is the correct methodology (Glasserman & Lin; Lopez-Lira, Tang & Zhu; Sarkar & Vafa). **Add anonymization.** Expect about 0. |
| **P-1 / B4** (2 × ATR stop, minimum 4%; 1% risk sizing) | **Mixed, directionally supported** | Wider, volatility-scaled stops avoid the tight-stop cost drag (Lo & Remorov) and match the model book's finding that volatile winners get shaken out. Stops add value only if returns trend (Kaminski & Lo). Volatility scaling helps momentum at the portfolio level (Barroso & Santa-Clara; Daniel & Moskowitz), but the out-of-sample record for volatility management is weak (Cederburg et al.). 1% risk sizing underweights the high-ATR names that were the doublers. No peer-reviewed test of ATR-multiple stops [NF]. |
| *(inherited)* Regime gate | **Supported, with a known cost** | Momentum is negative after DOWN markets (Cooper et al.) and crashes in panic states (Daniel & Moskowitz). The gate will make every arm lag MDY/IJR in V-shaped rebounds. |

---

## New ideas the literature strongly supports (at most 3)

1. **Add a plain-momentum control arm (arm M).**
   - Construction: 12-1-month return, top decile (or tercile) of the frozen universe, equal-weight, rebalanced monthly, with the same costs and regime gate as the other arms.
   - *Rationale:* every strong result in Q1 is for this construction, not for breakout timing. Without M, a positive or negative B1 cannot be attributed to the factor or to the entry and exit machinery. It is cheap to run and gives the one contrast the literature can actually predict.
2. **Use a rank-hysteresis exit (a buy/hold spread) instead of relying on tight price stops.**
   - Construction: enter at RS ≥ 95; stay while RS ≥ about 80 and the trend condition holds; keep only a wide catastrophe stop.
   - *Rationale:* Novy-Marx & Velikov find a buy/hold spread is the most effective cost mitigation for anomalies. Lo & Remorov find tight individual-stock stops underperform after costs. It targets experiment 2's failure directly: 50 of 80 trades hit the stop.
3. **Within RS ≥ 95, rank by path quality rather than raw RS.**
   - Candidate measures: frog-in-the-pan smoothness (information discreteness), residual (factor-adjusted) momentum, or nearness to the 52-week high.
   - *Rationale:* smooth momentum earned 8.86% against 2.91% for jumpy momentum (Da et al.). Residual momentum gives about 2× the risk-adjusted profit (Blitz et al.). 52-week-high nearness dominates past returns (George & Hwang). All three push the book away from lottery/MAX names (Bali et al.).

*(All three must be pre-registered before Day 1, or started on their own clock under the draft's rules.)*

---

## What the literature says to expect

| Quantity | Realistic range | Basis |
|---|---|---|
| Net excess return vs the MDY/IJR blend, per year, for a well-built long-only momentum/breakout arm | **−3% to +3%**, central about 0 to +2% | AQR long-only small-cap momentum: +4.2% gross, about +2.7% net (1980–2009); then a post-publication haircut (McLean & Pontiff: −58% for anomalies in general); the regime gate's lag in rebounds; FFTY's live record |
| Excess information ratio vs the blend | **0.0 to 0.4**; above 0.6 would be exceptional | AQR IR 0.60 gross / about 0.4 net for a diversified index. A concentrated 4–10-name book has higher tracking error, so its IR is lower for the same alpha |
| Absolute Sharpe | **0.3 to 0.7** (market-like) | AQR indices: 0.38–0.40, against 0.24–0.30 for the benchmarks |
| Maximum drawdown over 5 years | **20% to 40%** | Momentum crash history; MDY/IJR fell −42% in 2017–2021. **The 25% kill rule has a material chance of firing even for an arm with a real edge.** |
| Haircut from any in-sample (development) Sharpe | **−50% to −100%** | Suhonen et al.: median −73%; experiment 2: 1.42 became −0.01 |
| Chance of 100%+/yr sustained | **About 0**; no credible systematic record found | Q8 |
| Years to confirm the excess IR at 80% power, one-sided α = 0.10 | IR 0.3 → **50 yrs**; 0.4 → **28**; 0.5 → **18**; 0.6 → **12.5**; 1.0 → 4.5 | T = (2.123 / IR)², the same formula as the draft's power table |

**Bottom line.** The literature supports B1's ingredients (RS and a trend condition), not its exact rules. It predicts a small edge at best, and a 5-year forward test cannot confirm an edge of that size. The most informative additions are:
- a plain-momentum control arm (M), so a null result can be attributed;
- anonymized LLM inputs in arm C;
- writing down now that the most likely verdict at 60 months is INCONCLUSIVE, and that this is not evidence the arms work.

---

## Search gaps and unverified items

- **[NF]** No peer-reviewed tests found of: Minervini SEPA or VCP; the "N-day high on ≥ 1.2× volume" rule; ATR-multiple stops; top-5% versus top-10% momentum.
- **[S] items used for key numbers, to re-check against the papers' tables before any of them is quoted in a report:**
  - George & Hwang's 0.65% vs 0.38% per month;
  - Barroso & Santa-Clara's 0.53 → 0.97 Sharpe;
  - Han, Zhou & Zhu's stop-loss results;
  - Cooper et al.'s +0.93% / −0.37%;
  - Da et al.'s 8.86% / 2.91%.
- **Post-2010 US small/mid-cap momentum:** the Robeco figure could not be verified (404). Compute it from Ken French's data library before relying on it.
- **Lopez-Lira & Tang's venue** (reported as *Journal of Financial Economics*) was not confirmed.
- **Cheh, Kim & Lee (2011) and Najafi & Asgari (2013)** on CAN SLIM are known only secondhand.
