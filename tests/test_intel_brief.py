"""Brief tests with a fake model: headlines stay verbatim, rules decide relevance, repeats are grouped."""

from langchain_core.runnables import RunnableLambda

import src.intel_brief as brief_module
from src.intel_brief import (CompanyJudgments, ItemJudgment, channel_term, classify_company, render_markdown)

ENTRY = {"company": "Anthropic", "relationship": "Partner", "query": "Anthropic",
         "why_watch": "Distribution partner: IDC Quanta is available inside Claude through a connector",
         "channel_terms": ""}
CHANNEL_ENTRY = {**ENTRY, "channel_terms": "connector;Quick Research"}
COMPETITOR = {"company": "Gartner", "relationship": "Competitor", "query": "Gartner",
              "why_watch": "Competitor: technology research and advisory firm", "channel_terms": ""}
ITEMS = [
    {"company": "Anthropic", "relationship": "Partner", "title": "Anthropic launches new enterprise connector",
     "source": "Reuters", "published": "2026-11-02", "link": "https://example.com/a"},
    {"company": "Anthropic", "relationship": "Partner", "title": "Anthropic files for its IPO",
     "source": "Axios", "published": "2026-10-26", "link": "https://example.com/b"},
]


def judgment(index, signal_type="Product or service launch", why="This could widen how IDC Quanta reaches Claude users.",
             same_story_as=None, action="Flag to the GTM director to check whether IDC can join the launch."):
    return ItemJudgment(index=index, same_story_as=same_story_as, signal_type=signal_type, why_it_matters=why,
                        suggested_action=action, owner="Partner GTM & Activation")


class FakeLLM:
    def __init__(self, judgments=(), failures=0):
        self.judgments, self.failures, self.calls = list(judgments), failures, 0

    def _respond(self, _inputs):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("tool_use_failed")
        return CompanyJudgments(items=self.judgments)

    def with_structured_output(self, _schema):
        return RunnableLambda(self._respond)


def use_fake(monkeypatch, **kwargs):
    fake = FakeLLM(**kwargs)
    monkeypatch.setattr(brief_module, "get_llm", lambda: fake)
    monkeypatch.setattr(brief_module, "RETRY_PAUSE_SECONDS", 0)
    return fake


def test_headlines_are_kept_word_for_word(monkeypatch):
    use_fake(monkeypatch, judgments=[judgment(1), judgment(2)])
    result = classify_company(ENTRY, ITEMS)
    assert [r["title"] for r in result] == [i["title"] for i in ITEMS]
    assert all(r["judgment_source"] == "llm" for r in result)


def test_invented_number_rejects_only_that_judgment(monkeypatch):
    use_fake(monkeypatch, judgments=[judgment(1, why="Could reach IDC's 300 enterprise clients."), judgment(2)])
    first, second = classify_company(ENTRY, ITEMS)
    assert first["relevance"] == "Unrated" and first["judgment_source"].startswith("rejected")
    assert second["judgment_source"] == "llm"


def test_llm_failure_keeps_every_headline(monkeypatch):
    fake = use_fake(monkeypatch, failures=5)
    result = classify_company(ENTRY, ITEMS)
    assert fake.calls == brief_module.MAX_ATTEMPTS
    assert len(result) == 2
    assert all(r["judgment_source"] == "not classified (LLM failed)" for r in result)


def test_missing_judgment_marks_headline_unclassified(monkeypatch):
    use_fake(monkeypatch, judgments=[judgment(1)])
    result = classify_company(ENTRY, ITEMS)
    assert result[1]["judgment_source"] == "not classified (no judgment returned)"


def test_same_story_is_grouped_under_first_headline(monkeypatch):
    use_fake(monkeypatch, judgments=[judgment(1), judgment(2, same_story_as=1)])
    result = classify_company(ENTRY, ITEMS)
    assert len(result) == 1
    assert result[0]["also_covered_by"][0]["source"] == "Axios"


def test_invalid_story_references_are_ignored(monkeypatch):
    use_fake(monkeypatch, judgments=[judgment(1, same_story_as=2), judgment(2, same_story_as=2)])
    assert len(classify_company(ENTRY, ITEMS)) == 2


def test_rule_table_decides_relevance_not_the_llm(monkeypatch):
    use_fake(monkeypatch, judgments=[judgment(1, signal_type="Research publication"),
                                     judgment(2, signal_type="New research product", action="No action")])
    blog_post, new_product = classify_company(COMPETITOR, ITEMS)
    assert blog_post["relevance"] == "Low" and blog_post["suggested_action"] == "No action"
    assert new_product["relevance"] == "Medium"
    assert new_product["relevance_basis"] == "Competitor + New research product = Medium (rule table)"
    assert new_product["suggested_action"] == brief_module.ROUTE_ACTION


def test_partner_product_news_is_low_but_financials_are_medium(monkeypatch):
    use_fake(monkeypatch, judgments=[judgment(1), judgment(2, signal_type="Earnings or financials")])
    launch, ipo = classify_company(ENTRY, ITEMS)
    assert launch["relevance"] == "Low"
    assert ipo["relevance"] == "Medium"


def test_channel_term_raises_partner_launch_to_high(monkeypatch):
    use_fake(monkeypatch, judgments=[judgment(1), judgment(2)])
    first, second = classify_company(CHANNEL_ENTRY, ITEMS)
    assert first["relevance"] == "High" and "connector" in first["rule_note"]
    assert second["relevance"] == "Low" and second["rule_note"] is None


def test_channel_rule_still_surfaces_news_when_llm_fails(monkeypatch):
    use_fake(monkeypatch, failures=5)
    first, second = classify_company(CHANNEL_ENTRY, ITEMS)
    assert first["relevance"] == "High"
    assert first["owner"] == "Partner GTM & Activation"
    assert first["suggested_action"] == brief_module.ROUTE_ACTION
    assert second["relevance"] == "Unrated"


def test_channel_terms_match_whole_words_only():
    entry = {**ENTRY, "channel_terms": "MCP"}
    assert channel_term(entry, "McPherson joins the company board") is None
    assert channel_term(entry, "Anthropic expands MCP support") == "MCP"


def test_markdown_shows_grouped_story_once_with_caveat(monkeypatch):
    use_fake(monkeypatch, judgments=[judgment(1), judgment(2, same_story_as=1)])
    brief = {"fetched_at": "2026-11-02T18:00:00+00:00", "lookback_days": 14,
             "items": classify_company(CHANNEL_ENTRY, ITEMS),
             "errors": [{"company": "Gartner", "error": "URLError"}]}
    text = render_markdown(brief)
    assert "Built from 2 headlines (1 story)" in text
    assert "## Needs attention (1)" in text
    assert "Also covered by: [Axios]" in text
    assert "Relevance comes from a rule table" in text
    assert "Gartner: URLError" in text
