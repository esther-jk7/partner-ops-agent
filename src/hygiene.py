"""Pipeline hygiene: rules that flag partners needing attention, before and after signature."""

import json
from datetime import date, datetime

from src.triage import FIELD_LABELS

STALE_DAYS = 30
ACTIVATION_SLA_DAYS = 30
SEVERITY_BY_TIER = {"Priority": "High", "Nurture": "Medium", "Deprioritize": "Low"}
POST_SIGNATURE_STAGES = {"Signed", "Activating", "Live"}
NEEDS_SPONSOR_STAGES = {"Contracting", "Signed", "Activating", "Live"}

QUERY = """
SELECT o.opportunity_id, o.company, t.tier, t.score, t.missing_fields,
       p.stage, p.owner, p.last_contact_date, p.next_follow_up_date,
       p.owner_role, p.exec_sponsor, p.signed_date, p.activation_date
FROM opportunities o
JOIN triage_results t ON o.opportunity_id = t.opportunity_id
JOIN pipeline p ON o.opportunity_id = p.opportunity_id
"""

DELIVERABLES_QUERY = """
SELECT d.opportunity_id, o.company, t.tier, d.deliverable, d.owner, d.due_date, d.status
FROM deliverables d
JOIN opportunities o ON d.opportunity_id = o.opportunity_id
JOIN triage_results t ON d.opportunity_id = t.opportunity_id
WHERE d.status != 'Done'
"""


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date() if value else None


def days_ago(days: int) -> str:
    return f"{days} day ago" if days == 1 else f"{days} days ago"


def field(row, key):
    """Read a column that older rows or test fixtures might not have."""
    return row[key] if key in row.keys() else None


def make_issue(row, issue: str, detail: str, severity: str | None = None) -> dict:
    return {"opportunity_id": row["opportunity_id"], "company": row["company"], "tier": row["tier"],
            "severity": severity or SEVERITY_BY_TIER[row["tier"]], "issue": issue, "detail": detail}


def check_deal(row, today: date) -> list[dict]:
    """Return every hygiene issue found for one partner record."""
    issues = []
    stage = row["stage"]
    pre_signature = stage not in POST_SIGNATURE_STAGES
    follow_up = parse_date(row["next_follow_up_date"])
    last_contact = parse_date(row["last_contact_date"])
    signed = parse_date(field(row, "signed_date"))

    # Original five checks, same order. Stale and not-started apply only before signature.
    if follow_up and follow_up < today:
        issues.append(make_issue(row, "Overdue follow-up",
                                 f"Follow-up was due {follow_up} ({days_ago((today - follow_up).days)})"))
    if pre_signature and last_contact and (today - last_contact).days > STALE_DAYS:
        issues.append(make_issue(row, "Stale deal", f"No contact in {(today - last_contact).days} days"))
    if not row["owner"] and row["tier"] != "Deprioritize":
        issues.append(make_issue(row, "No owner", f"{row['tier']} deal has no one assigned"))
    if pre_signature and row["tier"] == "Priority" and stage == "New":
        issues.append(make_issue(row, "Priority deal not started", "High-scoring deal is still at stage 'New'"))
    missing = json.loads(row["missing_fields"] or "[]")
    if missing:
        issues.append(make_issue(row, "Incomplete record",
                                 f"Missing: {', '.join(FIELD_LABELS.get(f, f) for f in missing)}"))

    # Partnership checks. A signed partner that stalls is a commitment at risk, so these are always High.
    if stage in ("Signed", "Activating") and signed and not field(row, "activation_date"):
        waited = (today - signed).days
        if waited > ACTIVATION_SLA_DAYS:
            issues.append(make_issue(row, "Signed but not activated",
                                     f"Signed {signed} ({days_ago(waited)}), still not live", "High"))
    if stage in NEEDS_SPONSOR_STAGES and not field(row, "exec_sponsor"):
        issues.append(make_issue(row, "No exec sponsor",
                                 f"Partner is at '{stage}' with no IDC exec sponsor", "High"))

    return issues


def check_deliverables(conn, today: date) -> list[dict]:
    """Flag every unfinished partner deliverable that is past its due date."""
    issues = []
    for row in conn.execute(DELIVERABLES_QUERY):
        due = parse_date(row["due_date"])
        if due and due < today:
            issues.append(make_issue(
                row, "Overdue deliverable",
                f"'{row['deliverable']}' was due {due} ({days_ago((today - due).days)}); "
                f"status: {row['status']}, owner: {row['owner'] or 'unassigned'}",
                "High",
            ))
    return issues


def find_issues(conn, today: date | None = None) -> list[dict]:
    """Scan the whole pipeline and return all issues, most severe first."""
    today = today or date.today()
    issues = [issue for row in conn.execute(QUERY) for issue in check_deal(row, today)]
    issues += check_deliverables(conn, today)
    order = {"High": 0, "Medium": 1, "Low": 2}
    return sorted(issues, key=lambda i: order[i["severity"]])
