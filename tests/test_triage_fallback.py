"""Tests that one bad LLM response never stops the batch or changes the rules-based score."""

import pandas as pd
from langchain_core.runnables import RunnableLambda

import src.triage as triage_module
from src.scoring import score_opportunity
from src.triage import TriageNote, triage

OPP = pd.read_csv("data/inbound_opportunities.csv").to_dict("records")[0]


class FakeLLM:
    """Stands in for the real model: fails a set number of times, then returns a note."""

    def __init__(self, failures: int):
        self.failures = failures
        self.calls = 0

    def _respond(self, _inputs):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("model did not call a tool")
        return TriageNote(rationale="Scored on value and fit.", next_action="Book an intro call.")

    def with_structured_output(self, _schema):
        return RunnableLambda(self._respond)


def use_fake(monkeypatch, failures):
    fake = FakeLLM(failures)
    monkeypatch.setattr(triage_module, "get_llm", lambda: fake)
    monkeypatch.setattr(triage_module, "RETRY_PAUSE_SECONDS", 0)
    return fake


def test_llm_failure_falls_back_to_rules_score(monkeypatch):
    fake = use_fake(monkeypatch, failures=5)
    result = triage(OPP)
    expected = score_opportunity(OPP)
    assert fake.calls == triage_module.MAX_ATTEMPTS
    assert (result["score"], result["tier"]) == (expected["score"], expected["tier"])
    assert result["rationale"].startswith("Automated explanation unavailable")
    assert result["next_action"].startswith("Review manually")


def test_one_failure_is_recovered_by_retry(monkeypatch):
    fake = use_fake(monkeypatch, failures=1)
    result = triage(OPP)
    assert fake.calls == 2
    assert result["rationale"] == "Scored on value and fit."
