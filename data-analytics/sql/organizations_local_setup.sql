-- Local-only schema + seed data for developing/testing the Organization Analytics API.
-- Mirrors ddl_organizations.sql / ddl_state.sql from saayam-for-all/database, minus the
-- org_id sequence/trigger (we insert explicit org_id values instead) and minus the FK to
-- `country`, since we're not standing up that whole table just for this.
-- Safe to re-run: types/tables are guarded, inserts use ON CONFLICT DO NOTHING.

CREATE SCHEMA IF NOT EXISTS virginia_dev_saayam_rdbms;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'org_type_enum') THEN
        CREATE TYPE org_type_enum AS ENUM ('non_profit', 'for_profit');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'org_size_enum') THEN
        CREATE TYPE org_size_enum AS ENUM ('small', 'medium', 'large');
    END IF;
END$$;

CREATE TABLE IF NOT EXISTS virginia_dev_saayam_rdbms.state (
    state_id VARCHAR(50) PRIMARY KEY,
    country_id INT NOT NULL,
    state_name VARCHAR(100) NOT NULL,
    state_code VARCHAR(6),
    last_update_date TIMESTAMP
);

CREATE TABLE IF NOT EXISTS virginia_dev_saayam_rdbms.organizations (
    org_id VARCHAR(255) PRIMARY KEY,
    org_name VARCHAR(125) NOT NULL,
    street VARCHAR(255),
    city_name VARCHAR(100),
    state_id VARCHAR(50),
    zip_code VARCHAR(10),
    mission TEXT,
    web_url VARCHAR(255) CHECK (web_url IS NULL OR web_url LIKE 'http%'),
    phone VARCHAR(20),
    email VARCHAR(255) CHECK (email IS NULL OR email LIKE '%@%'),
    org_type org_type_enum,
    org_size org_size_enum,
    org_rating INTEGER CHECK (org_rating >= 1 AND org_rating <= 5),
    is_collaborator BOOLEAN,
    is_contributor BOOLEAN,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'UTC'),
    last_updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'UTC'),
    FOREIGN KEY (state_id) REFERENCES virginia_dev_saayam_rdbms.state(state_id) ON DELETE SET NULL
);

-- Covers the case where this script already ran before is_contributor existed:
-- CREATE TABLE IF NOT EXISTS is a no-op on an existing table, so the column
-- needs its own guarded ADD.
ALTER TABLE virginia_dev_saayam_rdbms.organizations
    ADD COLUMN IF NOT EXISTS is_contributor BOOLEAN;

CREATE INDEX IF NOT EXISTS idx_org_name ON virginia_dev_saayam_rdbms.organizations(org_name);
CREATE INDEX IF NOT EXISTS idx_org_state_id ON virginia_dev_saayam_rdbms.organizations(state_id);
CREATE INDEX IF NOT EXISTS idx_org_city_state ON virginia_dev_saayam_rdbms.organizations(city_name, state_id);

INSERT INTO virginia_dev_saayam_rdbms.state (state_id, country_id, state_name, state_code, last_update_date) VALUES
    ('VA', 1, 'Virginia', 'VA', now()),
    ('NY', 1, 'New York', 'NY', now()),
    ('CA', 1, 'California', 'CA', now()),
    ('TX', 1, 'Texas', 'TX', now()),
    ('IL', 1, 'Illinois', 'IL', now())
ON CONFLICT (state_id) DO NOTHING;

