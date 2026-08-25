-- Local PostgreSQL setup for the Organization Analytics API (issue #228).
--
-- Creates the schema plus the two source tables the API reads, so the endpoint
-- can be exercised locally without any AWS access. Load the sample data with:
--
--   psql -U postgres -d saayam_local -f organization_analytics_local_setup.sql
--   \copy virginia_dev_saayam_rdbms.state FROM 'state.csv' WITH (FORMAT csv, HEADER true, NULL '')
--   \copy virginia_dev_saayam_rdbms.organizations FROM 'organizations.csv' WITH (FORMAT csv, HEADER true, NULL '')

CREATE SCHEMA IF NOT EXISTS virginia_dev_saayam_rdbms;

DROP TABLE IF EXISTS virginia_dev_saayam_rdbms.organizations;
DROP TABLE IF EXISTS virginia_dev_saayam_rdbms.state;

-- Mirrors data-analytics/sql/state.csv
CREATE TABLE virginia_dev_saayam_rdbms.state (
    state_id          VARCHAR(10) PRIMARY KEY,
    country_id        INTEGER,
    state_name        VARCHAR(100),
    state_code        VARCHAR(20),
    last_update_date  TIMESTAMP
);

-- Mirrors data-analytics/sql/organizations.csv
CREATE TABLE virginia_dev_saayam_rdbms.organizations (
    org_id           VARCHAR(20) PRIMARY KEY,
    org_name         VARCHAR(255),
    street           VARCHAR(255),
    city_name        VARCHAR(100),
    state_id         VARCHAR(10),
    zip_code         VARCHAR(20),
    mission          TEXT,
    web_url          VARCHAR(255),
    phone            VARCHAR(50),
    email            VARCHAR(255),
    org_type         VARCHAR(50),
    org_size         VARCHAR(50),
    org_rating       INTEGER,
    is_collaborator  BOOLEAN,
    is_contributor   BOOLEAN,
    created_at       TIMESTAMP,
    last_updated_at  TIMESTAMP
);

CREATE INDEX idx_organizations_created_at ON virginia_dev_saayam_rdbms.organizations (created_at);
CREATE INDEX idx_organizations_state_id ON virginia_dev_saayam_rdbms.organizations (state_id);
