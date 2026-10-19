"""Validator agent: checks a follow-up draft for claims not supported by the deal data."""

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate

from src.llm import get_llm


class ValidationResult(BaseModel):
    passed: bool = Field(description="True only if every specific claim in the email is supported by the deal facts")
    problems: list[str] = Field(description="Each unsupported claim, quoted from the email, with why it is unsupported. Empty if passed.")


PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are a strict fact-checker for emails IDC sends to partner companies. "
     "Compare the email against the deal facts. Flag any specific claim the facts do not support, including: "
     "meeting times or availability, dates, prices, deliverables, attachments, past events, people's names other than the deal owner, "
     "and promises or commitments. "
     "Placeholders like [First Name] are allowed. General polite phrases (e.g. 'I hope you are well') are allowed. "
     "Asking the partner a question or suggesting a call without specifying times is allowed."),
    ("human", "Deal facts:\n{facts}\n\nEmail subject: {subject}\n\nEmail body:\n{body}"),
])


def validate_draft(facts: str, draft: dict) -> dict:
    """Return {'passed': bool, 'problems': [...]} for one draft."""
    chain = PROMPT | get_llm().with_structured_output(ValidationResult)
    result = chain.invoke({"facts": facts, "subject": draft["subject"], "body": draft["body"]})
    return result.model_dump()
