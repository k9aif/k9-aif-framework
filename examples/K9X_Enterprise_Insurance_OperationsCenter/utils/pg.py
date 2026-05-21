# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — shared PostgreSQL helper

import os
from typing import Any, Dict

import psycopg2
import psycopg2.extras


def pg_cfg(config: Dict[str, Any]) -> Dict[str, Any]:
    """Build psycopg2 connect kwargs from config + env vars."""
    pg = config.get("postgres", {})
    schema = os.getenv("K9_PG_SCHEMA") or pg.get("schema", "eoc")
    return {
        "host":     os.getenv("K9_PG_HOST")     or pg.get("host",     "localhost"),
        "port":     int(os.getenv("K9_PG_PORT") or pg.get("port",     5432)),
        "dbname":   os.getenv("K9_PG_DB")       or pg.get("database", "eoc"),
        "user":     os.getenv("K9_PG_USER")     or pg.get("user",     "postgres"),
        "password": os.getenv("K9_PG_PASSWORD") or pg.get("password", ""),
        "options":  f"-c search_path={schema}",
    }


def pg_connect(config: Dict[str, Any]):
    """Return a psycopg2 connection using config + env vars."""
    return psycopg2.connect(**pg_cfg(config))


def pg_upsert(conn, table: str, row: Dict[str, Any], conflict_col: str) -> None:
    """INSERT … ON CONFLICT (conflict_col) DO UPDATE SET …"""
    cols   = list(row.keys())
    vals   = list(row.values())
    ph     = ", ".join(["%s"] * len(cols))
    sets   = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != conflict_col)
    sql    = (
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({ph}) "
        f"ON CONFLICT ({conflict_col}) DO UPDATE SET {sets}"
    )
    with conn.cursor() as cur:
        cur.execute(sql, vals)


def pg_insert_ignore(conn, table: str, row: Dict[str, Any], conflict_col: str) -> None:
    """INSERT … ON CONFLICT DO NOTHING"""
    cols = list(row.keys())
    vals = list(row.values())
    ph   = ", ".join(["%s"] * len(cols))
    sql  = (
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({ph}) "
        f"ON CONFLICT ({conflict_col}) DO NOTHING"
    )
    with conn.cursor() as cur:
        cur.execute(sql, vals)
