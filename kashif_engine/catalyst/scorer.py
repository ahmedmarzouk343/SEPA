"""Rubric v0.3 catalyst scoring of SEC 8-K filings, with a hard budget cap.

Order of work (cheapest first):
  1. code-only layer: items 1.03 / 4.02 / 3.01 are STRONG_NEGATIVE with no model;
     low-tier-only filings (9.01, 5.07, ...) are NEUTRAL with no model;
  2. the model reads only high/medium-tier filings on the shortlist.

Output per filing: score in {STRONG_POSITIVE, NEUTRAL, STRONG_NEGATIVE}, the
cited source (SEC accession + items + date) and a one-sentence rationale.
Nothing found / unreadable -> NEUTRAL, said explicitly. The score is a ranking
input only; the strategy never gates on it.

Cost control: every call is cached by (accession, model, prompt version);
tokens are logged per call to kashif_data/llm_spend.jsonl with a NOTIONAL
cost at the provider's list price (the free tier bills $0); calls stop the
moment the notional total reaches BUDGET_USD. Unscored filings are recorded
as NOT_SCORED -- never silently turned into NEUTRAL.

Known limitation (reported): a model trained after 2022-2025 may "know" how
these companies fared; the prompt forbids using outside knowledge, but that
cannot be verified, so catalyst results carry hindsight risk.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "kashif_data" / "llm_cache"
SPEND_LOG = ROOT / "kashif_data" / "llm_spend.jsonl"
PROMPT_VERSION = "rubric-v0.3-us-2"   # -1 scored cover-page boilerplate; discarded
BUDGET_USD = 10.0
# List prices per 1M tokens (input, output) used for the NOTIONAL cost.
PRICES = {"openai/gpt-oss-20b": (0.075, 0.30), "gemini-3.1-flash-lite": (0.10, 0.40)}

RUBRIC = """You score ONE SEC 8-K filing for a growth-stock screening system, using rubric v0.3.
Categories (choose exactly one):
STRONG_POSITIVE: new major contract/deal; regulatory approval; capacity expansion; major partnership;
  credit rating upgrade; growth-directed acquisition or major stake purchase; earnings beat or raised
  guidance (a clear trailing YoY beat alone qualifies); capital raise clearly tied to growth; index
  inclusion or upgrade.
STRONG_NEGATIVE: litigation; regulatory investigation; credit rating downgrade; auditor concerns;
  related-party concerns; leadership departure under negative circumstances; guidance cut; earnings
  decline (sharp YoY profit drop with no offsetting positive); index exclusion.
NEUTRAL: routine disclosures; ambiguous corporate actions; reporting-basis conflicts; anything that
  fits neither strong bucket. If the text does not support a strong call, answer NEUTRAL.
