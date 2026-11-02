"""Tests for the partnership hygiene checks: activation SLA, exec sponsor, overdue deliverables."""

from datetime import date

from src.db import get_connection, init_db
from src.hygiene import check_deal, check_deliverables

TODAY = date(2026, 11, 4)


def partner(**overrides):
    """A healthy signed partner. Each test changes only the fields it cares about."""
    row = {"opportunity_id": "OPP-T1", "company": "Test Partner", "tier": "Priority", "score": 80,
           "missing_fields": "[]", "stage": "Signed", "owner": "Jordan Kim",
           "last_contact_date": "2026-10-30", "next_follow_up_date": "2026-11-20",
           "owner_role": "Partner GTM & Activation", "exec_sponsor": "Alan Mercer",
           "signed_date": "2026-10-20", "activation_date": None}
    row.update(overrides)
    return row


def issue_names(row):
    return [i["issue"] for i in check_deal(row, TODAY)]


def test_healthy_recently_signed_partner_has_no_issues():
    assert issue_names(partner()) == []


def test_signed_partner_past_sla_is_flagged_high():
    issues = check_deal(partner(signed_date="2026-09-15"), TODAY)
    flagged = [i for i in issues if i["issue"] == "Signed but not activated"]
    assert len(flagged) == 1
    assert flagged[0]["severity"] == "High"


def test_live_partner_is_not_flagged_as_stale_or_unactivated():
    row = partner(stage="Live", signed_date="2026-06-15", activation_date="2026-08-01",
                  last_contact_date="2026-09-15")
    names = issue_names(row)
    assert "Stale deal" not in names
    assert "Signed but not activated" not in names


def test_contracting_partner_without_sponsor_is_flagged_high():
    issues = check_deal(partner(stage="Contracting", signed_date=None, exec_sponsor=None), TODAY)
    flagged = [i for i in issues if i["issue"] == "No exec sponsor"]
    assert len(flagged) == 1
    assert flagged[0]["severity"] == "High"


def test_only_unfinished_overdue_deliverables_are_flagged():
    conn = get_connection(":memory:")
    init_db(conn)
    conn.execute("INSERT INTO opportunities (opportunity_id, company) VALUES ('OPP-T1', 'Test Partner')")
    conn.execute("INSERT INTO triage_results (opportunity_id, tier) VALUES ('OPP-T1', 'Nurture')")
    conn.executemany(
        "INSERT INTO deliverables (deliverable_id, opportunity_id, deliverable, owner, due_date, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [("D1", "OPP-T1", "Sandbox API credentials issued", "Jordan Kim", "2026-10-30", "In progress"),
         ("D2", "OPP-T1", "Kickoff call held", "Jordan Kim", "2026-10-01", "Done"),
         ("D3", "OPP-T1", "Joint webinar scheduled", "Jordan Kim", "2026-11-15", "Not started")],
    )
    issues = check_deliverables(conn, TODAY)
    assert len(issues) == 1
    assert "Sandbox API credentials issued" in issues[0]["detail"]
    assert issues[0]["severity"] == "High"
