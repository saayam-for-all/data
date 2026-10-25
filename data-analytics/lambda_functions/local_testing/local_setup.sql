-- Local Postgres schema for organization_analytics.py.
-- Loads from the mock data at data-analytics/sql/organizations.csv (provided
-- by Sana for this task) via seed_from_csv.py in this same folder.
--
-- org_type/org_size are plain VARCHAR here (not the org_type_enum/org_size_enum
-- from ddl_organizations.sql) because the mock CSV stores them as
-- "Non-Profit"/"For-profit"/"Small"/"Medium"/"Large" rather than the DDL's
-- lowercase snake_case enum labels. organization_analytics.py normalizes
-- these at query time (see ORG_TYPE_NORM / ORG_SIZE_NORM), so this works
-- whether the underlying table uses the mock's display strings or the real
-- enum values.
--
-- state_id is also plain VARCHAR: the mock data stores literal 2-letter
-- state codes directly (e.g. "NY"), not the FK-style state_id used in
-- ddl_organizations.sql / ddl_state.sql. No state table is created or
-- joined here - see the NOTE in fetch_organizations_by_state().

CREATE SCHEMA IF NOT EXISTS virginia_dev_saayam_rdbms;

DROP TABLE IF EXISTS virginia_dev_saayam_rdbms.organizations;

CREATE TABLE virginia_dev_saayam_rdbms.organizations (
    org_id           VARCHAR(255) PRIMARY KEY,
    org_name         VARCHAR(125) NOT NULL,
    street           VARCHAR(255),
    city_name        VARCHAR(100),
    state_id         VARCHAR(50),
    zip_code         VARCHAR(10),
    mission          TEXT,
    web_url          VARCHAR(255),
    phone            VARCHAR(20),
    email            VARCHAR(255),
    org_type         VARCHAR(50),
    org_size         VARCHAR(50),
    org_rating       INTEGER CHECK (org_rating IS NULL OR (org_rating BETWEEN 1 AND 5)),
    is_collaborator  BOOLEAN,
    is_contributor   BOOLEAN,
    created_at       TIMESTAMP,
    last_updated_at  TIMESTAMP
);