Rules: judge ONLY from the filing text below, as of its filing date. Do NOT use any knowledge of later
events or later stock prices. A denied/resolved negative rumor is not negative. When citing profit
figures, name the P&L line (e.g. net income, diluted EPS) and GAAP vs non-GAAP.
Answer with JSON only: {"score": "...", "event": "<=12 words", "rationale": "one sentence"}"""


class BudgetExceeded(RuntimeError):
    pass


def _spent() -> float:
    if not SPEND_LOG.exists():
        return 0.0
    return sum(json.loads(l)["notional_usd"] for l in SPEND_LOG.read_text().splitlines() if l.strip())


def _log_spend(provider, model, pin, pout):
    cin, cout = PRICES.get(model, (1.0, 2.0))
    cost = pin / 1e6 * cin + pout / 1e6 * cout
    SPEND_LOG.parent.mkdir(parents=True, exist_ok=True)
    with SPEND_LOG.open("a") as f:
        f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "provider": provider,
                            "model": model, "prompt_tokens": pin, "completion_tokens": pout,
                            "notional_usd": cost}) + "\n")
    return cost


class Scorer:
    def __init__(self, budget_usd=BUDGET_USD, log=print):
        from dotenv import dotenv_values
        env = dotenv_values(ROOT / ".env")
        self.log = log
        self.budget = budget_usd
        self.providers = []
        if env.get("GROQ_API_KEY"):
            from openai import OpenAI
            self.providers.append(("groq", "openai/gpt-oss-20b",
                                   OpenAI(base_url="https://api.groq.com/openai/v1", api_key=env["GROQ_API_KEY"])))
        if env.get("GOOGLE_AI_STUDIO_KEY"):
            from google import genai
            self.providers.append(("gemini", "gemini-3.1-flash-lite", genai.Client(api_key=env["GOOGLE_AI_STUDIO_KEY"])))
        self.exhausted = set()
        self.calls = 0

    def _call(self, provider, model, client, prompt):
        if provider == "groq":
            r = client.chat.completions.create(model=model, temperature=0, max_tokens=400,
                                               reasoning_effort="low",
                                               messages=[{"role": "system", "content": RUBRIC},
                                                         {"role": "user", "content": prompt}])
            return r.choices[0].message.content, r.usage.prompt_tokens, r.usage.completion_tokens
        r = client.models.generate_content(model=model, contents=RUBRIC + "\n\n" + prompt)
        u = r.usage_metadata
        return r.text, u.prompt_token_count or 0, u.candidates_token_count or 0

    def score(self, filing: dict, text: str) -> dict:
        """filing: ticker, accession, filing_date, items. Returns score dict."""
        key = f"{filing['accession']}_{PROMPT_VERSION}"
        p = CACHE / f"{key}.json"
        if p.exists():
            return json.loads(p.read_text())
        if not text.strip():
            out = {"score": "NEUTRAL", "event": "", "rationale": "Filing text unavailable; nothing to score.",
                   "model": None}
            CACHE.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(out))
            return out
        prompt = (f"Company ticker: {filing['ticker']}\nFiling: SEC {filing.get('form', '8-K')} "
                  f"accession {filing['accession']}, filed {filing['filing_date']}, items {filing['items']}\n"
                  f"--- filing text (truncated) ---\n{text[:6000]}")
        for provider, model, client in self.providers:
            if provider in self.exhausted:
                continue
            for attempt in range(4):
                if _spent() >= self.budget:
                    raise BudgetExceeded(f"notional LLM spend reached ${self.budget:.2f}; hard stop")
                try:
                    raw, pin, pout = self._call(provider, model, client, prompt)
                except Exception as e:  # noqa: BLE001 -- provider errors are classified below
                    msg = str(e)
                    if "429" in msg or "rate" in msg.lower() or "quota" in msg.lower() or "RESOURCE_EXHAUSTED" in msg:
                        if "day" in msg.lower() or "RPD" in msg or "TPD" in msg or attempt == 3:
                            self.log(f"    {provider} quota exhausted: {msg[:120]}")
                            self.exhausted.add(provider)
                            break
                        time.sleep(15 * (attempt + 1))
                        continue
                    if "503" in msg or "UNAVAILABLE" in msg or "overloaded" in msg.lower():
                        time.sleep(20 * (attempt + 1))      # transient overload: back off, never "exhausted"
                        continue
                    self.log(f"    {provider} error: {type(e).__name__} {msg[:120]}")
                    time.sleep(3)
                    continue
                self.calls += 1
                _log_spend(provider, model, pin, pout)
                out = self._parse(raw)
                out["model"] = model
                CACHE.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(out))
                return out
        if all(pr in self.exhausted for pr, _, _ in self.providers):
            return {"score": "NOT_SCORED", "event": "", "rationale": "all providers exhausted", "model": None}
        return {"score": "NOT_SCORED", "event": "", "rationale": "transient provider errors", "model": None}

    @staticmethod
    def _parse(raw: str) -> dict:
        m = re.search(r"\{.*\}", raw or "", re.S)
        try:
            d = json.loads(m.group(0)) if m else {}
        except json.JSONDecodeError:
            d = {}
        s = str(d.get("score", "")).upper().strip()
        if s not in ("STRONG_POSITIVE", "NEUTRAL", "STRONG_NEGATIVE"):
            return {"score": "NEUTRAL", "event": "", "rationale": f"unparseable model answer -> NEUTRAL: {str(raw)[:80]}"}
        return {"score": s, "event": str(d.get("event", ""))[:120], "rationale": str(d.get("rationale", ""))[:300]}
