"""Validator agent: checks a follow-up draft for claims not supported by the deal data.

If the check itself fails, the draft is treated as unchecked (failed), never as approved.
"""

import time

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate

from src.llm import get_llm

MAX_ATTEMPTS = 2
RETRY_PAUSE_SECONDS = 2
CHECK_FAILED = "Fact-check could not run (model error), so this draft is unchecked: review it manually"


class ValidationResult(BaseModel):
    passed: bool = Field(description="True only if every specific claim in the email is supported by the deal facts")
    problems: list[str] = Field(description="Every unsupported claim, quoted from the email, with why it is unsupported. Empty if passed.")


PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are a strict fact-checker for emails IDC sends to partner companies. "
     "Compare the email against the deal facts. Flag any specific claim the facts do not support, including: "
     "meeting times or availability, dates, prices, deliverables, attachments, past events, people's names other than the deal owner, "
     "and promises or commitments. "
     "Any claim that something already happened (a meeting, call, note, approval, confirmation, or launch) is unsupported "
     "unless the facts record it as having happened; a scheduled event has not happened yet. "
     "List every unsupported claim, not just the first one you find. "
     "Placeholders like [First Name] are allowed. General polite phrases (e.g. 'I hope you are well') are allowed. "
     "Asking the partner a question or suggesting a call without specifying times is allowed."),
    ("human", "Deal facts:\n{facts}\n\nEmail subject: {subject}\n\nEmail body:\n{body}"),
])


def validate_draft(facts: str, draft: dict) -> dict:
    """Return {'passed': bool, 'problems': [...], 'error': bool} for one draft. Fails closed."""
    chain = PROMPT | get_llm().with_structured_output(ValidationResult)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = chain.invoke({"facts": facts, "subject": draft["subject"], "body": draft["body"]})
            return {**result.model_dump(), "error": False}
        except Exception:  # provider errors vary; a broken check must never look like a pass
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_PAUSE_SECONDS)
    return {"passed": False, "problems": [CHECK_FAILED], "error": True}
