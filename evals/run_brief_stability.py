"""Classify the same snapshot several times and measure how stable the brief is.

For each headline: did it get the same relevance and the same signal type on every run?
Relevance comes from the rule table, so it can only change when the model's signal type
crosses a rule boundary.
"""

import json
import sys
import time
from datetime import date
from pathlib import Path

from src.intel_brief import COMPANY_PAUSE_SECONDS, classify_company, latest_snapshot
from src.intel_fetch import load_watchlist

RUNS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
RESULTS_DIR = Path("evals/results")


def one_run(snapshot: dict) -> tuple[dict, int]:
    """Map every headline (including folded repeats) to its (relevance, signal type) for one run."""
    ratings, stories = {}, 0
    for n, entry in enumerate(load_watchlist()):
        items = [i for i in snapshot["items"] if i["company"] == entry["company"]]
        if n and items:
            time.sleep(COMPANY_PAUSE_SECONDS)
        for row in classify_company(entry, items):
            stories += 1
            for title in [row["title"]] + [c["title"] for c in row["also_covered_by"]]:
                ratings[title] = (row["relevance"], row["signal_type"])
    return ratings, stories


def main():
    snapshot_path = latest_snapshot()
    snapshot = json.loads(snapshot_path.read_text())
    runs, story_counts = [], []
    for r in range(1, RUNS + 1):
        ratings, stories = one_run(snapshot)
        runs.append(ratings)
        story_counts.append(stories)
        print(f"Run {r}: {stories} stories")

    titles = [i["title"] for i in snapshot["items"]]
    per_title = {t: [run.get(t, (None, None)) for run in runs] for t in titles}
    relevance_changed = {t: [r for r, _ in v] for t, v in per_title.items() if len({r for r, _ in v}) > 1}
    signal_changed = {t: [s for _, s in v] for t, v in per_title.items() if len({s for _, s in v}) > 1}
    harmless = [t for t in signal_changed if t not in relevance_changed]

    summary = {
        "snapshot": snapshot_path.name, "date": date.today().isoformat(), "runs": RUNS,
        "same_relevance_every_run": f"{len(titles) - len(relevance_changed)}/{len(titles)}",
        "same_signal_type_every_run": f"{len(titles) - len(signal_changed)}/{len(titles)}",
        "signal_changed_but_relevance_did_not": len(harmless),
        "stories_per_run": story_counts,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"brief_stability_{summary['date']}.json"
    out.write_text(json.dumps({"summary": summary, "relevance_changed": relevance_changed,
                               "signal_changed": signal_changed}, indent=2))

    print("\n" + "\n".join(f"{k}: {v}" for k, v in summary.items()))
    for t, levels in relevance_changed.items():
        print(f"RELEVANCE CHANGED  {t[:70]}: {levels}")
    print(f"Saved to {out}")


if __name__ == "__main__":
    main()
