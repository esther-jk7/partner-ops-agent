"""Turn a news snapshot into a partner intelligence brief.

Headline, source, date, and link are kept word for word: they are the facts.
The LLM classifies each headline's signal type, says why it could matter, suggests a small step,
and marks repeat coverage. It does not rate relevance: a rule table maps relationship and signal
type to a level, and a channel-term rule raises headlines naming IDC's channels to High.
Any number in a judgment that isn't in its inputs gets that judgment rejected.
"""

import json
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate

from src.intel_fetch import SNAPSHOT_DIR, load_watchlist
from src.llm import get_llm
from src.triage import unsupported_numbers

SignalType = Literal["Product or service launch", "New research product", "Research publication", "Partnership",
                     "Acquisition", "Leadership change", "Earnings or financials", "Market commentary",
                     "Third-party mention", "Other"]


class ItemJudgment(BaseModel):
    index: int = Field(description="The number of the headline being judged")
    same_story_as: int | None = Field(default=None, description="If this headline covers the same event as an "
                                      "earlier-numbered headline, that headline's number; otherwise null")
    signal_type: SignalType
    why_it_matters: str = Field(description="One sentence on why this could matter to IDC, using only the headline and the watchlist note")
    suggested_action: str = Field(description="One small internal step for IDC's team, or 'No action'")
    owner: Literal["Strategic Partner Development", "Partner GTM & Activation", "Leadership", "None"]


class CompanyJudgments(BaseModel):
    items: list[ItemJudgment]


PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are a partner intelligence analyst for the partnerships team at IDC, a technology research and data firm. "
     "For each numbered headline about one company, classify what kind of news it is and say briefly why it could "
     "matter to IDC's partnerships. Use only the headline text and the watchlist note. Do not state facts that aren't "
     "in them, do not guess at connections the headline doesn't show, and write any number exactly as it appears.\n\n"
     "Signal types:\n"
     "- Product or service launch: the company launches or changes a product or service.\n"
     "- New research product: a new research offering, rating, index, or framework, such as an inaugural Magic Quadrant.\n"
     "- Research publication: an article, blog post, prediction, survey finding, or commissioned study.\n"
     "- Partnership: a new or expanded partnership.\n"
     "- Acquisition: the company buys or is bought.\n"
     "- Leadership change: an executive joins, leaves, or changes role.\n"
     "- Earnings or financials: reported results, an IPO, funding, or a regulatory filing.\n"
     "- Market commentary: earnings previews, stock analysis, or opinion pieces about the company.\n"
     "- Third-party mention: another company's announcement that only mentions this company, such as a vendor citing its rating.\n"
     "- Other: anything else.\n\n"
     "Suggested actions are small internal steps for IDC's team, such as flagging to an owner, checking with the "
     "partner contact, or adding a line to the leadership briefing. Never commit IDC to a campaign, deal, or outreach. "
     "If the news needs nothing from IDC, the action is 'No action' and the owner is None.\n\n"
     "Owners: Strategic Partner Development handles new or expanded deals; Partner GTM & Activation handles launches "
     "and joint marketing with existing partners; Leadership handles competitive moves and strategic risks.\n\n"
     "If a headline covers the same event as an earlier-numbered headline, set same_story_as to that number. "
     "Return one judgment per headline."),
    ("human", "{facts}"),
])

# Relevance is decided here, not by the LLM. Anything not listed is Low. High comes only from the channel rule.
RELEVANCE_RULES = {
    "Partner": {"Partnership": "Medium", "Acquisition": "Medium", "Leadership change": "Medium",
                "Earnings or financials": "Medium"},
    "Channel to watch": {"Partnership": "Medium", "Acquisition": "Medium"},
    "Competitor": {"New research product": "Medium", "Product or service launch": "Medium", "Partnership": "Medium",
                   "Acquisition": "Medium", "Leadership change": "Medium", "Earnings or financials": "Medium"},
}
OWNER_BY_RELATIONSHIP = {"Partner": "Partner GTM & Activation", "Competitor": "Leadership",
                         "Channel to watch": "Strategic Partner Development"}
ROUTE_ACTION = "Read the article and route it to the right director"
TRUSTED_SOURCES_PATH = "data/trusted_sources.txt"
SOURCE_WARNING = "Source not on the trusted list: verify the story with a trusted outlet before sharing"

MAX_ATTEMPTS = 2
RETRY_PAUSE_SECONDS = 2
COMPANY_PAUSE_SECONDS = 2
RELEVANCE_ORDER = {"High": 0, "Medium": 1, "Low": 2, "Unrated": 3}


