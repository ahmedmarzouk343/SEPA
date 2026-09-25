# Fundamentals Dataset: Final Verification Report (v3, backtest-ready round)

**Generated:** 2026-09-24
**Dataset:** 22,099 quarterly rows, 1,024 tickers. The 6 of 1,030 with no us-gaap XBRL are unchanged: CWEN-A, HLX, LEG, ONON [IFRS], OZK, PFBC.
**Query entry point:** `fundamentals_store.get_known_fundamentals(ticker, as_of_date)`, reading `scaled_fundamentals_parquet/`. Split-adjust with `adjust_eps_for_splits()`.

Every number below comes from a script run against the final dataset.

---

## 1. Verification battery (final run)

| # | Check | v2 | **v3** | Result | Script |
|---|---|---|---|---|---|
| 1 | Missing data | 0.88% | **0.35%** (310 of 88,396) | PASS (≤1%) | `scaled_verification.py` |
| 1a | Missing EPS / missing NI | 490 / 6 | **169 / 6** | see §3 | |
| 1b | Missing values with no specific cause | not tracked | **0 of 310** | PASS | `explain_missing.py` |
| 2 | Duplicate-NI scan | FHN | FHN | Reviewed genuine (3 separate filings) | `scaled_verification.py` |
| 3 | Invalid quarter labels | 0 | **0** | PASS | `scaled_verification.py` |
| 3b | Label steps vs date steps | 22 / 16 tickers | 22 / 16 tickers | All are FY-change / predecessor-stub / 2-row listings | `scan_label_consistency.py` |
| 4 | Gaps | 72 in 64 tickers | 72 in 64 tickers | **All classified**, 0 unexplained | `gap_diagnosis.py` |
| 5 | FY-end month coverage | 12/12 | 12/12 | PASS | `scaled_verification.py` |
| 6 | Checkpoints (BURL, TTEK, CRM) | 9/9 | **9/9** | PASS | `verify_checkpoints.py` |
| 7 | Split suite | 38/38 | **80/80** | PASS | `test_split_adjustment.py` |
| 8 | Sanity rejections | 37 | **18** | nulled + NEEDS_MANUAL_REVIEW | pipeline |
| 9 | Ticker coverage guard | not checked | 1,024 | PASS | pipeline log |

**External spot-checks this round:** 38 values checked against official SEC filings.

| Check | Values | Result |
|---|---|---|
| EPS around new splits | 12 | 11 match. CELH Q4'23 is off, a documented limit (§4) |
| Q4 EPS in split years, after the split-aware fix | 8 | 5 exact, 2 off by $0.01, CHDN off by 2.6%. The pre-fix values matched **0 of 8** |
| Class-level EPS, a new data source | 7 | **7 exact**, including the derived MC Q4'25 |
| Bank composite revenue changes | 4 | **4 exact** (ZION, CATY, BKU, FBP). Old values confirmed as fee sub-lines, e.g. ZION's $163M "customer-related noninterest income" vs the true $861M |
| Filing-anchored split tests | 4 | Exact adjusted values equal what the companies later reported (NLY ×4 confirmed) |

---

## 2. The three items

### 2.1 Splits: 25 verified, 8 rejected (`split_table.csv`)

**Your 13 candidates:**
- **Confirmed from 8-K or 10-K text (10):** ACMR 3, NLY **1/4 (reverse)**, EXLS 5, MLI 2, CELH 3, HUBG 2, PANW 2, CRVL **3** (not 5), MTH 2, RLI 2.
- **Rejected (3):**
  - **AAMI:** a 43% tender-offer buyback, not a reverse split.
  - **CHRD:** the Oasis–Whiting merger.
  - **BBT:** the Berkshire–Brookline reverse acquisition. Filings after the merger present Brookline's history, so treat this series as a discontinuity.

**LXP** (1/5 reverse, Nov 2025) was added from the REIT spot-check.

**Re-running the scanner found 9 more real splits.** It ran on the final data, which now includes class-level EPS, with 2-quarter windows. The 3-quarter windows had missed COKE (one bad row nearby) and LXP (split near the end of the data).
- **NVDA 4:1 (July 2021)** was missing from the original table, so NVDA's pre-2021 EPS would have been mis-adjusted 4×.
- The others: NSSC 2, GME 4, CHDN 2, USLM 5, SMCI 10, COKE 10, PIPR 4, POWL 3.
- Rejected with filings: RBA (acquisition), CRGY (unit conversion + offering), PNFP (holding-company merger), SM (merger), and COKE's 2025 drop (a $2.4B buyback of Coca-Cola Co.'s stake).

**Reverse-split math.** Ratios are stored as exact `Fraction(new, old)`. Adjusting divides by the factor, so a reverse split *multiplies* pre-split EPS. Test 6 checks this explicitly:
- NLY $0.55 → $2.20, which Annaly's own 2023 10-Q confirms.
- LXP ×5 exactly: 1.23 → 6.15. Naive float division would give 6.1499999999999995.
- Lookahead is blocked, and the post-split quarter is unchanged.

**Split dates vs. the data.** Test 7 checks every split against the dataset's own as-filed EPS basis: 24 pass. NLY is covered by the filing anchor instead, because preferred dividends make NI/EPS unusable as a share proxy.

### 2.2 EPS gap: 490 → 169 (NI: 6)

Four fixes, each tied to a traced root cause:

