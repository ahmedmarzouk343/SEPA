"""Verify that all binding checkpoint values still pass after pipeline re-run."""
import pandas as pd
from pathlib import Path

SCRATCHPAD = Path(__file__).resolve().parent
CSV = SCRATCHPAD / "scaled_fundamentals.csv"

CHECKPOINTS = [
    {"ticker": "BURL", "quarter": "Q4 2022", "field": "revenue",    "expected": 2_744_283_000},
    {"ticker": "BURL", "quarter": "Q4 2022", "field": "net_income", "expected": 185_200_000},
    {"ticker": "BURL", "quarter": "Q4 2023", "field": "revenue",    "expected": 3_126_358_000},
    {"ticker": "BURL", "quarter": "Q4 2023", "field": "net_income", "expected": 227_458_000},
    {"ticker": "TTEK", "quarter": "Q3 2024", "field": "eps",        "expected": 1.59},
    {"ticker": "TTEK", "quarter": "Q4 2024", "field": "eps",        "expected": 0.35},
    {"ticker": "CRM",  "quarter": "Q4 2025", "field": "revenue",    "expected": 9_993_000_000},
    {"ticker": "CRM",  "quarter": "Q4 2025", "field": "net_income", "expected": 1_708_000_000},
    {"ticker": "CRM",  "quarter": "Q4 2025", "field": "eps",        "expected": 1.76, "tolerance": 0.01},
]


def run():
    df = pd.read_csv(CSV)
    passed = 0
    failed = 0
    results = []

    for cp in CHECKPOINTS:
        mask = (df["ticker"] == cp["ticker"]) & (df["fiscal_quarter"] == cp["quarter"])
        rows = df[mask]
        if rows.empty:
            results.append(f"  FAIL  {cp['ticker']} {cp['quarter']} {cp['field']}: NOT FOUND")
            failed += 1
            continue

        actual = rows.iloc[0][cp["field"]]
        expected = cp["expected"]
        tol = cp.get("tolerance", 0)

        if pd.isna(actual):
            results.append(f"  FAIL  {cp['ticker']} {cp['quarter']} {cp['field']}: NaN (expected {expected})")
            failed += 1
        elif abs(actual - expected) <= tol:
            results.append(f"  PASS  {cp['ticker']} {cp['quarter']} {cp['field']}: {actual} == {expected}")
            passed += 1
        else:
            results.append(f"  FAIL  {cp['ticker']} {cp['quarter']} {cp['field']}: {actual} != {expected}")
            failed += 1

    print("=" * 70)
    print("  CHECKPOINT VERIFICATION")
    print("=" * 70)
    for r in results:
        print(r)
    print(f"\n  {passed}/{passed+failed} passed")
    if failed:
        print(f"  *** {failed} CHECKPOINT(S) FAILED ***")
    else:
        print("  All checkpoints PASS")
    return failed == 0


if __name__ == "__main__":
    ok = run()
    exit(0 if ok else 1)
