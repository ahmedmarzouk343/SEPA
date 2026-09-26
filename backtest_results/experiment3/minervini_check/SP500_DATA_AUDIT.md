# S&P 500 fundamentals audit: 40 random quarters vs the companies' own press releases

Audited 2026-09-26 by an independent auditor, working read-only. The store checked is `us_fundamentals/scaled_fundamentals.csv`, written 2026-09-26 18:04 with 68,811 rows. `kashif_data/apply_8k_sp1500.log` for that build says: "rows 68811; release date moved to the 8-K 2.02 date on 43768 (63.6%)".
The row-level results are in `sp500_data_audit.csv`, in the same folder. It has 160 rows: 40 quarters × 4 fields.

## Lookahead

**Sample (40 quarters): no lookahead.** No stored `earnings_release_date` is earlier than the press release.
- 38 of 40 dates equal the press-release date or the day EDGAR accepted its 8-K.
- The other 2 are late. Late dates are conservative, so they cannot leak future data.
- No stored value turned out to be a later restatement dated at the original release.

**Store-wide checks on the 22,340 new-ticker rows:**
- 0 rows are dated earlier than 7 days after the quarter end.
- 0 rows are dated after their own SEC filing.

**One minor lookahead mechanism exists outside the sample. It is rare and small, but it is real:**
- **The mechanism.** Some rows take a value from a later filing, such as a 10-K comparative or a later 10-Q. The pipeline then sets that row's SEC date to the later filing. The 8-K step moves the date back to the latest Item 2.02 8-K within 60 days before that filing. That 8-K is usually the press release for a *later* quarter.
- **When it leaks.** If the later filing restated the value and the borrowed release did not print it, the row becomes visible before its value was public.
- **Scale.** 973 new-ticker rows (4.4%) are dated this way: 8-K sourced and more than 100 days after quarter end. Store-wide the count is 3,741 rows (5.4%). The borrowed 8-K comes 0 to 59 days before the filing that holds the value (median 5 days store-wide, 11 for the new tickers).
- **Probe of 20 such rows (2016+, seed 21):**

| Result | Rows | What it means |
|---|---|---|
| NI/EPS equal the first-filed values | 13 | Harmless, just late |
| Revised value, but the borrowed release printed it | 2 | BX 1Q'16 NI 159,753K and NEE Q2'18 EPS 1.61. Not lookahead |
| Dated on the day of the filing that holds the value | 3 | NI (NiSource), NOC, REG. Not early |
| No data (pre-IPO) | 1 | MRNA |
| **Confirmed lookahead** | **1** | **CPAY Q2 2016** |

- **The confirmed case, CPAY Q2 2016.** Stored NI is 116.253M, the revised figure first filed in the Q3 10-Q on 2016-11-09. The original was 114.185M. The row is dated 2016-11-01, the Q3 press release, which does not contain the Q2 number. So the value is visible 8 days early; it is 1.8% higher, and EPS is unchanged at 1.21.
- **Estimated extent.** About 5% of the 973 rows (95% CI 1–24%), so roughly 10 to 230 new-ticker rows. Each is early by 59 days at most, and each is a quarter that is already about a year old. The probe checked NI and EPS only, not revenue.
- **Suggested fix.** Only move a row's date to an 8-K if it is that quarter's own release: the first 2.02 after quarter end and before the next quarter end + 7 days. Otherwise keep the date of the filing the value came from.

## Match rates

Tolerances: EPS ±$0.01. Revenue and net income ±0.5%. The date must equal the press-release date, the 8-K filing or acceptance day, or be at most 1 day later.

| Field | Match | Rate (95% Wilson CI) | Exact |
|---|---|---|---|
| EPS (GAAP diluted) | 36 / 39 (+1 n/a: LYV Q4 EPS not in the release) | 92.3% (79.7–97.3%) | 32 / 39 |
| Revenue | 38 / 40 | 95.0% (83.5–98.6%) | 37 / 40 (JKHY off by $1K on a derived Q4) |
| Net income | 38 / 40 | 95.0% (83.5–98.6%) | 38 / 40 |
| Earnings release date | 38 / 40 | 95.0% (83.5–98.6%) | 0 early, 2 late |
| **All fields** | **150 / 159** | **94.3% (89.6–97.0%)** | |

- **Non-Q4 quarters (26):** 100/104 fields match. Three misses are values the store is *missing*, not wrong: HSY EPS, APTV revenue and IBKR revenue. The fourth is IBKR NI, which is on a different definition. No non-Q4 value is wrong and no date is off.
- **Fiscal-Q4 quarters (14):** 50/55 fields match. Q4 is derived as FY minus 9-month YTD. All 3 wrong values in the sample and both late dates are Q4 rows (CI, MRNA, DASH).
- 4 more Q4 EPS values (ZBRA, TECH, LOW, IDXX) are exactly 1 cent below the reported figure. That is inside tolerance, but it shows the derived Q4 share counts are imprecise.

## Mismatch classes (9 mismatches)

