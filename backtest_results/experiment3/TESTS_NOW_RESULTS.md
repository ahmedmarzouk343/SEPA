# Experiment 3 historical tests: results

Arms frozen in `a8ba093` before either run. Real bars, the engine's costs, and the independent auditor, which matched on every arm.

## Test 1: 2024-01-02 .. 2026-09-24 (the owner's request; IN-SAMPLE, because the ideas were derived from 2022-2026)

| Arm | Trades | Raw total | Raw CAGR | Idle cash in MDY/IJR (CAGR) | MDY/IJR (CAGR) |
|---|---|---|---|---|---|
| B1 | 80 | +21.6% | +7.4% | +14.2% | +11.5% |
| B2 | 121 | −8.7% | −3.3% | +7.0% | +11.5% |
| B3 | 116 | −0.4% | −0.2% | +8.1% | +11.5% |
| Experiment 1 frozen | 98 | +9.3% | +3.3% | +14.5% | +11.5% |
| Experiment 2 pick | 44 | +113.9% | +32.2% | +39.0% | +11.5% |

The experiment-2 pick's +113.9% is in-sample: it was chosen on 2022-2026. The same configuration made −3.2% on 2017-2021.

## Test 2 (3a): 2017-01-03 .. 2021-12-31, run once

Lock claimed in `65124cb` and finished in `656d8f6`, both pushed.

| Arm | Verdict | Trades | Raw total | Raw CAGR | Sharpe | Max DD | Idle cash in MDY/IJR (CAGR) | MDY/IJR (CAGR) |
|---|---|---|---|---|---|---|---|---|
| B1 | **KILLED** | 164 | −23.8% | −5.3% | −0.30 | −31.5% | +2.1% | +12.5% |
| B2 | **KILLED** | 171 | −18.7% | −4.1% | −0.19 | −31.8% | +2.5% | +12.5% |
| B3 | **KILLED** | 187 | −7.1% | −1.5% | −0.03 | −32.5% | +4.6% | +12.5% |

With idle cash in the equal-weight member basket, B1, B2 and B3 made +6.0%, +6.1% and +8.3% a year, against +19.9% for the basket.

**Conclusion:** none of the model-book entry ideas survives the period it was not built on. B1 looked best in-sample and was the worst out of sample. This is the fourth fair test of Minervini-style rules in this project, after experiment 1's holdout, experiment 2's validation and this one, and every one fell short of simply holding the index.
