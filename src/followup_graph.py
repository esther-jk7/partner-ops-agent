"""LangGraph workflow: draft a follow-up, fact-check it, and rewrite until it passes (max 3 attempts)."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from src.followup import get_facts, write_draft
from src.validator import validate_draft

MAX_ATTEMPTS = 3


class FollowUpState(TypedDict):
    facts: str
    draft: dict
    problems: list[str]
    passed: bool
    attempts: int
    history: list[dict]


def draft_node(state: FollowUpState) -> dict:
    draft = write_draft(state["facts"], state["problems"] or None)
    return {"draft": draft, "attempts": state["attempts"] + 1}


def validate_node(state: FollowUpState) -> dict:
    result = validate_draft(state["facts"], state["draft"])
    log = {"attempt": state["attempts"], "passed": result["passed"], "problems": result["problems"]}
    return {"passed": result["passed"], "problems": result["problems"], "history": state["history"] + [log]}


def route_after_validation(state: FollowUpState) -> str:
    if state["passed"] or state["attempts"] >= MAX_ATTEMPTS:
        return "done"
    return "rewrite"


builder = StateGraph(FollowUpState)
builder.add_node("draft", draft_node)
builder.add_node("validate", validate_node)
builder.add_edge(START, "draft")
builder.add_edge("draft", "validate")
builder.add_conditional_edges("validate", route_after_validation, {"rewrite": "draft", "done": END})
followup_graph = builder.compile()


def run_followup(conn, opportunity_id: str, issues: list[dict]) -> dict:
    """Run the draft-and-validate loop for one flagged deal."""
    company, facts = get_facts(conn, opportunity_id, issues)
    final = followup_graph.invoke({
        "facts": facts, "draft": {}, "problems": [], "passed": False, "attempts": 0, "history": [],
    })
    return {
        "opportunity_id": opportunity_id,
        "company": company,
        **final["draft"],
        "passed": final["passed"],
        "attempts": final["attempts"],
        "history": final["history"],
        "needs_review": not final["passed"],
    }
