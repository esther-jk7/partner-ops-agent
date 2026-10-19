from datetime import date

from src.db import get_connection, init_db
from src.hygiene import days_ago, find_issues

TODAY = date(2026, 10, 16)


def make_db(tier, stage="Contacted", owner="Alex", last_contact=None, follow_up=None, missing="[]"):
    """Build a throwaway in-memory database holding one deal."""
    conn = get_connection(":memory:")
    init_db(conn)
    conn.execute("INSERT INTO opportunities (opportunity_id, company) VALUES ('T-1', 'Test Co')")
    conn.execute("INSERT INTO triage_results (opportunity_id, tier, missing_fields) VALUES ('T-1', ?, ?)",
                 (tier, missing))
    conn.execute("""INSERT INTO pipeline (opportunity_id, stage, owner, last_contact_date, next_follow_up_date)
                    VALUES ('T-1', ?, ?, ?, ?)""", (stage, owner, last_contact, follow_up))
    return conn


def issue_types(conn):
    return [i["issue"] for i in find_issues(conn, today=TODAY)]


def test_overdue_priority_deal_is_high_severity():
    issues = find_issues(make_db("Priority", follow_up="2026-10-01"), today=TODAY)
    assert issues[0]["issue"] == "Overdue follow-up"
    assert issues[0]["severity"] == "High"


def test_stale_deal_flagged_after_30_days():
    assert "Stale deal" in issue_types(make_db("Nurture", last_contact="2026-09-01"))
    assert "Stale deal" not in issue_types(make_db("Nurture", last_contact="2026-10-01"))


def test_priority_deal_at_new_with_no_owner():
    types = issue_types(make_db("Priority", stage="New", owner=None))
    assert "No owner" in types
    assert "Priority deal not started" in types


def test_deprioritized_deal_without_owner_not_flagged():
    assert issue_types(make_db("Deprioritize", stage="New", owner=None)) == []


def test_clean_deal_has_no_issues():
    assert issue_types(make_db("Nurture", last_contact="2026-10-10", follow_up="2026-10-20")) == []


def test_days_ago_grammar():
    assert days_ago(1) == "1 day ago"
    assert days_ago(5) == "5 days ago"
