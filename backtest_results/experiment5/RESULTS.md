# Experiment 5 (MV1 momentum/volatility breakout): results

**Pre-registered verdict: PASS by the frozen rule.** The strategy beat both MDY/IJR and the median random-breakout portfolio.

**Read it as weak evidence.** The window is contaminated (see the pre-registration), and the margin is inside random variation.

- Run once at commit 2c0fafc. Rules: `PREREGISTRATION.md` (c2e5780); T frozen at fc1d321.
- Raw output: `test_2025_09_2026_09.json`.

## Result: 2025-09-02 to 2026-09-24

993 fresh breakouts in the window; 539 in the top third (score ≥ T).

| Portfolio | Total return | Max drawdown | Trades | Win rate |
|---|---|---|---|---|
| **MV1 primary** (top third, 60-day hold, 6 slots) | **+22.7%** | −26.8% | 30 | 63% |
| MDY/IJR 50/50 (with dividends) | +16.6% | | | |
| Equal-weight current S&P 400/600 | +17.3% | | | |
| Random-priority breakouts, median of 500 | +17.6% (10th–90th percentile: +6.5% to +30.3%) | | | |
| Variant: + 8% stop | **−7.8%** | −22.0% | 68 | 25% |
| Bottom third, same rules | +3.0% | −13.5% | 27 | 48% |

Decision rule: +22.7% > +16.6% (index) **and** > +17.6% (null median). **PASS.**

## Why this is weak evidence

1. **Contaminated window.** The clue was found in part on these months, as the pre-registration states.
2. **Inside the noise.** The strategy ranks at the **68th percentile** of 500 random breakout portfolios: 32% of random picks did better, so p ≈ 0.32. Thirty trades in 6 slots are too few to separate skill from luck.
3. **It does not survive a normal stop.** With an 8% stop it lost 7.8%. These volatile names are shaken out before they run, as the model-book README warned.
4. **The previous year disagrees.** On the mechanics rehearsal (Sept 2024 – Aug 2025, development data, in-sample for the ranking model), the same rules made **−0.9% vs +8.0%** for the index, with a 40% drawdown. That drawdown came from cohort risk: the slots fill in bursts, so six positions that entered in December 2024 all lost 28–44% together.
5. **Survivorship.** The universe is current index members. This flatters the strategy against the index, but not against the random-priority null, which uses the same universe.

**The one consistent sign:** the ranking's order held. Top third +22.7% vs bottom third +3.0% here; mean trade +1.9% vs −0.0% on the rehearsal. That matches the signal-level finding (AUC 0.80), but a portfolio of this size is too small to prove it.

## What the rule says next

A PASS on this window means only "worth a clean test".
- The clean test is **Jul 2015 – Dec 2016**, which no experiment has touched. Price data starts 2014-06, and the trend filters need about a year of history.
- It would use the **same frozen rules**: model, T, 6 slots, 60-day hold, costs.
- It would need the model-book breakout flags recomputed for 2015–2016.
- If it also passes, the next step would be a forward paper test. It would not be real money.
