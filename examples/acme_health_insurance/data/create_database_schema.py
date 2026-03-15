# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# File: examples/acme_health_insurance/data/create_database_schema.py

import sqlite3
from pathlib import Path


def create_database():
    """
    Initializes the Acme Health Insurance Experience Center database
    using any *schema.sql file and all other .sql files in this folder.
    Automatically disables FK checks while seeding.
    """

    data_dir = Path(__file__).parent

    # Auto-detect schema file (e.g., 000_schema.sql or schema.sql)
    schema_candidates = sorted(data_dir.glob("*schema.sql"))
    if not schema_candidates:
        raise FileNotFoundError(f"No schema file found in {data_dir}")
    schema_file = schema_candidates[0]

    # Database path (consistent with config.yaml / PersistenceAgent)
    db_path = data_dir.parent / "acme_health_insurance.db"

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print(f" Creating Acme Health Insurance schema from {schema_file.name}")
    with open(schema_file, "r") as f:
        cursor.executescript(f.read())

    # -----------------------------------------------------------
    # Disable foreign-key enforcement for unordered seeding
    # -----------------------------------------------------------
    cursor.execute("PRAGMA foreign_keys = OFF;")

    for seed_file in sorted(data_dir.glob("*.sql")):
        if seed_file.name == schema_file.name:
            continue
        print(f" Seeding data from {seed_file.name}")
        with open(seed_file, "r") as f:
            cursor.executescript(f.read())

    cursor.execute("PRAGMA foreign_keys = ON;")

    conn.commit()
    conn.close()
    print(f" Database initialized successfully at: {db_path}")


if __name__ == "__main__":
    create_database()