def build_facts(entry: dict, items: list[dict]) -> str:
    lines = [f"Company: {entry['company']} ({entry['relationship']})",
             f"Watchlist note: {entry['why_watch']}", "Headlines:"]
    lines += [f"{n}. [{i['published']}, {i['source']}] {i['title']}" for n, i in enumerate(items, start=1)]
    return "\n".join(lines)


def unclassified(item: dict, reason: str) -> dict:
    return {**item, "signal_type": None, "relevance": "Unrated", "why_it_matters": None,
            "suggested_action": None, "owner": None, "judgment_source": reason, "also_covered_by": []}


def rule_relevance(relationship: str, signal_type: str) -> tuple[str, str]:
    level = RELEVANCE_RULES.get(relationship, {}).get(signal_type, "Low")
    return level, f"{relationship} + {signal_type} = {level} (rule table)"


def channel_term(entry: dict, title: str) -> str | None:
    """The first watchlist channel term the headline names, matched as a whole word."""
    terms = [t.strip() for t in (entry.get("channel_terms") or "").split(";") if t.strip()]
    return next((t for t in terms if re.search(rf"\b{re.escape(t)}\b", title, re.IGNORECASE)), None)


@lru_cache(maxsize=1)
def trusted_sources() -> frozenset[str]:
    """Outlets the team trusts, from an editable text file; comment lines start with #."""
    path = Path(TRUSTED_SOURCES_PATH)
    if not path.exists():
        return frozenset()
    lines = (line.strip() for line in path.read_text().splitlines())
    return frozenset(line.lower() for line in lines if line and not line.startswith("#"))


def is_trusted(source: str, entry: dict) -> bool:
    """True for a listed outlet or the company's own newsroom."""
    source = (source or "").lower()
    return entry["company"].split()[0].lower() in source or source in trusted_sources()


def finalize(row: dict, entry: dict) -> dict:
    """Set relevance from the rules, then make the action and owner fit that level."""
    row["relevance_basis"], row["rule_note"] = None, None
    row["source_check"] = None if is_trusted(row["source"], entry) else SOURCE_WARNING
    if row["judgment_source"] == "llm":
        row["relevance"], row["relevance_basis"] = rule_relevance(entry["relationship"], row["signal_type"])
    term = channel_term(entry, row["title"])
    if term:
        row["relevance"] = "High"
        row["rule_note"] = f"Raised to High by rule: the headline mentions '{term}', a term on IDC's channel watchlist"
        if row["why_it_matters"] is None:
            row["why_it_matters"] = "Not judged by AI; see the rule note."
    if row["relevance"] == "Low":
        row["suggested_action"], row["owner"] = "No action", "None"
    elif row["relevance"] in ("High", "Medium"):
        if not row["suggested_action"] or row["suggested_action"].strip().rstrip(".") == "No action":
            row["suggested_action"] = ROUTE_ACTION
        if row["owner"] in (None, "None"):
            row["owner"] = OWNER_BY_RELATIONSHIP.get(entry["relationship"], "Leadership")
    return row


def classify_company(entry: dict, items: list[dict]) -> list[dict]:
    """Classify one company's headlines in one LLM call, fold repeat coverage, then apply the rules."""
    if not items:
        return []
    facts = build_facts(entry, items)
    chain = PROMPT | get_llm().with_structured_output(CompanyJudgments)
    result, last_error = None, None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = chain.invoke({"facts": facts})
            break
        except Exception as err:  # provider errors vary (bad output, rate limits, timeouts)
            last_error = err
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_PAUSE_SECONDS)
    if result is None:
        print(f"  ! {entry['company']}: classification failed ({type(last_error).__name__}); headlines kept unclassified")
        return [finalize(unclassified(i, "not classified (LLM failed)"), entry) for i in items]

    by_index = {j.index: j for j in result.items}
    judged, row_of, lead_of = [], {}, {}
    for n, item in enumerate(items, start=1):
        j = by_index.get(n)
        target = j.same_story_as if j else None
        if target is not None and 1 <= target < n:
            lead = lead_of[target]
            lead_of[n] = lead
            judged[row_of[lead]]["also_covered_by"].append(
                {"source": item["source"], "title": item["title"], "link": item["link"]})
            continue
        lead_of[n], row_of[n] = n, len(judged)
        if j is None:
            row = unclassified(item, "not classified (no judgment returned)")
        else:
            invented = unsupported_numbers(f"{j.why_it_matters} {j.suggested_action}", facts)
            if invented:
                print(f"  ! {entry['company']} #{n}: judgment cited numbers not in the headline ({', '.join(invented)}); rejected")
                row = unclassified(item, f"rejected (cited numbers not in the headline: {', '.join(invented)})")
            else:
                row = {**item, **j.model_dump(exclude={"index", "same_story_as"}),
                       "judgment_source": "llm", "also_covered_by": []}
        judged.append(finalize(row, entry))
    return judged


