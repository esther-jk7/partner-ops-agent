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
     "Do not invent prices, dates, deliverables, or commitments that are not in the context. "
     "Never describe when something happened (e.g. 'last week') unless you use the exact last contact date given. "
     "Sign off with only the deal owner's name and 'IDC' on the next line, or 'IDC Partnerships Team' if there is no owner. Do not add job titles. "
     "The internal note is for IDC staff only: flag anything that should be fixed before the email is sent."),
    ("human",
     "Company: {company}\nPartner type: {partner_type}\nWhat they want: {description}\n"
     "Current stage: {stage}\nDeal owner: {owner}\nLast contact date: {last_contact}\nTier: {tier}\n"
     "Suggested next action from triage: {next_action}\n"
     "Problems found in the pipeline: {issues}"),
])


def group_actionable(issues: list[dict]) -> dict[str, list[dict]]:
    """Group issues by deal, keeping only deals with problems a follow-up email can fix."""
    grouped = {}
    for issue in issues:
        grouped.setdefault(issue["opportunity_id"], []).append(issue)
    return {opp_id: items for opp_id, items in grouped.items()
            if any(i["issue"] in ACTIONABLE_ISSUES for i in items)}


def draft_followup(conn, opportunity_id: str, issues: list[dict]) -> dict:
    """Ask the LLM for a follow-up email for one flagged deal."""
    row = conn.execute(CONTEXT_QUERY, (opportunity_id,)).fetchone()
    chain = PROMPT | get_llm().with_structured_output(FollowUpDraft)
    draft = chain.invoke({
        "company": row["company"],
        "partner_type": row["partner_type"],
        "description": row["description"],
        "stage": row["stage"],
        "owner": row["owner"] or "none assigned",
        "last_contact": row["last_contact_date"] or "no contact yet",
        "tier": row["tier"],
        "next_action": row["next_action"],
        "issues": "; ".join(f"{i['issue']}: {i['detail']}" for i in issues),
    })
    return {"opportunity_id": opportunity_id, "company": row["company"], **draft.model_dump()}
