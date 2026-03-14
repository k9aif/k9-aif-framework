-- SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
-- K9-AIF™ — Acme Health Insurance Experience Center Schema

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS members (
    member_id      TEXT PRIMARY KEY,
    first_name     TEXT,
    last_name      TEXT,
    dob            TEXT,
    plan           TEXT,
    city           TEXT,
    state          TEXT,
    zip_code       TEXT,
    phone          TEXT,
    email          TEXT,
    created_at     TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS providers (
    provider_id    TEXT PRIMARY KEY,
    name           TEXT,
    specialty      TEXT,
    address        TEXT,
    city           TEXT,
    state          TEXT,
    zip_code       TEXT,
    phone          TEXT,
    npi_number     TEXT,
    created_at     TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS claims (
    claim_id       TEXT PRIMARY KEY,
    member_id      TEXT,
    provider       TEXT,
    amount         REAL,
    status         TEXT,
    submitted_at   TEXT,
    FOREIGN KEY(member_id) REFERENCES members(member_id)
);

CREATE TABLE IF NOT EXISTS eligibility_checks (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id      TEXT,
    plan           TEXT,
    verified_by    TEXT,
    verified_at    TEXT,
    status         TEXT,
    FOREIGN KEY(member_id) REFERENCES members(member_id)
);

CREATE TABLE IF NOT EXISTS policy_queries (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id      TEXT,
    question       TEXT,
    answer         TEXT,
    created_at     TEXT,
    FOREIGN KEY(member_id) REFERENCES members(member_id)
);

CREATE TABLE IF NOT EXISTS notifications (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient      TEXT,
    event          TEXT,
    sent_at        TEXT,
    status         TEXT
);

CREATE TABLE IF NOT EXISTS event_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    event          TEXT,
    agent          TEXT,
    logged_at      TEXT
);

CREATE TABLE IF NOT EXISTS governance_audit (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    component      TEXT,
    action         TEXT,
    policy         TEXT,
    checked_at     TEXT,
    result         TEXT
);

CREATE TABLE IF NOT EXISTS geo_areas (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    area_code      TEXT,
    zip_code       TEXT,
    city           TEXT,
    county         TEXT,
    state          TEXT,
    population     INTEGER,
    created_at     TEXT DEFAULT CURRENT_TIMESTAMP
);