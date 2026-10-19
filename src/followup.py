"""Draft follow-up emails for deals the hygiene checks flagged."""

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate

from src.llm import get_llm

ACTIONABLE_ISSUES = {"Overdue follow-up", "Stale deal", "Priority deal not started"}

CONTEXT_QUERY = """
SELECT o.company, o.partner_type, o.description, p.stage, p.owner, p.last_contact_date, t.tier, t.next_action
FROM opportunities o
JOIN triage_results t ON o.opportunity_id = t.opportunity_id
JOIN pipeline p ON o.opportunity_id = p.opportunity_id
WHERE o.opportunity_id = ?
"""


class FollowUpDraft(BaseModel):
    subject: str = Field(description="Short email subject line")
    body: str = Field(description="Email body under 120 words, ready for the owner to review and send")
    internal_note: str = Field(description="One line for the partnerships team, e.g. what to fix before sending")


PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You draft follow-up emails for IDC's partnerships team. IDC is a global technology research and advisory firm. "
     "Write a warm, concise, professional email to the partner company. "
     "Do not invent prices, dates, meeting times, availability, deliverables, or commitments that are not in the deal facts. "
     "Never describe when something happened (e.g. 'last week') unless you use the exact last contact date given. "
     "Sign off with only the deal owner's name and 'IDC' on the next line, or 'IDC Partnerships Team' if there is no owner. "
     "Do not add job titles. "
     "The internal note is for IDC staff only: flag anything that should be fixed before the email is sent."),
    ("human", "Deal facts:\n{facts}\n\n{feedback}"),
])


def group_actionable(issues: list[dict]) -> dict[str, list[dict]]:
    """Group issues by deal, keeping only deals with problems a follow-up email can fix."""
    grouped = {}
    for issue in issues:
        grouped.setdefault(issue["opportunity_id"], []).append(issue)
    return {opp_id: items for opp_id, items in grouped.items()
            if any(i["issue"] in ACTIONABLE_ISSUES for i in items)}


def get_facts(conn, opportunity_id: str, issues: list[dict]) -> tuple[str, str]:
    """Return the company name and a plain-text summary of everything known about the deal."""
    row = conn.execute(CONTEXT_QUERY, (opportunity_id,)).fetchone()
    facts = (
        f"Company: {row['company']}\n"
        f"Partner type: {row['partner_type']}\n"
        f"What they want: {row['description']}\n"
        f"Current stage: {row['stage']}\n"
        f"Deal owner: {row['owner'] or 'none assigned'}\n"
        f"Last contact date: {row['last_contact_date'] or 'no contact yet'}\n"
        f"Tier: {row['tier']}\n"
        f"Suggested next action from triage: {row['next_action']}\n"
        f"Problems found in the pipeline: " + "; ".join(f"{i['issue']}: {i['detail']}" for i in issues)
    )
    return row["company"], facts


def write_draft(facts: str, problems: list[str] | None = None) -> dict:
    """Ask the LLM for a draft. If a previous draft failed validation, include the problems to fix."""
    feedback = ""
    if problems:
        feedback = ("Your previous draft was rejected by the fact-checker for these unsupported claims. "
                    "Rewrite the email without them:\n- " + "\n- ".join(problems))
    chain = PROMPT | get_llm().with_structured_output(FollowUpDraft)
    return chain.invoke({"facts": facts, "feedback": feedback}).model_dump()


def draft_followup(conn, opportunity_id: str, issues: list[dict]) -> dict:
    """Single draft with no validation (kept so the current dashboard still works)."""
    company, facts = get_facts(conn, opportunity_id, issues)
    return {"opportunity_id": opportunity_id, "company": company, **write_draft(facts)}