| Class | Count | Examples |
|---|---|---|
| **Q4 derivation** | 3 | **CI Q4'18 NI** 153M vs 144M reported (+6.3%). The FY figure is ProfitLoss (2,646M, including $9M noncontrolling interest) because the FY2018 10-K does not tag NetIncomeLoss, but the 9-month figure is the attributable 2,493M. That mixes two bases. **CI Q4'18 EPS** 0.58 vs 0.55 is the same error carried through; the 10-K itself tags Q4 diluted EPS 0.55. **MRNA Q4'21 EPS** 11.35 vs 11.29: NI 4,868M is right, but the derived Q4 diluted share count is ~428.9M against 431M reported. |
| **Missing value** | 3 | **HSY EPS**: dual-class (Common / Class B) EPS is never extracted, so all 42 HSY quarters since 2016 have no EPS. Store-wide, 9 new tickers have no EPS at all since 2016: ARES, BRK-B, ERIE, FDXF, HONA, HSY, KKR, STZ, V. **APTV revenue**: 2016–17 revenue is tagged `SalesRevenueGoodsNet`, which is not in `REV_CONCEPTS`, so 7 quarters are empty. **IBKR revenue**: 16 quarters (2016–19) are empty. The likely cause is that IBKR's `NoninterestIncome` tag triggers the bank rule (NII + noninterest income), which finds no inputs. The filed revenue (507M gross, 489M net) is ignored. |
| **Definitional (NI basis)** | 1 | **IBKR Q1'16 NI** 310M vs 33M. The store uses ProfitLoss, which includes the ~90% noncontrolling interest, because NetIncomeLoss is not tagged. The project's own definition is NI attributable to the parent. EPS (0.51) is correct. The whole IBKR NI series is on the including-NCI basis. |
| **Late date (conservative)** | 2 | **CI Q4'18**: stored 2019-02-28 (the 10-K) vs the 2019-02-01 release. EDGAR indexes the results 8-K (0000950159-19-000028) as Items 2.01, 9.01, although its text says Item 2.02, so the 2.02 filter misses it. **DASH Q4'25**: stored 2026-05-06 vs the 2026-02-18 release. The FY2025 10-K/A, filed 2026-05-06 with identical numbers, replaced the original 10-K date. The 8-K step then matched the Q1-2026 release, filed the same day. That is 77 days late. |
| Early date (lookahead) | 0 | — |
| Restatement / units error | 0 | — |

## Other notes

- **The first Item 2.02 8-K is not always the results release.** 3 of 40 quarters had something else first:
  - MRNA 2022-01-04 was a preliminary shareholder letter, followed by a JPM conference release on 2022-01-10.
  - HIG 2021-04-16 was the Boy Scouts settlement and catastrophe-loss pre-announcement.
  - For CI, the first 8-K indexed as 2.02 is the *next* quarter's release.
  - The store's "latest 2.02 before the 10-Q/10-K" rule picked the full release correctly for MRNA and HIG. Values above were read from the full results release.
- **Some releases don't show the needed GAAP line.**
  - PRU's EX-99.1 has no GAAP total revenues. GAAP 20,480M comes from the same 8-K's EX-99.2 reconciliation; the 21,611M there is the non-GAAP adjusted-operating-income basis. The store has the GAAP figure. I first misread 21,611 and corrected it.
  - LYV's Q4 release gives Q4 revenue but only full-year NI and EPS. I checked Q4 NI as FY minus 9 months from the Q3 release: −210.7M, which matches. Q4 EPS is not disclosed. The value implied by the release, about −1.25, differs from the stored −1.33 (low confidence).
- **Net income basis:** before preferred dividends, per the project definition (HIG 249M; 244M available to common). ALB's reported (0.00) is stored as 0.0.
- **52/53-week quarter ends** (ULTA, TDG, HSY, TEL, SNDK, SBUX, STX, AMAT, LOW, NXPI, KVUE) all matched the stored `quarter_end_date` exactly.

## Method