-- created_at is seeded relative to "now" (not hardcoded dates) so the 7D/30D/1Y/ALL time
-- filters and daily/weekly/monthly/yearly grouping all have real data every time this runs.
-- is_contributor is deliberately NOT a copy of is_collaborator on every row --
-- keeping them independent is what actually exercises that the two filters/
-- distributions are querying different columns instead of coincidentally
-- agreeing because the seed data always sets them the same way.
INSERT INTO virginia_dev_saayam_rdbms.organizations
    (org_id, org_name, city_name, state_id, org_type, org_size, org_rating, is_collaborator, is_contributor, created_at) VALUES
    ('ORG-LOCAL-001', 'Helping Hands VA',        'Ashburn',    'VA', 'non_profit', 'small',  5,    TRUE,  TRUE,  now() - INTERVAL '1 day'),
    ('ORG-LOCAL-002', 'Community Bridge NY',      'Albany',     'NY', 'non_profit', 'medium', 4,    TRUE,  FALSE, now() - INTERVAL '3 days'),
    ('ORG-LOCAL-003', 'Bright Future CA',         'Sacramento', 'CA', 'non_profit', 'large',  NULL, FALSE, TRUE,  now() - INTERVAL '5 days'),
    ('ORG-LOCAL-004', 'TechForGood TX',           'Austin',     'TX', 'for_profit', 'medium', 3,    FALSE, FALSE, now() - INTERVAL '6 days'),
    ('ORG-LOCAL-005', 'Neighbor Network IL',      'Chicago',    'IL', 'non_profit', 'small',  5,    TRUE,  TRUE,  now() - INTERVAL '10 days'),
    ('ORG-LOCAL-006', 'Care Collective VA',       'Richmond',   'VA', 'non_profit', 'medium', 2,    FALSE, TRUE,  now() - INTERVAL '18 days'),
    ('ORG-LOCAL-007', 'Urban Uplift NY',          'Buffalo',    'NY', 'for_profit', 'small',  NULL, FALSE, FALSE, now() - INTERVAL '22 days'),
    ('ORG-LOCAL-008', 'Golden State Aid CA',      'Fresno',     'CA', 'non_profit', 'large',  4,    TRUE,  FALSE, now() - INTERVAL '28 days'),
    ('ORG-LOCAL-009', 'Lone Star Volunteers TX',  'Houston',    'TX', 'non_profit', 'medium', 3,    TRUE,  TRUE,  now() - INTERVAL '45 days'),
    ('ORG-LOCAL-010', 'Prairie Partners IL',      'Springfield','IL', 'for_profit', 'large',  2,    FALSE, TRUE,  now() - INTERVAL '70 days'),
    ('ORG-LOCAL-011', 'Capitol Care VA',          'Alexandria', 'VA', 'non_profit', 'small',  5,    TRUE,  FALSE, now() - INTERVAL '90 days'),
    ('ORG-LOCAL-012', 'Empire Outreach NY',       'Rochester',  'NY', 'non_profit', 'medium', NULL, FALSE, FALSE, now() - INTERVAL '120 days'),
    ('ORG-LOCAL-013', 'Pacific Relief CA',        'Oakland',    'CA', 'for_profit', 'small',  4,    FALSE, TRUE,  now() - INTERVAL '150 days'),
    ('ORG-LOCAL-014', 'Southern Cross TX',        'Dallas',     'TX', 'non_profit', 'large',  3,    TRUE,  TRUE,  now() - INTERVAL '200 days'),
    ('ORG-LOCAL-015', 'Windy City Works IL',      'Naperville', 'IL', 'non_profit', 'medium', 5,    TRUE,  FALSE, now() - INTERVAL '250 days'),
    ('ORG-LOCAL-016', 'Old Dominion Outreach VA', 'Norfolk',    'VA', 'for_profit', 'medium', 1,    FALSE, TRUE,  now() - INTERVAL '300 days'),
    ('ORG-LOCAL-017', 'Empire State Aid NY',      'Syracuse',   'NY', 'non_profit', 'small',  NULL, FALSE, FALSE, now() - INTERVAL '400 days'),
    ('ORG-LOCAL-018', 'Sunshine Support CA',      'San Jose',   'CA', 'non_profit', 'large',  4,    TRUE,  TRUE,  now() - INTERVAL '450 days'),
    ('ORG-LOCAL-019', 'Texas Together TX',        'San Antonio','TX', 'for_profit', 'small',  2,    FALSE, FALSE, now() - INTERVAL '500 days'),
    ('ORG-LOCAL-020', 'Great Lakes Giving IL',    'Peoria',     'IL', 'non_profit', 'medium', 5,    TRUE,  TRUE,  now() - INTERVAL '600 days')
ON CONFLICT (org_id) DO NOTHING;

-- Backfills is_contributor for rows inserted before this column existed (the
-- ON CONFLICT DO NOTHING above skips existing rows entirely, so it won't
-- touch this). Harmless no-op if every row is already correct.
UPDATE virginia_dev_saayam_rdbms.organizations SET is_contributor = TRUE
WHERE org_id IN ('ORG-LOCAL-001','ORG-LOCAL-003','ORG-LOCAL-005','ORG-LOCAL-006','ORG-LOCAL-009',
                  'ORG-LOCAL-010','ORG-LOCAL-013','ORG-LOCAL-014','ORG-LOCAL-016','ORG-LOCAL-018','ORG-LOCAL-020')
  AND is_contributor IS DISTINCT FROM TRUE;
UPDATE virginia_dev_saayam_rdbms.organizations SET is_contributor = FALSE
WHERE org_id IN ('ORG-LOCAL-002','ORG-LOCAL-004','ORG-LOCAL-007','ORG-LOCAL-008','ORG-LOCAL-011',
                  'ORG-LOCAL-012','ORG-LOCAL-015','ORG-LOCAL-017','ORG-LOCAL-019')
  AND is_contributor IS DISTINCT FROM FALSE;
