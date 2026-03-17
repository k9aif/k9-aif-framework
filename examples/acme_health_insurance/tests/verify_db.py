# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# File: examples/acme_health_insurance/tests/verify_db.py

import sqlite3
from pathlib import Path
from pprint import pprint

try:
    from tabulate import tabulate
    USE_TABULATE = True
except ImportError:
    USE_TABULATE = False


def get_table_counts(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
    tables = [r[0] for r in cursor.fetchall()]
    summary = []
    for table in tables:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        summary.append((table, count))
    return summary


def show_sample(conn, table, limit=5):
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM {table} LIMIT {limit}")
    rows = cursor.fetchall()
    cols = [desc[0] for desc in cursor.description]
    if not rows:
        print(f"No data found in {table}")
        return
    print(f"\n📘 Sample from {table} (first {limit} rows):")
    if USE_TABULATE:
        print(tabulate(rows, headers=cols, tablefmt="fancy_grid"))
    else:
        pprint(rows)


def verify_database():
    db_path = Path(__file__).resolve().parents[1] / "acme_health_insurance.db"
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    print(f"Connected to database: {db_path}\n")

    summary = get_table_counts(conn)
    print("Table Record Counts:")
    if USE_TABULATE:
        print(tabulate(summary, headers=["Table", "Row Count"], tablefmt="github"))
    else:
        pprint(summary)

    # Show samples from key tables
    for t in ["members", "providers", "claims", "eligibility_checks"]:
        show_sample(conn, t)

    conn.close()
    print("\nVerification complete.")


if __name__ == "__main__":
    verify_database()
