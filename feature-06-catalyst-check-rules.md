# Kashif — Engineering Rules: Catalyst Check (Feature 6)

*Source of truth for Claude Code on this feature. Supersedes verbal instructions
given in chat — if chat and this file disagree, this file wins until it's
explicitly updated. Living document.*

**Status:** Ready to build. The rubric (v0.3), method priority, worked examples,
and edge case rules are all already specified in the JSON — this feature's design
work was done in a prior session through live testing on 15 real EGX tickers.
The gap is purely implementation: turning the JSON's documented rubric into a
.py file. The model/provider decision (Claude Haiku 4.5 vs Google AI Studio) is
explicitly deferred — build the scoring logic first, wire the model second.

---

## 0. What this feature is

Catalyst check is SEPA element 3: after a stock passes the Trend Template
(Feature 1), Fundamentals Screen (Feature 2), and Market Regime Gate (Feature 3),
and before entry timing (Feature 5), it must have a real, identifiable reason
for moving. Not just good numbers — a specific event (contract, approval,
earnings beat, index inclusion) that explains WHY this stock is likely to
continue moving.

Two outputs:
- `catalyst_score`: STRONG_POSITIVE / NEUTRAL / STRONG_NEGATIVE
- `catalyst_rationale`: source + date + 1-sentence explanation

STRONG_NEGATIVE is the only score that blocks entry — it gates the pipeline.
NEUTRAL does not block entry but reduces `vcp_quality_score` weighting in the
Scoring Queue. STRONG_POSITIVE boosts it.

Catalyst check is NEVER a hard buy signal by itself — it only informs
`ai_synthesis`. A stock can have a STRONG_POSITIVE catalyst and still fail
entry timing. A NEUTRAL catalyst doesn't disqualify a strong VCP setup.

---

## 1. Source of truth

1. `minervini_sepa_v1_strategy_config.json` → `catalyst_check` block (full rubric,
   worked examples, method priority, edge case rules) — read every field, the
   rubric is already complete at v0.3
2. `MANIFESTO.md` Part 3 (SEPA element 3)
3. `ch06-notes.md` — catalyst types, sector leadership rotation context

---

## 2. Architecture — two independent stages, model call is last

```
Stage A (deterministic, zero AI cost):
  fetch_arabfinance_disclosures(ticker) → timing + category tag only
  apply_category_priority_layer(disclosures) → HIGH / MEDIUM / LOW priority
  
Stage B (news search, both languages):
  search_news(ticker, arabic_name, window_days=90) → article list
  
Stage C (model call — deferred, pluggable):
  score_with_model(ticker, disclosures, articles, rubric) → STRONG_POSITIVE /
    NEUTRAL / STRONG_NEGATIVE + rationale
  
Stage D (deterministic, zero AI cost):
  log_to_track_record(ticker, date, score, source, rationale)
```

Stage A runs first and cheapest. LOW-priority disclosures only (Trading, General)
get scored NEUTRAL automatically without reaching Stage C — zero model tokens
spent on routine trading notices. Only HIGH/MEDIUM priority disclosures + any
news surfaced in Stage B reach the model.

Stage C is a pluggable function stub in v1 — the rest of the pipeline works
without it. When the model decision is made, fill in the stub. Until then,
LOW-priority tickers auto-score NEUTRAL, HIGH/MEDIUM-priority tickers auto-score
NEUTRAL with a `"pending_model_review": true` flag in the output.

---

## 3. Stage A — ArabFinance disclosure fetch

Already confirmed working in prior testing. Method:

```python
def fetch_arabfinance_disclosures(ticker, window_days=90):
    """
    Fetch from ArabFinance companyprofiledisclosures?key={TICKER}.
    Returns list of {date, category, title} — TIMING and CATEGORY only.
    Do NOT attempt to fetch PDF content — confirmed blocked (see JSON
    pdf_path_status). Use date and category as clues for news search only.
    """
```

Category priority mapping (from JSON `category_priority_layer`):
- HIGH: FinancialResults, FinancialStatements, Corporate
- MEDIUM: Shareholding, GeneralAssemblies, Listing
- LOW: Trading, General → auto-score NEUTRAL, skip to Stage D

**Single point of failure warning** (from JSON `known_dependency_risk`):
ArabFinance is the ONLY confirmed working disclosure source. If it changes
structure or blocks scraping, there is no backup. Handle HTTP errors and
structure changes gracefully — return empty list, do not crash the pipeline.
Log the failure in the Decision Receipt.

**ArabFinance re-verification needed** (from JSON): ArabFinance has NOT been
re-verified with a full JS browser execution test. Handle it defensively —
same standard as Mubasher.

---

## 4. Stage B — news search, both languages

