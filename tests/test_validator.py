"""The Validator fails closed: if the check can't run, the draft is unchecked, never approved."""

from langchain_core.runnables import RunnableLambda

import src.validator as validator_module
from src.validator import CHECK_FAILED, ValidationResult, validate_draft

DRAFT = {"subject": "Following up", "body": "Hi [First Name],\n\nFollowing up on our conversation.\n\nBest,\nDaniel Brooks"}


class FakeLLM:
    def __init__(self, failures):
        self.failures, self.calls = failures, 0

    def _respond(self, _inputs):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("tool_use_failed")
        return ValidationResult(passed=True, problems=[])

    def with_structured_output(self, _schema):
        return RunnableLambda(self._respond)


def use_fake(monkeypatch, failures):
    fake = FakeLLM(failures)
    monkeypatch.setattr(validator_module, "get_llm", lambda: fake)
    monkeypatch.setattr(validator_module, "RETRY_PAUSE_SECONDS", 0)
    return fake


def test_broken_check_fails_closed(monkeypatch):
    fake = use_fake(monkeypatch, failures=5)
    assert validate_draft("Company: Test Co", DRAFT) == {"passed": False, "problems": [CHECK_FAILED], "error": True}
    assert fake.calls == validator_module.MAX_ATTEMPTS


def test_one_failure_is_recovered_by_retry(monkeypatch):
    use_fake(monkeypatch, failures=1)
    assert validate_draft("Company: Test Co", DRAFT) == {"passed": True, "problems": [], "error": False}
