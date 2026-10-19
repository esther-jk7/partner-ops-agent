"""SQLite database for opportunities, triage results, and pipeline status."""

import json
import sqlite3
from datetime import datetime

DB_PATH = "data/pipeline.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
    opportunity_id TEXT PRIMARY KEY,
    company TEXT NOT NULL,
    partner_type TEXT,
    industry TEXT,
    region TEXT,
    employees INTEGER,
    est_annual_value_usd REAL,
    source TEXT,
    submitted_date TEXT,
    description TEXT
);

CREATE TABLE IF NOT EXISTS triage_results (
    opportunity_id TEXT PRIMARY KEY REFERENCES opportunities(opportunity_id),
    score INTEGER,
    tier TEXT,
    rationale TEXT,
    next_action TEXT,
    missing_fields TEXT,
    scored_at TEXT
);

CREATE TABLE IF NOT EXISTS pipeline (
    opportunity_id TEXT PRIMARY KEY REFERENCES opportunities(opportunity_id),
    stage TEXT DEFAULT 'New',
    owner TEXT,
    last_contact_date TEXT,
    next_follow_up_date TEXT
);
"""


def get_connection(path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def save_triage(conn: sqlite3.Connection, result: dict) -> None:
    """Insert or update the triage result for one opportunity."""
    conn.execute(
        """INSERT OR REPLACE INTO triage_results
           (opportunity_id, score, tier, rationale, next_action, missing_fields, scored_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (result["opportunity_id"], result["score"], result["tier"], result.get("rationale"),
         result.get("next_action"), json.dumps(result["missing_fields"]),
         datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
