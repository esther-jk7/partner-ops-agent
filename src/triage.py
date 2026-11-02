"""Triage: rules decide the score, tier, and flags; the LLM only explains them in plain language.

The LLM gets the rule-generated reasons as the only facts it may cite. Any number in its text
that isn't in those facts is treated as invented, and rule-based wording is used instead.
Routing and review decisions never depend on the LLM.
"""

import re
import time

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate

from src.llm import get_llm
from src.scoring import MAX_SCORE, NURTURE_THRESHOLD, PRIORITY_THRESHOLD, is_missing, score_opportunity


class TriageNote(BaseModel):
    rationale: str = Field(description="Two sentences explaining the tier, using only the scoring reasons provided")
    next_action: str = Field(description="One concrete next step for the partnerships team")


PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are a partnerships analyst at IDC, a global technology research and advisory firm. "
     "A rules-based system has already scored this inbound partner opportunity. "
     "Do not change or second-guess the score, tier, or flags. "
     "Explain the tier using only the scoring reasons provided. Do not add facts, numbers, or claims "
     "about IDC's strategy that are not in them, and write any number exactly as it appears. "
     "If fields are missing, the next action should include collecting them."),
    ("human", "{facts}"),
])

FIELD_LABELS = {
    "company": "company name",
    "partner_type": "partner type",
    "region": "region",
    "employees": "company size (employees)",
    "est_annual_value_usd": "estimated annual deal value",
    "source": "lead source",
    "partnership_model": "partnership model",
    "revenue_model": "revenue model",
    "integration_effort": "integration effort",
    "wants_model_training": "data-use terms (model training)",
}

TIER_PLAYBOOK = {
    "Priority": "Assign an owner and schedule an intro call",
    "Nurture": "Add to the follow-up queue and revisit next month",
    "Deprioritize": "No outreach for now; revisit next quarter",
}

MAX_ATTEMPTS = 2
RETRY_PAUSE_SECONDS = 2
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def format_opportunity(opp: dict) -> str:
    """Turn an opportunity into readable lines, skipping blank fields."""
    return "\n".join(f"{key}: {value}" for key, value in opp.items() if not is_missing(value))


def build_facts(opp: dict, result: dict, missing: str) -> str:
    """Everything the LLM is allowed to cite, in one block."""
    lines = [
        "Opportunity:", format_opportunity(opp), "",
        f"Score: {result['score']}/{MAX_SCORE}",
        f"Tier: {result['tier']}",
        f"Tier thresholds: Priority {PRIORITY_THRESHOLD}+, Nurture {NURTURE_THRESHOLD}-{PRIORITY_THRESHOLD - 1}, "
        f"Deprioritize below {NURTURE_THRESHOLD}",
        "Scoring reasons:",
        *[f"- {reason}" for reason in result["reasons"]],
        f"Route to sales: {'yes' if result['route_to_sales'] else 'no'}",
        f"Review flags: {'; '.join(result['review_reasons']) or 'none'}",
        f"Missing fields: {missing}",
    ]
    return "\n".join(lines)


def unsupported_numbers(text: str, facts: str) -> list[str]:
    """Numbers in the LLM's text that appear nowhere in the facts it was given."""
    allowed = {n.replace(",", "") for n in NUMBER.findall(facts)}
    return [n for n in NUMBER.findall(text) if n.replace(",", "") not in allowed]


def rules_rationale(result: dict) -> str:
    """A plain explanation built only from the two biggest scoring reasons."""
    ranked = sorted(zip(result["breakdown"].values(), result["reasons"]), key=lambda pair: -pair[0])
    top = "; ".join(reason for _, reason in ranked[:2])
    return f"Scored {result['score']}/{MAX_SCORE}, tier {result['tier']}. Biggest factors: {top}."


def rules_next_action(result: dict, missing: str) -> str:
    """The next step decided by rules: routing and review always come first."""
    if result["route_to_sales"]:
        return "Hand off to the IDC sales team: this is a client request, not a partnership"
    if result["needs_review"]:
        return "Hold outreach until reviewed: " + "; ".join(result["review_reasons"])
    if missing != "none":
        return f"Collect missing fields: {missing}"
    return TIER_PLAYBOOK[result["tier"]]


def triage(opp: dict) -> dict:
    """Score with the rules, then add a plain-language explanation that can't add new facts."""
    result = score_opportunity(opp)
    missing = ", ".join(FIELD_LABELS.get(f, f) for f in result["missing_fields"]) or "none"
    facts = build_facts(opp, result, missing)
    chain = PROMPT | get_llm().with_structured_output(TriageNote)

    note, last_error = None, None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            note = chain.invoke({"facts": facts})
            break
        except Exception as err:  # provider errors vary (bad output, rate limits, timeouts)
            last_error = err
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_PAUSE_SECONDS)

    if note is None:
        print(f"  ! {result['opportunity_id']}: LLM explanation failed after {MAX_ATTEMPTS} attempts "
              f"({type(last_error).__name__}); used rule-based wording")
        result["rationale"] = "Automated explanation unavailable. " + rules_rationale(result)
        result["next_action"] = rules_next_action(result, missing)
        result["explanation_source"] = "rules (LLM failed)"
        return result

    invented = unsupported_numbers(f"{note.rationale} {note.next_action}", facts)
    if invented:
        print(f"  ! {result['opportunity_id']}: LLM cited numbers not in the data "
              f"({', '.join(invented)}); used rule-based wording")
        result["rationale"] = rules_rationale(result)
        result["next_action"] = rules_next_action(result, missing)
        result["explanation_source"] = "rules (LLM cited unsupported numbers)"
        return result

    result["rationale"] = note.rationale
    if result["route_to_sales"] or result["needs_review"]:
        result["next_action"] = rules_next_action(result, missing)  # never left to LLM wording
    else:
        result["next_action"] = note.next_action
    result["explanation_source"] = "llm"
    return result