This is the only way to find externally-originated catalysts (index inclusion,
analyst rating changes, credit agency actions) — confirmed by exhaustive test
on ETEL's full 494-item disclosure history (zero hits for its FTSE Russell
inclusion via any disclosure feed). News search is NOT a fallback for this
category — it is the ONLY possible path.

```python
def search_news(ticker, company_arabic_name, window_days=90):
    """
    Always run BOTH: English search (ticker name) AND Arabic search
    (company_arabic_name + أخبار/إعلان). Never treat Arabic as a fallback.
    
    From JSON: Arabic search surfaced genuine catalysts (credit rating upgrade,
    67.8% acquisition) completely absent from English results, in 2 of 3 test
    cases. OCDI is the clearest proof: English alone found a stale FY2025 
    +77% figure and would have scored FALSE POSITIVE. Arabic found the real
    H1 2026 -35.7% result.
    """
```

Window: trailing 90 days (from JSON `scoring_window_rule`). A catalyst outside
90 days may be cited as SUPPORTING CONTEXT ONLY if there is also an in-window
follow-through item — never as the sole basis for a score.

---

## 5. Stage C — model call (pluggable stub in v1)

The scoring rubric, worked examples, and all edge case rules live in the JSON.
They must be packaged into the model prompt as a system message, not regenerated
each time — this is what makes prompt caching effective on the fixed portions.

```python
def score_with_model(ticker, disclosures, articles, rubric_text):
    """
    MODEL CALL — DEFERRED. Return stub for now.
    
    When implemented, this function must:
    1. Package rubric_text (the full JSON scoring_rubric, serialized to text)
       as the system message — fixed, cacheable
    2. Package ticker + disclosures + articles as the user message — variable
    3. Request output in this exact format:
         SCORE: [STRONG_POSITIVE|NEUTRAL|STRONG_NEGATIVE]
         SOURCE: [source name, date]
         RATIONALE: [1 sentence, including P&L line and reporting basis when
                     profit figures are cited]
    4. Parse response — extract score, source, rationale
    5. Handle failure cases: model unavailable, malformed output → NEUTRAL
       with error flag, never crash the pipeline
    
    Model choice (deferred): Claude Haiku 4.5 (prompt caching + Batch API
    already planned) OR Google AI Studio (Considerations.md proposal).
    This function is the only place that needs to change when the decision
    is made.
    """
    return {
        "score": "NEUTRAL",
        "source": "pending_model_review",
        "rationale": "Model not yet wired — auto-NEUTRAL pending implementation",
        "pending_model_review": True
    }
```

**Critical — rubric enforcement in the prompt**: the model must be told it can
ONLY output one of the three categories (STRONG_POSITIVE, NEUTRAL, STRONG_NEGATIVE)
with source and rationale. No free-form opinions. No buy/sell recommendations.
The same rule that applies to every other AI-scored step in this project.

---

## 6. Stage D — track record logging

This was designed but never built (`"not_yet_built": true` in JSON). It must
be built alongside the scoring function — not as a later addition. Missing the
first real entries defeats the purpose of having a track record at all.

```python
def log_to_track_record(ticker, date, score, source, rationale,
                        forward_return_days=[10, 20, 60]):
    """
    Append to catalyst_track_record.jsonl — one JSON line per call.
    
    Fields logged immediately:
      ticker, date, score, source, rationale, pipeline_run_id
    
    Fields populated later (backfill job, separate script):
      forward_return_10d, forward_return_20d, forward_return_60d
      — these can only be filled in after the time has elapsed
    
    File: catalyst_track_record.jsonl (append-only, never overwrite)
    Location: same output directory as Decision Receipts
    
    Review cadence (from JSON): at each graduation_criteria checkpoint,
    check whether STRONG_POSITIVE scores are associated with better forward
    returns than NEUTRAL scores. If not, the rubric needs revision.
    """
```

The backfill script that populates forward returns is a separate deliverable
(call it `backfill_catalyst_returns.py`) — it reads the track record, looks up
price at score date + N days via yfinance, and writes the return fields back.
This separation is intentional: the main pipeline never looks up future prices
(lookahead bias), the backfill only runs as a periodic reporting job.

---

## 7. Edge case rules — all from the JSON, must be implemented

These are rules discovered from live testing, not theory. Each has a named rule
and at least one worked example in the JSON. Implement them as named functions
or explicit checks, not buried in the model prompt:

**`reporting_basis_conflict_rule`**: Egyptian disclosures routinely show both
standalone and consolidated profit, sometimes with conflicting YoY directions.
When both bases are present and disagree in direction: score NEUTRAL, state both
figures explicitly. Do not pick one basis to force a strong score.