1. **Class-level EPS from each filing's XBRL instance** (`class_eps.py`): 377 periods for 18 dual-class or Up-C tickers (MC, PJT, COKE, ADT, GEF…). SEC companyfacts drops per-class facts. Only as-filed current-period facts are used, and for the class that actually trades. Q4 is derived per class only when the year sits on one dilution basis: RYAN switches between if-converted and anti-dilutive by quarter, which would otherwise produce nonsense.
2. **The 10-K's own filed Q4 EPS** when Q4 shares aren't available (NPK).
3. **Late-filed FY shares**, accepted only if within ±15% of that year's Q1–Q3 shares (SSD, RES, STBA, ALGT).
4. **Next-year comparative EPS** when the original 10-Q didn't tag EPS (BFAM, RCUS). It's used only if the comparative NI equals the as-filed NI, no known split falls between, and implied shares are in line. BANC's merger-restated history is correctly refused.

**Split-year Q4 bug found and fixed along the way.** Q1–Q3 shares filed before a mid-year split were subtracted from post-split FY shares, which corrupted the Q4 EPS of every split year. For example, NVDA Q4 FY22 was $0.68 against an actual **$1.18**. Quarters are now converted onto the FY basis using the verified split table.

**Why EPS can't reach NI's level (169 vs 6).** Every remaining EPS gap has a filing-level cause (`missing_values_explained.csv`):

| Cause | Count |
|---|---|
| Class-level Q4 not derivable: no Q4 in the 10-K, and the year spans mixed dilution bases or a split | 47 |
| No EPS or share count filed anywhere, typically pre-IPO / first-10-K periods where NI exists only as a later comparative | 45 |
| Comparative EPS failed the restatement/split checks | 24 |
| Q4 with no share count and no filed Q4 EPS | 21 |
| Class-level EPS untagged in that filing | 12 |
| Late FY shares inconsistent with Q1–Q3 | 10 |
| Rejected (8 EPS/NI sign conflicts + KGS pre-IPO EPS of $495,550 on ~100 units) | 10 |
| **Total** | **169** |

### 2.3 Unexplained revenue: every missing value now has a specific cause

The four named tickers were all **fixable extraction bugs**, and all four are now **CLEAN**:

| Ticker | Root cause | Fix |
|---|---|---|
| PTGX (8) | 2021–23 10-Qs didn't tag revenue under a standard concept (incl. genuine $0 quarters) | Guarded comparative fallback |
| WTFC (10) | Tags quarterly `Revenues` (= NII + noninterest income) but no annual; stopped tagging in 2025 | All real banks use the composite |
| FLS (3) | FY2023 10-K tags `Revenues` = **$0**; the old data also had **Q1 2025 revenue = $0** | A placeholder zero yields to a later concept's non-zero value |
| FBNC (3) | Annual `Revenues` is a sub-line; its old quarterly revenue was an $864K sub-line | Composite |

**Related changes:**
- The same-concept annual is used only as a Q4 fallback. Using it as an override wrongly changed RCUS Q4'24 (a concept that changed meaning mid-year).
- A derived Q4 on one concept that spikes is *kept and flagged*, not rejected. Examples: PTGX $170.6M, CYTK, VIR, and RCUS Gilead milestones.

**Remaining 135 missing revenue values:**
- 66: no revenue fact filed in any us-gaap concept (company-specific tags such as AMH, or pre-revenue)
- 36: Q4 not derivable (annual missing, restated only, or basis mix)
- 20: only a restated comparative exists
- 8: rejected derived Q4s
- 5: WT tags only a sub-line

**Revenue values changed vs. v2: 363 in 23 tickers.** Nearly all are banks where the old "revenue" was a fee sub-line tagged `Revenues`: CATY about 1/16 of the true figure, BKU about 1/45, FBNC about 1/75. CBSH and FLS had bogus $0 tags. The Q3'25 10-Qs confirm ZION, CATY, BKU and FBP exactly: ZION NII $672M + noninterest income $189M = $861M.

---

## 3. Known limitations (documented, not bugs)

- **Derived Q4 EPS precision.** Q4 EPS = Q4 NI ÷ derived Q4 shares.
  - Usually within $0.01: CRM, MTH, NLY, UBSI.
  - It can be off more when the Q4 dilution method differs from the full year. CELH Q4'23 is $0.15 vs $0.17 (PepsiCo preferred if-converted in Q4 only), and CHDN is 2.6% off (share count moved during the year).
  - Switching to FY EPS − ΣQ EPS would fix CELH but break the verified TTEK checkpoint ($0.36 vs $0.35), so Rule 2 stays.
- **Release dates** for about 988 tickers are SEC filing dates: no lookahead, but 0–3 weeks after the press release.
- **Split-scanner recall.** It can't see splits in loss-making or low-EPS series (|EPS| < $0.25) or within about 2 quarters of the data's end. After the fixes it recovers 24 of the 25 verified splits.
- **Series discontinuities, where a merger replaced the history (not splits):** BBT (2025), BANC (2023 PacWest).

---

## 4. Files

| File | Contents |
|---|---|
| `scaled_fundamentals_parquet/`, `scaled_fundamentals.csv` | Final dataset, with a `notes` audit trail per value |
| `per_ticker_summary.csv` | 1,024 rows: **CLEAN 904 / OK_WITH_KNOWN_GAPS 87 / REVIEW 33**; missing-value causes, gap causes, splits, revenue basis |
| `split_table.csv` | 25 verified splits (accessions) + 8 rejected candidates (what actually happened) |
| `missing_values_explained.csv` | Cause for each of the 310 missing values |
| `class_eps_supplement.json` | 377 class-level EPS values with source accessions (rebuild: `python class_eps.py`) |
| `gap_diagnosis.csv`, `label_inconsistencies.csv`, `split_candidates.csv`, `verification_report.txt`, `split_test_final.log` | Supporting outputs |
