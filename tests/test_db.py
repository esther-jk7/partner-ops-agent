"""Triage results round-trip through the database with their reasons and flags intact."""

import json

import pandas as pd

from src.db import get_connection, init_db, save_triage
from src.scoring import score_opportunity

GATED = pd.read_csv("data/inbound_opportunities.csv").to_dict("records")[0]  # OPP-001


def test_triage_result_round_trips_with_flags():
    conn = get_connection(":memory:")
    init_db(conn)
    result = {**score_opportunity(GATED), "rationale": "Test rationale.",
              "next_action": "Hold outreach until reviewed", "explanation_source": "llm"}
    save_triage(conn, result)
    row = conn.execute("SELECT * FROM triage_results WHERE opportunity_id = 'OPP-001'").fetchone()
    assert row["needs_review"] == 1
    assert row["route_to_sales"] == 0
    assert json.loads(row["review_reasons"])[0].startswith("Data rights")
    assert len(json.loads(row["reasons"])) == 6
    assert row["explanation_source"] == "llm"