- **Universe.** The 475 new tickers = `kashif_data/sp500_members.json["sp500"]` minus `us_fundamentals/sp_universe.json` sp400 + sp600 + existing.
- **Sample.** I shuffled the tickers with `random.Random(21)` and took 40 distinct tickers, with one quarter each. Every third pick (14 of 40) was drawn from the ticker's 10-K period ends (fiscal Q4), and the rest from 10-Q period ends. Quarter ends were limited to 2016-01 to 2025-12 and taken from EDGAR `reportDate`. No ticker was skipped.
- **Source.** For each quarter I took the first 8-K with Item 2.02 filed after quarter end, from EDGAR submissions, and read its EX-99.1 (EX-99 or EX-99.2 where noted). If that 8-K was not the results release, I read the actual results release and recorded both.
- **What was recorded.** GAAP diluted EPS, total revenue (bank and broker bases noted), net income attributable to the parent, and the release dateline, all read by hand from the release tables.
- **SEC access.** Merged-pipeline user agent, at most 4 requests per second, about 330 requests in total.
- **Scratch files.** `%TEMP%\claude\...\scratchpad\sp500_audit\`: `sample.json`, `source_values.py`, `docs/`, `text/`, `compare_csv.json`, `borrowed_check.json`.

## Sample

| # | ticker | quarter end | fiscal Q4? | release date | 8-K accession read | first 2.02 after QE (if different) |
|---|---|---|---|---|---|---|
| 1 | CI | 2018-12-31 | yes | 2019-02-01 | 0000950159-19-000028 | EDGAR index: 0000950159-19-000073 (2019-05-02, the Q1-2019 release); the release read is mis-indexed as Items 2.01,9.01 |
| 2 | HPE | 2022-01-31 |  | 2022-03-01 | 0001645590-22-000010 |  |
| 3 | PPG | 2021-03-31 |  | 2021-04-15 | 0000079879-21-000020 |  |
| 4 | ZBRA | 2020-12-31 | yes | 2021-02-11 | 0000877212-21-000006 |  |
| 5 | NXPI | 2023-10-01 |  | 2023-11-06 | 0001413447-23-000105 |  |
| 6 | EFX | 2017-09-30 |  | 2017-11-09 | 0000033185-17-000033 |  |
| 7 | JKHY | 2016-06-30 | yes | 2016-08-16 | 0000779152-16-000138 |  |
| 8 | ULTA | 2017-04-29 |  | 2017-05-25 | 0001193125-17-183714 |  |
| 9 | CTAS | 2018-08-31 |  | 2018-09-25 | 0000723254-18-000026 |  |
| 10 | TECH | 2021-06-30 | yes | 2021-08-05 | 0001437749-21-018609 |  |
| 11 | JBL | 2021-11-30 |  | 2021-12-16 | 0001193125-21-358576 |  |
| 12 | TPL | 2022-06-30 |  | 2022-08-03 | 0001811074-22-000050 |  |
| 13 | LH | 2022-12-31 | yes | 2023-02-16 | 0000920148-23-000012 |  |
| 14 | CMS | 2018-03-31 |  | 2018-04-26 | 0001104659-18-026879 |  |
| 15 | KVUE | 2024-03-31 |  | 2024-05-07 | 0001944048-24-000096 |  |
| 16 | LOW | 2024-02-02 | yes | 2024-02-27 | 0000060667-24-000012 |  |
| 17 | DDOG | 2024-03-31 |  | 2024-05-07 | 0001561550-24-000048 |  |
| 18 | TDG | 2016-07-02 |  | 2016-08-09 | 0001260221-16-000074 |  |
| 19 | ABBV | 2021-12-31 | yes | 2022-02-02 | 0001551152-22-000003 |  |
| 20 | ADI | 2024-08-03 |  | 2024-08-21 | 0000006281-24-000158 |  |
| 21 | GEHC | 2024-03-31 |  | 2024-04-30 | 0001932393-24-000033 |  |
| 22 | MRNA | 2021-12-31 | yes | 2022-02-24 | 0001193125-22-051058 | 0001682852-22-000004 (2022-01-04) |
| 23 | HSY | 2021-07-04 |  | 2021-07-29 | 0000047111-21-000043 |  |
| 24 | APTV | 2016-06-30 |  | 2016-08-03 | 0001521332-16-000112 |  |
| 25 | CCI | 2021-12-31 | yes | 2022-01-26 | 0001051470-22-000009 |  |
| 26 | TEL | 2022-06-24 |  | 2022-07-27 | 0001558370-22-011089 |  |
| 27 | SNDK | 2025-10-03 |  | 2025-11-06 | 0001628280-25-050180 |  |
| 28 | DASH | 2025-12-31 | yes | 2026-02-18 | 0001792789-26-000012 |  |
| 29 | DD | 2024-06-30 |  | 2024-07-31 | 0001666700-24-000028 |  |
| 30 | PRU | 2022-09-30 |  | 2022-11-01 | 0001137774-22-000106 |  |
| 31 | AMAT | 2018-10-28 | yes | 2018-11-15 | 0000006951-18-000032 |  |
| 32 | IBKR | 2016-03-31 |  | 2016-04-19 | 0001381197-16-000060 |  |
| 33 | SBUX | 2023-07-02 |  | 2023-08-01 | 0000829224-23-000042 |  |
| 34 | STX | 2021-07-02 | yes | 2021-07-21 | 0001137789-21-000041 |  |
| 35 | HIG | 2021-03-31 |  | 2021-04-22 | 0000874766-21-000043 | 0000874766-21-000027 (2021-04-16) |
| 36 | NOC | 2021-03-31 |  | 2021-04-29 | 0001133421-21-000028 |  |
| 37 | IDXX | 2018-12-31 | yes | 2019-02-01 | 0001144204-19-004216 |  |
| 38 | ALB | 2025-03-31 |  | 2025-04-30 | 0000915913-25-000081 |  |
| 39 | FAST | 2025-03-31 |  | 2025-04-11 | 0000815556-25-000079 |  |
| 40 | LYV | 2023-12-31 | yes | 2024-02-22 | 0001335258-24-000015 |  |
