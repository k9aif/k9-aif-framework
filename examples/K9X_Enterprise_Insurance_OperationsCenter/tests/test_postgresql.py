# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
#
# PostgreSQL settings and connectivity for the EOC persistence layer.
# Settings come from config.yaml (${VAR} references) and the environment (.env):
# the password is K9_PG_PASSWORD, never a value in config.yaml. The connection
# tests run against the database named there and skip when none is reachable.

import unittest
from pathlib import Path

import psycopg2

from k9_aif_abb.k9_utils.config_loader import load_yaml
from examples.K9X_Enterprise_Insurance_OperationsCenter.utils.pg import pg_cfg

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "config.yaml"


class TestPostgreSQLConnection(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.config = load_yaml(str(CONFIG_PATH))
        cls.pg = cls.config.get("postgres", {})
        cls.kwargs = pg_cfg(cls.config)

    def _connect(self):
        try:
            return psycopg2.connect(**self.kwargs, connect_timeout=3)
        except psycopg2.OperationalError as exc:
            self.skipTest(f"no PostgreSQL reachable at {self.kwargs['host']}:{self.kwargs['port']} ({exc})")

    def test_postgres_config_exists(self):
        for key in ("host", "port", "user", "database", "schema"):
            self.assertIn(key, self.pg)
        # Secrets live in the environment (.env), not in config.yaml.
        self.assertNotIn("password", self.pg)

    def test_postgres_connection(self):
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute("SELECT version();")
            row = cur.fetchone()
        conn.close()
        self.assertIn("PostgreSQL", row[0])

    def test_schema_exists(self):
        schema_name = self.pg.get("schema", "public")
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name = %s",
                        (schema_name,))
            row = cur.fetchone()
        conn.close()
        self.assertIsNotNone(row, f"Schema '{schema_name}' does not exist")


if __name__ == "__main__":
    unittest.main()
