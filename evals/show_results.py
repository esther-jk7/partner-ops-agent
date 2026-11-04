"""Print a short summary of the saved eval results."""
import json
from pathlib import Path

RESULTS = Path(__file__).parent / "results"

def load(name):
    return json.loads((RESULTS / name).read_text())

print("\nValidator results")
for name, label in [("validator_cases_2026-11-02.json", "Standard set"),
                    ("validator_cases_hard_2026-11-02.json", "Hard set")]:
    s = load(name)["summary"]
    print(f"  {label}: caught {s['planted_caught']} planted errors | "
          f"false alarms on clean drafts {s['false_alarms_on_clean_drafts']} | "
          f"failed model calls {s['failed_model_calls']}")

print("\nHard set: the miss and the strict flag")
for r in load("validator_cases_hard_2026-11-02.json")["rows"]:
    if r["id"] == "H-E5":
        print(f"  {r['id']} ({r['error_type']}): not caught")
    if r["id"] == "H-C4":
        print(f"  {r['id']} (labeled clean): flagged -> {r['problems'][0][:160]}")

s = load("brief_stability_2026-11-02.json")["summary"]
print(f"\nIntel brief stability over {s['runs']} runs: "
      f"{s['same_relevance_every_run']} same relevance | "
      f"{s['same_signal_type_every_run']} same signal type\n")
