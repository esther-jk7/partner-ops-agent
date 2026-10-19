"""Pipeline hygiene: rules that flag deals needing attention."""

import json
from datetime import date, datetime

from src.triage import FIELD_LABELS

STALE_DAYS = 30
SEVERITY_BY_TIER = {"Priority": "High", "Nurture": "Medium", "Deprioritize": "Low"}

QUERY = """
SELECT o.opportunity_id, o.company, t.tier, t.score, t.missing_fields,
       p.stage, p.owner, p.last_contact_date, p.next_follow_up_date
FROM opportunities o
JOIN triage_results t ON o.opportunity_id = t.opportunity_id
JOIN pipeline p ON o.opportunity_id = p.opportunity_id
"""


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date() if value else None


def days_ago(days: int) -> str:
    return f"{days} day ago" if days == 1 else f"{days} days ago"


def check_deal(row, today: date) -> list[dict]:
    """Return every hygiene issue found for one deal."""
    issues = []
    follow_up = parse_date(row["next_follow_up_date"])
    last_contact = parse_date(row["last_contact_date"])

    if follow_up and follow_up < today:
        issues.append(("Overdue follow-up", f"Follow-up was due {follow_up} ({days_ago((today - follow_up).days)})"))
    if last_contact and (today - last_contact).days > STALE_DAYS:
        issues.append(("Stale deal", f"No contact in {(today - last_contact).days} days"))
    if not row["owner"] and row["tier"] != "Deprioritize":
        issues.append(("No owner", f"{row['tier']} deal has no one assigned"))
    if row["tier"] == "Priority" and row["stage"] == "New":
        issues.append(("Priority deal not started", "High-scoring deal is still at stage 'New'"))
    missing = json.loads(row["missing_fields"] or "[]")
    if missing:
        issues.append(("Incomplete record", f"Missing: {', '.join(FIELD_LABELS.get(f, f) for f in missing)}"))

    return [
        {"opportunity_id": row["opportunity_id"], "company": row["company"], "tier": row["tier"],
         "severity": SEVERITY_BY_TIER[row["tier"]], "issue": issue, "detail": detail}
        for issue, detail in issues
    ]


def find_issues(conn, today: date | None = None) -> list[dict]:
    """Scan the whole pipeline and return all issues, most severe first."""
    today = today or date.today()
    issues = [issue for row in conn.execute(QUERY) for issue in check_deal(row, today)]
    order = {"High": 0, "Medium": 1, "Low": 2}
    return sorted(issues, key=lambda i: order[i["severity"]])
