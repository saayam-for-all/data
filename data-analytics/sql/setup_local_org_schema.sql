-- Run this against your local saayam_local DB
-- Matches ddl_organizations.sql + ddl_state.sql exactly (no CSV-driven fields)

CREATE SCHEMA IF NOT EXISTS virginia_dev_saayam_rdbms;

-- state table (needed for FK)
DROP TABLE IF EXISTS virginia_dev_saayam_rdbms.state CASCADE;
CREATE TABLE virginia_dev_saayam_rdbms.state (
    state_id VARCHAR(50) PRIMARY KEY,
    country_id INT NOT NULL,
    state_name VARCHAR(100) NOT NULL,
    state_code VARCHAR(6),
    last_update_date TIMESTAMP
    -- FK to country dropped for local testing (country table not in scope)
);

-- organizations table (verbatim from ddl_organizations.sql, FK fixed to point at `state` not `states`)
DROP TYPE IF EXISTS org_type_enum CASCADE;
DROP TYPE IF EXISTS org_size_enum CASCADE;
CREATE TYPE org_type_enum AS ENUM ('non_profit', 'for_profit');
CREATE TYPE org_size_enum AS ENUM ('small', 'medium', 'large');

DROP TABLE IF EXISTS virginia_dev_saayam_rdbms.organizations CASCADE;
CREATE TABLE virginia_dev_saayam_rdbms.organizations (
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
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'UTC'),
  last_updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'UTC'),
  FOREIGN KEY (state_id) REFERENCES virginia_dev_saayam_rdbms.state(state_id) ON DELETE SET NULL
);

CREATE INDEX idx_org_name ON virginia_dev_saayam_rdbms.organizations(org_name);
CREATE INDEX idx_org_state_id ON virginia_dev_saayam_rdbms.organizations(state_id);
CREATE INDEX idx_org_city_state ON virginia_dev_saayam_rdbms.organizations(city_name, state_id);
