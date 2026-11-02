"""Triage: rules decide the score and tier, the LLM explains them and suggests a next step."""

import time

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate

from src.llm import get_llm
from src.scoring import is_missing, score_opportunity


class TriageNote(BaseModel):
    rationale: str = Field(description="Two sentences explaining why this opportunity got its tier, citing the point breakdown")
    next_action: str = Field(description="One concrete next step for the partnerships team")


PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are a partnerships analyst at IDC, a global technology research and advisory firm. "
     "A rules-based system has already scored this inbound partner opportunity and assigned its tier. "
     "Do not change or second-guess the tier. Explain it using only the facts provided. "
     "If any fields are missing, the next action should include collecting them."),
    ("human",
     "Opportunity:\n{opportunity}\n\n"
     "Score: {score}/90\nTier: {tier}\nPoint breakdown: {breakdown}\nMissing fields: {missing}"),
])


FIELD_LABELS = {
    "company": "company name",
    "partner_type": "partner type",
    "region": "region",
    "employees": "company size (employees)",
    "est_annual_value_usd": "estimated annual deal value",
    "source": "lead source",
}


def format_opportunity(opp: dict) -> str:
    """Turn an opportunity into readable lines, skipping blank fields."""
    return "\n".join(f"{key}: {value}" for key, value in opp.items() if not is_missing(value))


MAX_ATTEMPTS = 2
RETRY_PAUSE_SECONDS = 2


def triage(opp: dict) -> dict:
    """Score an opportunity with the rules, then add an LLM-written rationale and next action.

    If the LLM fails twice, the rules-based score is kept and the explanation is marked
    for manual review, so one bad response never stops the whole batch.
    """
    result = score_opportunity(opp)
    missing = ", ".join(FIELD_LABELS.get(f, f) for f in result["missing_fields"]) or "none"
    chain = PROMPT | get_llm().with_structured_output(TriageNote)
    inputs = {
        "opportunity": format_opportunity(opp),
        "score": result["score"],
        "tier": result["tier"],
        "breakdown": result["breakdown"],
        "missing": missing,
    }

    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            note = chain.invoke(inputs)
            result.update(note.model_dump())
            return result
        except Exception as err:  # provider errors vary (bad output, rate limits, timeouts)
            last_error = err
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_PAUSE_SECONDS)

    print(f"  ! {result['opportunity_id']}: LLM explanation failed after {MAX_ATTEMPTS} attempts "
          f"({type(last_error).__name__}); saved the rules-based score for manual review")
    result["rationale"] = (f"Automated explanation unavailable. Score {result['score']}/90 and tier "
                           f"{result['tier']} come from the rules. Point breakdown: {result['breakdown']}")
    result["next_action"] = (f"Review manually. Collect missing fields: {missing}" if missing != "none"
                             else "Review manually: automated explanation unavailable")
    return result
