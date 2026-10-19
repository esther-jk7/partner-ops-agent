"""Load the sample data into SQLite, triage every opportunity, and save the results."""

import pandas as pd

from src.db import get_connection, init_db, save_triage
from src.triage import triage


def load_table(conn, csv_path: str, table: str) -> pd.DataFrame:
    """Copy a CSV into a database table, turning blank cells into NULL."""
    df = pd.read_csv(csv_path)
    df = df.astype(object).where(pd.notna(df), None)
    columns = list(df.columns)
    placeholders = ", ".join("?" * len(columns))
    conn.executemany(
        f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
        df.itertuples(index=False, name=None),
    )
    conn.commit()
    return df


def main():
    conn = get_connection()
    init_db(conn)
    opportunities = load_table(conn, "data/inbound_opportunities.csv", "opportunities")
    load_table(conn, "data/pipeline_status.csv", "pipeline")

    for opp in opportunities.to_dict("records"):
        result = triage(opp)
        save_triage(conn, result)
        print(f"{result['opportunity_id']}  {result['company']:<30} {result['score']:>3}  {result['tier']}")

    conn.close()
    print("\nSaved all results to data/pipeline.db")


if __name__ == "__main__":
    main()
