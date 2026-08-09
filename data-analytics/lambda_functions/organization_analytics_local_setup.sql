-- Local PostgreSQL setup for Organization Analytics API development only.
-- Run this against a disposable local database, never an AWS environment.

CREATE SCHEMA IF NOT EXISTS virginia_dev_saayam_rdbms;

CREATE TABLE IF NOT EXISTS virginia_dev_saayam_rdbms.state (
    state_id VARCHAR(16) PRIMARY KEY,
    country_id INTEGER,
    state_name VARCHAR(150) NOT NULL,
    state_code VARCHAR(32),
    last_update_date TIMESTAMP
);

CREATE TABLE IF NOT EXISTS virginia_dev_saayam_rdbms.organizations (
    org_id VARCHAR(64) PRIMARY KEY,
    org_name VARCHAR(255) NOT NULL,
    street VARCHAR(255),
    city_name VARCHAR(150),
    state_id VARCHAR(16),
    zip_code VARCHAR(32),
    mission TEXT,
    web_url TEXT,
    phone VARCHAR(64),
    email VARCHAR(255),
    org_type VARCHAR(64),
    org_size VARCHAR(64),
    org_rating NUMERIC(3, 2),
    is_collaborator BOOLEAN,
    is_contributor BOOLEAN,
    created_at TIMESTAMP,
    last_updated_at TIMESTAMP,
    CONSTRAINT organizations_state_fk
        FOREIGN KEY (state_id)
        REFERENCES virginia_dev_saayam_rdbms.state (state_id)
);

-- The production column is not available in every environment yet. This is
-- intentionally part of local setup so contributor behavior can be verified.
ALTER TABLE virginia_dev_saayam_rdbms.organizations
    ADD COLUMN IF NOT EXISTS is_contributor BOOLEAN;

