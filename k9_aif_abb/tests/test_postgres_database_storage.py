# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
Tests for PostgresDatabaseStorage's URL construction -- G-20.

A bare "postgresql://" scheme lets SQLAlchemy pick whichever driver is
its own current default -- SQLAlchemy 2.1 changed that default from
psycopg2 to psycopg (v3), while this framework's `postgres` extra only
ships psycopg2-binary. A fresh install then fails with
ModuleNotFoundError: psycopg on first real connect. create_engine()
itself is mocked here (no real Postgres needed) -- these tests exist to
pin the URL scheme, the actual bug surface, not to prove connectivity.
"""

from unittest.mock import patch

from k9_aif_abb.k9_storage.postgres_database_storage import PostgresDatabaseStorage


def _make_storage(config=None):
    with patch("k9_aif_abb.k9_storage.postgres_database_storage.create_engine") as mock_engine:
        storage = PostgresDatabaseStorage(config=config or {})
    return storage, mock_engine


class TestDatabaseUrlDriver:

    def test_default_url_names_psycopg2_explicitly(self):
        """The actual G-20 assertion: no bare "postgresql://" -- the
        driver must be explicit regardless of which SQLAlchemy version
        happens to resolve at install time."""
        storage, _ = _make_storage()
        assert storage.database_url.startswith("postgresql+psycopg2://")
        assert not storage.database_url.startswith("postgresql://postgres")

    def test_driver_matches_the_installed_extra_by_default(self):
        """postgres.driver defaults to psycopg2 -- the driver this
        framework's own `postgres` extra (psycopg2-binary) actually
        installs, not psycopg v3."""
        storage, _ = _make_storage()
        assert storage.driver == "psycopg2"

    def test_driver_overridable_via_config(self):
        """Anyone with psycopg v3 installed by other means can opt in
        without a framework code change."""
        storage, _ = _make_storage(config={"postgres": {"driver": "psycopg"}})
        assert storage.driver == "psycopg"
        assert storage.database_url.startswith("postgresql+psycopg://")

    def test_credentials_and_host_still_present_in_url(self):
        storage, _ = _make_storage(config={
            "postgres": {"host": "db.example.com", "port": 5433, "user": "k9x", "database": "k9hil"},
        })
        assert "db.example.com:5433" in storage.database_url
        assert "k9x" in storage.database_url
        assert storage.database_url.endswith("/k9hil")

    def test_engine_constructed_with_the_driver_qualified_url(self):
        """The URL that actually reaches create_engine() -- not just the
        stored attribute -- must carry the explicit driver."""
        storage, mock_engine = _make_storage()
        args, _ = mock_engine.call_args
        assert args[0].startswith("postgresql+psycopg2://")
