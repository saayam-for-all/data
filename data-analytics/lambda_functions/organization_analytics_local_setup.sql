-- Local test setup for Organization Analytics API
-- Mirrors ddl_organizations.sql + ddl_state.sql from saayam-for-all/database
-- NOTE: adds is_contributor BOOLEAN (required by analytics spec, missing in current DDL)

SET search_path TO virginia_dev_saayam_rdbms;

DROP TABLE IF EXISTS organizations CASCADE;
DROP TABLE IF EXISTS state CASCADE;
DROP TABLE IF EXISTS country CASCADE;
DROP TYPE IF EXISTS org_type_enum;
DROP TYPE IF EXISTS org_size_enum;

CREATE TYPE org_type_enum AS ENUM ('non_profit', 'for_profit');
CREATE TYPE org_size_enum AS ENUM ('small', 'medium', 'large');

CREATE TABLE country (
    country_id INT PRIMARY KEY,
    country_name VARCHAR(100) NOT NULL
);

CREATE TABLE state (
    state_id VARCHAR(50) PRIMARY KEY,
    country_id INT NOT NULL,
    state_name VARCHAR(100) NOT NULL,
    state_code VARCHAR(6),
    last_update_date TIMESTAMP,
    FOREIGN KEY (country_id) REFERENCES country (country_id)
);

CREATE SEQUENCE IF NOT EXISTS org_id_seq;

CREATE TABLE organizations (
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
  is_contributor BOOLEAN,          -- ADDED: required by analytics spec (needs DDL PR in database repo)
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'UTC'),
  last_updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'UTC'),
  FOREIGN KEY (state_id) REFERENCES state(state_id) ON DELETE SET NULL
);

CREATE OR REPLACE FUNCTION generate_org_id()
    RETURNS trigger LANGUAGE plpgsql AS $BODY$
DECLARE
    seq_id INT;
BEGIN
    seq_id := nextval('virginia_dev_saayam_rdbms.org_id_seq');
    NEW.org_id := 'ORG-00-' || LPAD(FLOOR(seq_id / 1000000)::TEXT, 3, '0') || '-' ||
                  LPAD(FLOOR((seq_id % 1000000) / 1000)::TEXT, 3, '0') || '-' ||
                  LPAD((seq_id % 1000)::TEXT, 3, '0');
    RETURN NEW;
END;
$BODY$;

CREATE OR REPLACE TRIGGER before_insert_organizations
    BEFORE INSERT ON organizations
    FOR EACH ROW EXECUTE FUNCTION generate_org_id();

GRANT ALL ON ALL TABLES IN SCHEMA virginia_dev_saayam_rdbms TO saayam;
GRANT ALL ON ALL SEQUENCES IN SCHEMA virginia_dev_saayam_rdbms TO saayam;
