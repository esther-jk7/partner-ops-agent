"""Triage tests: LLM failures, invented numbers, and decisions the LLM can't override."""

import pandas as pd
from langchain_core.runnables import RunnableLambda

import src.triage as triage_module
from src.scoring import score_opportunity
from src.triage import TIER_PLAYBOOK, TriageNote, triage, unsupported_numbers

ROWS = {r["opportunity_id"]: r for r in pd.read_csv("data/inbound_opportunities.csv").to_dict("records")}
CLEAN = ROWS["OPP-013"]   # Priority, no flags
GATED = ROWS["OPP-001"]   # Priority, but wants to train models on IDC data


class FakeLLM:
    """Stands in for the real model: fails a set number of times, then returns a fixed note."""

    def __init__(self, failures=0, rationale="Strong fit on partnership model and revenue.",
                 next_action="Book an intro call."):
        self.failures, self.calls = failures, 0
        self.note = TriageNote(rationale=rationale, next_action=next_action)

    def _respond(self, _inputs):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("model did not call a tool")
        return self.note

    def with_structured_output(self, _schema):
        return RunnableLambda(self._respond)


def use_fake(monkeypatch, **kwargs):
    fake = FakeLLM(**kwargs)
    monkeypatch.setattr(triage_module, "get_llm", lambda: fake)
    monkeypatch.setattr(triage_module, "RETRY_PAUSE_SECONDS", 0)
    return fake


def test_llm_failure_keeps_rules_score_and_playbook_action(monkeypatch):
    fake = use_fake(monkeypatch, failures=5)
    result = triage(CLEAN)
    expected = score_opportunity(CLEAN)
    assert fake.calls == triage_module.MAX_ATTEMPTS
    assert (result["score"], result["tier"]) == (expected["score"], expected["tier"])
    assert result["rationale"].startswith("Automated explanation unavailable")
    assert result["next_action"] == TIER_PLAYBOOK["Priority"]
    assert result["explanation_source"] == "rules (LLM failed)"


def test_one_failure_is_recovered_by_retry(monkeypatch):
    fake = use_fake(monkeypatch, failures=1)
    result = triage(CLEAN)
    assert fake.calls == 2
    assert result["rationale"] == "Strong fit on partnership model and revenue."
    assert result["next_action"] == "Book an intro call."
    assert result["explanation_source"] == "llm"


def test_invented_number_is_replaced_with_rule_wording(monkeypatch):
    use_fake(monkeypatch, rationale="Fits IDC's 500 healthcare accounts.")
    result = triage(CLEAN)
    assert result["explanation_source"].startswith("rules")
    assert "500" not in result["rationale"]


def test_numbers_from_the_data_are_accepted(monkeypatch):
    use_fake(monkeypatch, rationale="Scored 95 out of 100, above the Priority threshold of 70.")
    result = triage(CLEAN)
    assert result["explanation_source"] == "llm"


def test_data_rights_gate_overrides_llm_next_action(monkeypatch):
    use_fake(monkeypatch, next_action="Book an intro call.")
    result = triage(GATED)
    assert result["next_action"].startswith("Hold outreach until reviewed")
    assert "Data rights" in result["next_action"]


def test_unsupported_numbers_ignores_commas_and_formatting():
    assert unsupported_numbers("Worth $450,000 over 3 calls", "value 450000") == ["3"]
