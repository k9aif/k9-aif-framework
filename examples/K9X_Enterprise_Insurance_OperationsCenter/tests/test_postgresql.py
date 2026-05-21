# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
#
# PostgreSQL connectivity smoke test for K9-AIF persistence layer.

import unittest
import yaml
import psycopg2
from pathlib import Path


CONFIG_PATH = (
    Path(__file__).resolve().parent.parent
    / "config"
    / "config.yaml"
)


class TestPostgreSQLConnection(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(CONFIG_PATH, "r") as f:
            cls.config = yaml.safe_load(f)

        cls.pg = cls.config.get("postgres", {})

    def test_postgres_config_exists(self):
        self.assertIn("host", self.pg)
        self.assertIn("port", self.pg)
        self.assertIn("user", self.pg)
        self.assertIn("password", self.pg)
        self.assertIn("database", self.pg)

    def test_postgres_connection(self):
        conn = psycopg2.connect(
            host=self.pg["host"],
            port=self.pg["port"],
            user=self.pg["user"],
            password=self.pg["password"],
            dbname=self.pg["database"],
        )

        self.assertIsNotNone(conn)

        cur = conn.cursor()
        cur.execute("SELECT version();")

        row = cur.fetchone()

        self.assertIsNotNone(row)
        self.assertTrue("PostgreSQL" in row[0])

        print("\n[TEST] PostgreSQL version:")
        print(row[0])

        cur.close()
        conn.close()

    def test_schema_exists(self):
        schema_name = self.pg.get("schema", "public")

        conn = psycopg2.connect(
            host=self.pg["host"],
            port=self.pg["port"],
            user=self.pg["user"],
            password=self.pg["password"],
            dbname=self.pg["database"],
        )

        cur = conn.cursor()

        cur.execute(
            """
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name = %s
            """,
            (schema_name,),
        )

        row = cur.fetchone()

        self.assertIsNotNone(
            row,
            f"Schema '{schema_name}' does not exist"
        )

        print(f"\n[TEST] Schema exists: {schema_name}")

        cur.close()
        conn.close()


if __name__ == "__main__":
    unittest.main()