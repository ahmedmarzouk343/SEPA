# Engine fixes from the Minervini comparison: results

Arms frozen in `8acb5ae` before any run. Book-config defaults otherwise. Real bars, costs, and the independent auditor. The 2017-2021 run went once, under its own pushed lock (`c292911` → `fa2a511`).

| Arm | Universe | Fundamentals |
|---|---|---|
| F0 | S&P 400/600 | strict veto (the old engine) |
| F1 | S&P 1500 | strict veto |
| F2 | S&P 1500 | rank only |

## Returns

"Swept" = idle cash held in MDY/IJR.

| Window | Arm | Raw total | Raw CAGR | Swept CAGR | MDY/IJR CAGR |
|---|---|---|---|---|---|
| 2022-2026 | F0 | +6.1% | +1.3% | +6.1% | +6.0% |
| 2022-2026 | F1 | +18.0% | +3.6% | **+10.7%** | +6.0% |
| 2022-2026 | F2 | −5.1% | −1.1% | +4.3% | +6.0% |
| 2017-2021 | F0 | +22.2% | +4.1% | +13.1% | +12.5% |
| 2017-2021 | F1 | +17.6% | +3.3% | +9.8% | +12.5% |
| 2017-2021 | F2 | +17.5% | +3.3% | +10.2% | +12.5% |

No arm beats the index in both periods. F1 wins in 2022-2026 and loses in 2017-2021.

## Did it pick his stocks?

His disclosed BUY/HOLD rows (excluding ETFs) listed as a candidate, or bought, within ±30 days of his date:

| Window | His rows | F0 | F1 | F2 |
|---|---|---|---|---|
| 2017-2021 | 33 | 1 candidate (PAG, bought) | 2 (PAG, PYPL; PAG bought) | 3 (OLN, PAG, PYPL; none bought) |
| 2022-2026 | 44 | 0 | 1 (GOOGL) | 2 (GOOGL, URBN) |

## Why, even after the fixes

Evidence: F2's decision receipts on his buy dates.

1. **The VCP chart-pattern detector rejects his entries.** Among his in-universe buys, the reasons include:
   - "contraction count out of range" (STAA, SKY, MRNA, NUE, SCHW);
   - "monotonicity failed" (GM, AXON, DVA);
   - "no daily base in weekly window" (APP);
   - "awaiting breakout" (PAG);
   - breakout volume below 1.2× (PYPL).

   He reads bases by eye; the mechanical detector accepts far fewer.
2. **The trend template or RS failed on his exact dates:** AAPL, TSLA, CCL, CARR, ANF, MP.
3. **Still outside any universe we have:** NNOX, UAVS, GBOX, ZIM, BNTX, SE, SNAP, SQ, RVLV, UPST, ASYS, SRTS, YELL, LMB, NMM, RNA, TATT. These are small caps, recent IPOs and foreign companies; some are delisted, so there are no free prices.
4. **Fundamentals:** in F2 they no longer veto, so they are not the blocker there. In F0/F1 they were: NVDA, MU, UBER, OLN, NUE, AIG and SCHW failed Q2 or Q4.

## Data checks for the S&P 500 addition

- 475 names added; the 46,471 existing rows are unchanged.
- 105 splits verified against the companies' own restatements.
- Audit of 40 random new-ticker quarters against press releases (`SP500_DATA_AUDIT.md`):
  - 94% of fields match;
  - no lookahead date in the sample;
  - a small class of revised values dated a few days early (about 10-230 of 68,811 rows) is flagged there, with a proposed fix.

## Conclusion

Widening the universe and softening the fundamentals did not make the mechanical system select like Minervini, and it did not produce an edge that holds in both periods.

The remaining gap is chart reading: his discretionary judgment of bases and entries, which our rule-based VCP detector does not reproduce. Every result here also carries survivorship bias (current index members), and a design motivated by his 2021-2026 picks.
