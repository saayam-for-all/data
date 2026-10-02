-- =============================================================================
-- Organization Analytics API - Local Development Schema (Issue #228)
-- =============================================================================
-- Creates the `states` lookup table and `organizations` table inside the
-- `virginia_dev_saayam_rdbms` schema for LOCAL PostgreSQL testing only.
--
-- NOTE ON is_contributor:
-- Per the issue, `is_contributor` is a NEW field that may not yet be present
-- in the current dev database. It IS included here so the contributor
-- metrics can be built/tested locally. The application code treats every
-- is_contributor query as best-effort (see organization_analytics.py) so it
-- degrades gracefully instead of failing once deployed against a table that
-- doesn't have the column yet.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS virginia_dev_saayam_rdbms;

CREATE TABLE IF NOT EXISTS virginia_dev_saayam_rdbms.states (
    state_id         VARCHAR(6) PRIMARY KEY,
    country_id       INTEGER,
    state_name       VARCHAR(100),
    state_code       VARCHAR(10),
    last_update_date TIMESTAMP
);

CREATE TABLE IF NOT EXISTS virginia_dev_saayam_rdbms.organizations (
    org_id          VARCHAR(255) PRIMARY KEY,
    org_name        VARCHAR(125) NOT NULL,
    street          VARCHAR(255),
    city_name       VARCHAR(100),
    state_id        VARCHAR(6) REFERENCES virginia_dev_saayam_rdbms.states(state_id),
    zip_code        VARCHAR(10),
    mission         TEXT,
    web_url         VARCHAR(255),
    phone           VARCHAR(20),
    email           VARCHAR(255),
    org_type        VARCHAR(50),   -- 'Non-Profit' | 'For-profit'
    org_size        VARCHAR(50),   -- 'Small' | 'Medium' | 'Large'
    org_rating      INTEGER,       -- 1-5, NULL = unrated
    is_collaborator BOOLEAN DEFAULT FALSE,
    is_contributor  BOOLEAN DEFAULT FALSE,  -- NOT YET IN DEV DB, see note above
    created_at      TIMESTAMP,
    last_updated_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_organizations_created_at ON virginia_dev_saayam_rdbms.organizations (created_at);
CREATE INDEX IF NOT EXISTS idx_organizations_org_type   ON virginia_dev_saayam_rdbms.organizations (org_type);
CREATE INDEX IF NOT EXISTS idx_organizations_org_size   ON virginia_dev_saayam_rdbms.organizations (org_size);
CREATE INDEX IF NOT EXISTS idx_organizations_state_id   ON virginia_dev_saayam_rdbms.organizations (state_id);
CREATE INDEX IF NOT EXISTS idx_organizations_org_rating ON virginia_dev_saayam_rdbms.organizations (org_rating);