**`source_reconciliation_rule`**: two sources showing different numbers for the
"same" metric can both be correct if they're citing different P&L lines (net
income after tax & minority interest vs. net operating profit). Before treating
as a contradiction: identify which named P&L line each figure refers to. Only
a genuine conflict if the SAME named line differs across sources.

**`debunked_rumor_rule`**: if a news item is a company's DENIAL of a negative
rumor, score based on the resolution (net-neutral/reassuring), not the rumor's
surface framing. ORWE is the reference case: a headline about "reducing US
operations" was actually a denial of that rumor — scoring on keywords alone
would have produced a false STRONG_NEGATIVE.

These three rules are pre-processing logic that runs BEFORE the model sees the
content — the model should receive already-interpreted context where possible,
not raw headlines that might trigger the debunked-rumor or basis-conflict traps.

---

## 8. Output format

Every `catalyst_check()` call returns:

```python
{
    "ticker": str,
    "date": str,                     # ISO format
    "score": str,                    # STRONG_POSITIVE | NEUTRAL | STRONG_NEGATIVE
    "source": str,                   # "Source Name, YYYY-MM-DD"
    "rationale": str,                # 1 sentence
    "disclosure_category": str,      # ArabFinance category or "externally_originated"
    "priority_tier": str,            # HIGH | MEDIUM | LOW | EXTERNAL
    "pending_model_review": bool,    # True if model stub not yet wired
    "scoring_window_days": int,      # 90
    "pipeline_blocks_entry": bool    # True only if score == STRONG_NEGATIVE
}
```

`pipeline_blocks_entry` is the only field that KashifStrategy reads to gate
entry. Everything else flows to Decision Receipts and track record logging.

---

## 9. Testing standard

Catalyst check cannot be tested with pure known-answer fixtures the way Features
1–5 were — the model call is non-deterministic and the news content changes over
time. Testing is structured differently:

**Deterministic fixtures (standard known-answer discipline):**
- Fixture 1: ArabFinance category routing — a LOW-priority disclosure (category
  = "Trading") must score NEUTRAL without reaching Stage C. Confirm Stage C
  never called (zero model calls).
- Fixture 2: 90-day window enforcement — a disclosure dated 95 days ago must
  not qualify as the primary trigger. One dated 89 days ago must qualify.
- Fixture 3: reporting_basis_conflict_rule — feed two articles with conflicting
  standalone vs. consolidated YoY directions. Score must be NEUTRAL regardless
  of which direction either basis shows individually.
- Fixture 4: debunked_rumor_rule — feed an article whose headline contains
  negative language but whose content is a denial. Pre-processing must flag this
  before model sees it. Score NEUTRAL (resolves to neutral after denial).
- Fixture 5: track record logging — after a scored call, confirm the .jsonl
  file contains the correct fields, append-only (two calls → two lines, not
  one overwritten).
- Fixture 6: pipeline_blocks_entry logic — STRONG_NEGATIVE → True,
  NEUTRAL → False, STRONG_POSITIVE → False.

**Rubric consistency tests (uses the 15 real worked examples from the JSON):**
These are not "run the model and check" tests. They verify that the correct
inputs reach the model in the correct format by checking the serialized prompt
content, and that the output parser correctly handles each of the three score
categories + the malformed-output fallback.

**NOT required in v1:**
- Testing that the model produces correct scores on new tickers — this is what
  the track_record_logging exists to evaluate over time, not a unit test.
- Testing Arabic search content — news APIs change, test against the interface
  not the content.

---

## 10. Deliverables checklist

- [ ] `catalyst_check.py` — `fetch_arabfinance_disclosures()`,
  `apply_category_priority_layer()`, `search_news()`, `score_with_model()`
  (stub, clearly marked), `log_to_track_record()`, `catalyst_check()`
  orchestrator, all three edge-case-rule functions as named pre-processors
- [ ] `backfill_catalyst_returns.py` — separate script to populate forward
  return fields in the track record after time has elapsed
- [ ] `test_feature6_known_answer.py` — 6 deterministic fixtures + rubric
  consistency tests, standard known-answer discipline where applicable
- [ ] `catalyst_track_record.jsonl` — created (empty, with header comment)
  on first run, append-only thereafter
- [ ] Updated `minervini_sepa_v1_strategy_config.json` — mark
  `track_record_logging.not_yet_built` as false once the logging function
  exists. Add `build_gap` note update reflecting PDF status unchanged.

---

## Change Log

- v1 — initial version. Design work already complete (rubric v0.3, 15-ticker
  test set, all edge case rules) — this spec is a translation of the JSON into
  a build handoff, not new design. Model call deferred by explicit decision.
  track_record_logging included as a first-class deliverable, not a later
  addition. Two-stage architecture (deterministic first, model last) preserves
  cost control regardless of which model is eventually chosen.
