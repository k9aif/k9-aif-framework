-- SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
-- K9-AIF™ — Seed ZIP Code Reference Data (Austin, TX)

CREATE TABLE IF NOT EXISTS zipcodes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    zip_code    TEXT,
    city        TEXT,
    county      TEXT,
    state       TEXT,
    area_code   TEXT,
    region_name TEXT,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO zipcodes (zip_code, city, county, state, area_code, region_name) VALUES
('78701', 'Austin', 'Travis', 'TX', '512', 'Downtown / Texas Capitol'),
('78702', 'Austin', 'Travis', 'TX', '512', 'East Austin'),
('78703', 'Austin', 'Travis', 'TX', '512', 'Tarrytown / Clarksville'),
('78704', 'Austin', 'Travis', 'TX', '737', 'South Congress / Barton Hills'),
('78705', 'Austin', 'Travis', 'TX', '737', 'University of Texas / Hyde Park'),
('78723', 'Austin', 'Travis', 'TX', '512', 'Mueller / Windsor Park'),
('78731', 'Austin', 'Travis', 'TX', '512', 'Northwest Hills'),
('78745', 'Austin', 'Travis', 'TX', '737', 'South Austin / Cherry Creek'),
('78746', 'Austin', 'Travis', 'TX', '512', 'West Lake Hills'),
('78759', 'Austin', 'Travis', 'TX', '512', 'Arboretum / Great Hills');