def sources_line(item: dict) -> str:
    return ", ".join(f"[{c['source']}]({c['link']})" for c in item["also_covered_by"])


def render_markdown(brief: dict) -> str:
    """A one-page brief: what needs attention first, routine news last, failures stated plainly."""
    items = brief["items"]
    headlines = len(items) + sum(len(i["also_covered_by"]) for i in items)
    stories = f"{len(items)} {'story' if len(items) == 1 else 'stories'}"
    out = [f"# Partner intelligence brief: {brief['fetched_at'][:10]}", "",
           f"Built from {headlines} headlines ({stories}) fetched {brief['fetched_at']}, covering the last "
           f"{brief['lookback_days']} days. Headlines, sources, and dates are copied from the news feeds. "
           "Relevance comes from a rule table. Signal, why it matters, suggested action, and owner are AI judgment: "
           "verify before acting.", ""]
    for level, heading in (("High", "Needs attention"), ("Medium", "Worth knowing")):
        rows = [i for i in items if i["relevance"] == level]
        out += [f"## {heading} ({len(rows)})", ""]
        if not rows:
            out += ["Nothing this period.", ""]
        for i in rows:
            out += [f"- **{i['company']}** ({i['relationship']}): [{i['title']}]({i['link']}), {i['source']}, {i['published']}",
                    f"  - Signal: {i['signal_type'] or 'Not classified'} · Owner: {i['owner']}",
                    f"  - Why it matters: {i['why_it_matters']}",
                    f"  - Suggested action: {i['suggested_action']}"]
            if i.get("rule_note"):
                out.append(f"  - {i['rule_note']}")
            elif i.get("relevance_basis"):
                out.append(f"  - Why rated {i['relevance']}: {i['relevance_basis']}")
            if i.get("source_check"):
                out.append(f"  - {i['source_check']}")
            if i["judgment_source"] != "llm":
                out.append(f"  - AI judgment: {i['judgment_source']}")
            if i["also_covered_by"]:
                out.append(f"  - Also covered by: {sources_line(i)}")
        out.append("")
    low = [i for i in items if i["relevance"] == "Low"]
    out += [f"## Routine ({len(low)})", ""]
    out += [f"- {i['company']}: [{i['title']}]({i['link']}), {i['source']}, {i['published']} ({i['signal_type']})"
            + (f" (+{len(i['also_covered_by'])} more)" if i["also_covered_by"] else "") for i in low] + [""]
    unrated = [i for i in items if i["relevance"] == "Unrated"]
    if unrated:
        out += [f"## Not classified ({len(unrated)})", ""]
        out += [f"- {i['company']}: [{i['title']}]({i['link']}) ({i['judgment_source']})" for i in unrated] + [""]
    if brief["errors"]:
        out += ["## Feeds that failed", ""] + [f"- {e['company']}: {e['error']}" for e in brief["errors"]] + [""]
    return "\n".join(out)


def latest_snapshot() -> Path:
    snapshots = sorted(SNAPSHOT_DIR.glob("snapshot_*.json"))
    if not snapshots:
        raise FileNotFoundError("No snapshot found; run python -m src.intel_fetch first")
    return snapshots[-1]


def build_brief(snapshot_path: Path | None = None) -> Path:
    snapshot_path = Path(snapshot_path or latest_snapshot())
    snapshot = json.loads(snapshot_path.read_text())
    judged = []
    for n, entry in enumerate(load_watchlist()):
        items = [i for i in snapshot["items"] if i["company"] == entry["company"]]
        if n and items:
            time.sleep(COMPANY_PAUSE_SECONDS)  # stay inside free-tier rate limits
        judged += classify_company(entry, items)
    judged.sort(key=lambda i: i["published"], reverse=True)
    judged.sort(key=lambda i: (RELEVANCE_ORDER[i["relevance"]], i["company"]))

    brief = {"built_from": snapshot_path.name, "fetched_at": snapshot["fetched_at"],
             "lookback_days": snapshot["lookback_days"], "items": judged, "errors": snapshot["errors"]}
    stem = snapshot_path.stem.replace("snapshot", "brief")
    json_path = SNAPSHOT_DIR / f"{stem}.json"
    json_path.write_text(json.dumps(brief, indent=2))
    (SNAPSHOT_DIR / f"{stem}.md").write_text(render_markdown(brief))
    counts = {level: sum(i["relevance"] == level for i in judged) for level in RELEVANCE_ORDER}
    raised = sum(bool(i.get("rule_note")) for i in judged)
    print(f"Brief saved to {json_path} and {stem}.md: {len(judged)} stories {counts}, {raised} matched a channel term")
    return json_path


if __name__ == "__main__":
    build_brief()
