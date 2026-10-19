"""Triage: rules decide the score and tier, the LLM explains them and suggests a next step."""

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


def triage(opp: dict) -> dict:
    """Score an opportunity with the rules, then add an LLM-written rationale and next action."""
    result = score_opportunity(opp)
    chain = PROMPT | get_llm().with_structured_output(TriageNote)
    note = chain.invoke({
        "opportunity": format_opportunity(opp),
        "score": result["score"],
        "tier": result["tier"],
        "breakdown": result["breakdown"],
        "missing": ", ".join(FIELD_LABELS.get(f, f) for f in result["missing_fields"]) or "none",
    })
    result.update(note.model_dump())
    return result
