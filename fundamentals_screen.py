"""
Fundamentals screen — the 4-question screen. This is the ONLY fundamentals
result the pipeline uses.

The legacy composite scoring system (BASE_WEIGHTS / compute_composite /
score_earnings_growth / score_code_33 / compute_peg_modifier /
compute_deceleration_penalty / renormalize_weights and friends) was REMOVED,
not shadowed. It ran in parallel with this screen and disagreed with it:
COMI returned pass=True here and pass=False at composite 25.0 at the same
time, on the same data. Two fundamentals verdicts for one ticker is a bug,
so the invented-weights path is gone. See kashif-implementation-plan.md
Category A.

Questions (feature-02-fundamentals-screen-rules.md, ch07-notes.md):
  Q1 EPS growth >= 20% YoY (turnaround: >= 100%).            Required.
  Q2 Earnings acceleration on a 2-QUARTER ROLLING AVERAGE.   Deceleration FAILS.
  Q3 Revenue growing YoY.                                    Skipped if no data.
  Q4 Annual EPS growing YoY.                                 Skipped if no data.

PASS = Q1 AND (Q2 PASS|SKIP) AND (Q3 PASS|SKIP) AND (Q4 PASS|SKIP).
"""

EPS_GROWTH_THRESHOLD = 0.20        # Q1, ch07 "20-25% minimum"
TURNAROUND_THRESHOLD = 1.00        # Q1, turnaround category
Q2_ROLLING_WINDOW = 2              # A1: 2-quarter rolling average
BREAKOUT_YEAR_LOOKBACK = 3         # A3: "multi-year (2-4yr) range"


def _mean(values):
    return sum(values) / len(values)


