"""Measure the follow-up Validator on hand-written drafts: 20 with one planted error each, 10 clean.

Reports how many planted errors it caught (and how many of those it caught by quoting the planted
claim), how many clean drafts it wrongly flagged, and any failed model calls. Results are saved
with the date and model name, so runs can be compared over time.
"""

import json
import os
import sys
import time
from datetime import date
from pathlib import Path

from src.validator import validate_draft

CASES_PATH = Path(sys.argv[1] if len(sys.argv) > 1 else "evals/validator_cases.json")
RESULTS_DIR = Path("evals/results")
PAUSE_SECONDS = 2


def model_name() -> str:
    provider = os.getenv("LLM_PROVIDER", "groq")
    if provider == "anthropic":
        return os.getenv("ANTHROPIC_MODEL", "anthropic default")
    return os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")


def main():
    spec = json.loads(CASES_PATH.read_text())
    rows = []
    for n, case in enumerate(spec["cases"], start=1):
        try:
            verdict = validate_draft(spec["deals"][case["deal"]], {"subject": case["subject"], "body": case["body"]})
            error = "validator failed closed" if verdict.get("error") else None
        except Exception as err:  # record failed calls instead of stopping the run
            verdict, error = {"passed": None, "problems": []}, type(err).__name__
        marker = case.get("marker")
        quoted = bool(marker) and any(marker.lower() in p.lower() for p in verdict["problems"])
        rows.append({"id": case["id"], "error_type": case.get("error_type"), "marker": marker,
                     "passed": verdict["passed"], "problems": verdict["problems"], "quoted": quoted, "error": error})
        status = "ERROR" if error else ("pass" if verdict["passed"] else "FLAG")
        print(f"{n:>2}/{len(spec['cases'])} {case['id']:<5} {status:<5} {case.get('error_type') or 'clean'}")
        time.sleep(PAUSE_SECONDS)

    planted = [r for r in rows if r["error_type"] and not r["error"]]
    clean = [r for r in rows if not r["error_type"] and not r["error"]]
    caught = [r for r in planted if r["passed"] is False]
    missed = [r for r in planted if r["passed"] is True]
    false_alarms = [r for r in clean if r["passed"] is False]
    summary = {
        "case_set": CASES_PATH.name, "date": date.today().isoformat(), "model": model_name(),
        "planted_caught": f"{len(caught)}/{len(planted)}",
        "caught_quoting_the_planted_claim": f"{sum(r['quoted'] for r in caught)}/{len(planted)}",
        "false_alarms_on_clean_drafts": f"{len(false_alarms)}/{len(clean)}",
        "failed_model_calls": sum(bool(r["error"]) for r in rows),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{CASES_PATH.stem}_{summary['date']}.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))

    print("\n" + "\n".join(f"{k}: {v}" for k, v in summary.items()))
    for r in missed:
        print(f"MISSED       {r['id']} ({r['error_type']}): planted '{r['marker']}'")
    for r in false_alarms:
        print(f"FALSE ALARM  {r['id']}: {r['problems']}")
    for r in caught:
        if not r["quoted"]:
            print(f"CAUGHT, NOT QUOTED {r['id']} ({r['error_type']}): {r['problems']}")
    print(f"Saved to {out}")


if __name__ == "__main__":
    main()
