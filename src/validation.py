"""Check CRM-export CSVs before they reach the database.

Errors reject the row. Warnings keep the row but clear the bad value.
Every issue goes into data/data_quality_report.csv, so nothing is dropped silently.
"""

import re

import pandas as pd

REPORT_PATH = "data/data_quality_report.csv"

ID_COLUMNS = {
    "opportunities": "opportunity_id",
    "pipeline": "opportunity_id",
    "deliverables": "deliverable_id",
}
DATE_COLUMNS = {
    "opportunities": ["submitted_date"],
    "pipeline": ["last_contact_date", "next_follow_up_date", "signed_date", "activation_date"],
    "deliverables": ["due_date", "completed_date"],
}
NUMBER_COLUMNS = {"opportunities": ["employees", "est_annual_value_usd"]}
SOFT_ALLOWED_VALUES = {
    "opportunities": {
        "partnership_model": {"Platform distribution", "Data alliance", "Content licensing",
                              "Co-marketing", "Client request"},
        "revenue_model": {"Licensing", "Revenue share", "Sponsorship", "No revenue", "Client purchase"},
        "integration_effort": {"Low", "Medium", "High"},
        "wants_model_training": {"Yes", "No", "Unknown"},
    },
}
ALLOWED_VALUES = {
    "pipeline": {"stage": {"New", "Contacted", "Meeting scheduled", "Proposal sent",
                           "Contracting", "Signed", "Activating", "Live"}},
    "deliverables": {"status": {"Not started", "In progress", "Blocked", "Done"}},
}
POST_SIGNATURE_STAGES = {"Signed", "Activating", "Live"}
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_issues = []


def _log(table, row_id, severity, field, issue):
    _issues.append({"table": table, "row_id": row_id, "severity": severity,
                    "field": field, "issue": issue})


def _blank(value) -> bool:
    return pd.isna(value) or str(value).strip() == ""


def validate(df: pd.DataFrame, table: str, conn) -> pd.DataFrame:
    """Return only the rows that are safe to load, logging every problem found."""
    df = df.copy()
    for col in DATE_COLUMNS.get(table, []) + NUMBER_COLUMNS.get(table, []):
        if col in df:
            df[col] = df[col].astype(object)

    id_col = ID_COLUMNS[table]
    known_opps = None
    if table in ("pipeline", "deliverables"):
        known_opps = {r[0] for r in conn.execute("SELECT opportunity_id FROM opportunities")}

    seen, keep = set(), []
    for idx, row in df.iterrows():
        row_id = row.get(id_col)

        # Errors: the row can't be trusted, so it is rejected.
        if _blank(row_id):
            _log(table, f"CSV line {idx + 2}", "error", id_col, "missing ID; row rejected")
            continue
        if row_id in seen:
            _log(table, row_id, "error", id_col, "duplicate ID; row rejected")
            continue
        seen.add(row_id)
        if known_opps is not None and row.get("opportunity_id") not in known_opps:
            _log(table, row_id, "error", "opportunity_id", "no matching opportunity; row rejected")
            continue
        bad_value = False
        for col, allowed in ALLOWED_VALUES.get(table, {}).items():
            if not _blank(row.get(col)) and row.get(col) not in allowed:
                _log(table, row_id, "error", col, f"unknown value '{row.get(col)}'; row rejected")
                bad_value = True
        if bad_value:
            continue

        # Warnings: the row is kept, but the bad value is cleared.
        for col in DATE_COLUMNS.get(table, []):
            value = row.get(col)
            if not _blank(value) and not DATE_PATTERN.match(str(value)):
                _log(table, row_id, "warning", col, f"bad date '{value}' (expected YYYY-MM-DD); value cleared")
                df.at[idx, col] = None
        for col in NUMBER_COLUMNS.get(table, []):
            value = row.get(col)
            number = pd.to_numeric(value, errors="coerce")
            if not _blank(value) and (pd.isna(number) or number < 0):
                _log(table, row_id, "warning", col, f"invalid number '{value}'; value cleared")
                df.at[idx, col] = None
        for col, allowed in SOFT_ALLOWED_VALUES.get(table, {}).items():
            value = row.get(col)
            if not _blank(value) and value not in allowed:
                _log(table, row_id, "warning", col, f"unknown value '{value}'; value cleared")
                df.at[idx, col] = None
        if table == "pipeline" and row.get("stage") in POST_SIGNATURE_STAGES and _blank(row.get("signed_date")):
            _log(table, row_id, "warning", "signed_date", f"stage is '{row.get('stage')}' but no signed date")

        keep.append(idx)

    clean = df.loc[keep].copy()
    for col in NUMBER_COLUMNS.get(table, []):
        if col in clean:
            clean[col] = pd.to_numeric(clean[col], errors="coerce")
    return clean


def write_report(path: str = REPORT_PATH) -> pd.DataFrame:
    """Write all logged issues to a CSV, print a one-line summary, and reset the log."""
    report = pd.DataFrame(_issues, columns=["table", "row_id", "severity", "field", "issue"])
    report.to_csv(path, index=False)
    errors = int((report["severity"] == "error").sum())
    warnings = int((report["severity"] == "warning").sum())
    print(f"Data quality: {errors} rows rejected, {warnings} warnings (details in {path})")
    _issues.clear()
    return report