def evaluate_fundamentals(fund_data, category=None):
    """
    4-question fundamentals screen. `fund_data` is the dict produced by
    fundamentals_fetcher.fetch_fundamentals().

    Quarterly lists are oldest-first, so [-1] is the most recent quarter.
    """
    eps = fund_data.get("eps_yoy_growth_by_quarter")
    revenue = fund_data.get("revenue_yoy_growth_by_quarter")
    annual_eps = fund_data.get("annual_eps_by_year")

    if not eps:
        return {
            "pass": False,
            "q1": {"status": "SKIPPED", "reason": "No EPS data available"},
            "q2": {"status": "SKIPPED", "reason": "No EPS data available"},
            "q3": {"status": "SKIPPED", "reason": "No EPS data available"},
            "q4": {"status": "SKIPPED", "reason": "No EPS data available"},
            "overall_reason": "No EPS data available",
        }

    # ---------------- Q1 — EPS growth threshold (required) ----------------
    latest_eps = eps[-1]
    threshold = TURNAROUND_THRESHOLD if category == "turnaround" else EPS_GROWTH_THRESHOLD
    q1_pass = latest_eps >= threshold
    cmp = ">=" if q1_pass else "<"
    q1 = {
        "status": "PASS" if q1_pass else "FAIL",
        "value": latest_eps,
        "threshold": threshold,
        "reason": f"EPS growth {latest_eps*100:.1f}% {cmp} {threshold*100:.0f}% threshold",
    }

    if not q1_pass:
        return {
            "pass": False,
            "q1": q1,
            "q2": {"status": "NOT_EVALUATED", "reason": "Q1 failed"},
            "q3": {"status": "NOT_EVALUATED", "reason": "Q1 failed"},
            "q4": {"status": "NOT_EVALUATED", "reason": "Q1 failed"},
            "overall_reason": f"Q1 FAIL: EPS growth {latest_eps*100:.1f}% < {threshold*100:.0f}%",
        }

    # ------- Q2 — acceleration on a 2-quarter rolling average (A1/A2) -----
    # Needs 3 quarters minimum: avg_recent uses [-1],[-2]; avg_prior uses
    # [-3],[-4], falling back to [-3] alone when only 3 quarters exist.
    # A single volatile quarter can no longer flip this either way, and a
    # material slowdown now FAILS rather than being ignored (ch07: "material
    # slowdown in growth rate is a real warning sign").
    # Needs 4 quarters: avg_recent = mean(eps[-1], eps[-2]),
    # avg_prior = mean(eps[-3], eps[-4]). At 3 quarters avg_prior would be a
    # single quarter, which is exactly the volatile single-quarter comparison
    # A1 exists to remove — so 3 SKIPS rather than half-applying the rule.
    if len(eps) < 2 * Q2_ROLLING_WINDOW:
        q2 = {
            "status": "SKIPPED",
            "reason": (f"Only {len(eps)} quarter(s) available — need "
                       f"{2 * Q2_ROLLING_WINDOW} for two full rolling averages"),
        }
        q2_ok = True
    else:
        recent_window = eps[-Q2_ROLLING_WINDOW:]
        prior_window = eps[-(2 * Q2_ROLLING_WINDOW):-Q2_ROLLING_WINDOW]
        avg_recent = _mean(recent_window)
        avg_prior = _mean(prior_window)
        q2_pass = avg_recent > avg_prior
        q2 = {
            "status": "PASS" if q2_pass else "FAIL",
            "avg_recent": avg_recent,
            "avg_prior": avg_prior,
            "recent_window": recent_window,
            "prior_window": prior_window,
            "reason": (
                f"2q rolling avg {avg_recent*100:.1f}% "
                f"{'>' if q2_pass else '<='} prior 2q avg {avg_prior*100:.1f}%"
                f"{'' if q2_pass else ' — DECELERATING'}"
            ),
        }
        q2_ok = q2_pass

    # ---------------- Q3 — revenue confirmation ----------------
    if revenue is None or len(revenue) == 0:
        q3 = {"status": "SKIPPED", "reason": "Revenue data unavailable"}
        q3_ok = True
    else:
        latest_rev = revenue[-1]
        q3_pass = latest_rev > 0
        q3 = {
            "status": "PASS" if q3_pass else "FAIL",
            "value": latest_rev,
            "reason": f"Revenue growth {latest_rev*100:.1f}% {'>' if q3_pass else '<='} 0%",
        }
        q3_ok = q3_pass

    # ---------------- Q4 — annual EPS growing YoY (A3) ----------------
    # annual_eps_by_year is oldest-first absolute EPS per fiscal year.
    # Unavailable data SKIPS (never fails) — most tickers have it, but the
    # screen must not reject a stock purely for a gap in the annual feed.
    breakout_year = False
    if not annual_eps or len(annual_eps) < 2:
        q4 = {
            "status": "SKIPPED",
            "reason": "Annual EPS data unavailable (need 2+ fiscal years)",
        }
        q4_ok = True
    else:
        current_year, prior_year = annual_eps[-1], annual_eps[-2]
        q4_pass = current_year > prior_year
        if prior_year != 0:
            growth_pct = (current_year - prior_year) / abs(prior_year) * 100
            growth_txt = f"{growth_pct:+.1f}%"
        else:
            growth_txt = "n/a (prior year 0)"
        # BREAKOUT_YEAR: current fiscal year above the prior 3-year high.
        prior_window = annual_eps[-(BREAKOUT_YEAR_LOOKBACK + 1):-1]
        if prior_window and current_year > max(prior_window):
            breakout_year = True
        q4 = {
            "status": "PASS" if q4_pass else "FAIL",
            "current_year": current_year,
            "prior_year": prior_year,
            "breakout_year": breakout_year,
            "reason": (
                f"Annual EPS {current_year:.4g} vs {prior_year:.4g} ({growth_txt})"
                + (" — BREAKOUT_YEAR" if breakout_year else "")
            ),
        }
        q4_ok = q4_pass

    overall_pass = q1_pass and q2_ok and q3_ok and q4_ok
    overall_reason = (
        f"Q1={q1['status']}, Q2={q2['status']}, Q3={q3['status']}, Q4={q4['status']}"
    )
    if breakout_year:
        overall_reason += " [BREAKOUT_YEAR]"

    return {
        "pass": overall_pass,
        "q1": q1,
        "q2": q2,
        "q3": q3,
        "q4": q4,
        "breakout_year": breakout_year,
        "overall_reason": overall_reason,
    }
