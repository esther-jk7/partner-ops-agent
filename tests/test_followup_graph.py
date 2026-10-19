import src.followup_graph as fg


def run_with_fake_validator(monkeypatch, verdicts):
    """Run the graph with a fake drafter and a validator that returns the given pass/fail verdicts in order."""
    calls = iter(verdicts)
    monkeypatch.setattr(fg, "write_draft", lambda facts, problems=None: {"subject": "s", "body": "b", "internal_note": "n"})

    def fake_validate(facts, draft):
        passed = next(calls)
        return {"passed": passed, "problems": [] if passed else ["Invented meeting time"]}

    monkeypatch.setattr(fg, "validate_draft", fake_validate)
    return fg.followup_graph.invoke({"facts": "f", "draft": {}, "problems": [], "passed": False, "attempts": 0, "history": []})


def test_clean_first_draft_stops_after_one_attempt(monkeypatch):
    final = run_with_fake_validator(monkeypatch, [True])
    assert final["passed"] is True
    assert final["attempts"] == 1


def test_failed_draft_is_rewritten_until_it_passes(monkeypatch):
    final = run_with_fake_validator(monkeypatch, [False, True])
    assert final["passed"] is True
    assert final["attempts"] == 2
    assert final["history"][0]["problems"] == ["Invented meeting time"]


def test_loop_stops_at_max_attempts(monkeypatch):
    final = run_with_fake_validator(monkeypatch, [False, False, False, False])
    assert final["passed"] is False
    assert final["attempts"] == fg.MAX_ATTEMPTS
