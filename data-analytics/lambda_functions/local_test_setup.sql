-- ============================================================================
-- Local test setup for Organization Analytics API (#228)
-- Run against a local Postgres instance matching DATABASE_URL in your .env.
--
-- Fixes applied vs. the raw DDL from the database repo:
--   1. organizations.state_id FK now points to `state` (the table that actually
--      exists), not `states` (referenced in the original DDL but never created).
--   2. Adds a minimal `country` table since `state` FKs to it but no DDL for it
--      was provided.
--   3. Adds `org_id_seq`, which the generate_org_id() trigger function
--      references but the original DDL never creates.
--
-- Usage:
--   psql "$DATABASE_URL" -f local_test_setup.sql
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS virginia_dev_saayam_rdbms;

-- ----------------------------------------------------------------------------
-- Enum types (idempotent - CREATE TYPE has no IF NOT EXISTS in Postgres)
-- ----------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'org_type_enum') THEN
        CREATE TYPE org_type_enum AS ENUM ('non_profit', 'for_profit');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'org_size_enum') THEN
        CREATE TYPE org_size_enum AS ENUM ('small', 'medium', 'large');
    END IF;
END$$;

-- ----------------------------------------------------------------------------
-- Minimal country table (not in the provided DDL, but state.country_id needs it)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS virginia_dev_saayam_rdbms.country (
    country_id INT PRIMARY KEY,
    country_name VARCHAR(100) NOT NULL
);

INSERT INTO virginia_dev_saayam_rdbms.country (country_id, country_name)
VALUES (1, 'United States')
ON CONFLICT (country_id) DO NOTHING;

-- ----------------------------------------------------------------------------
-- state table
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS virginia_dev_saayam_rdbms.state (
    state_id VARCHAR(50) PRIMARY KEY,
    country_id INT NOT NULL,
    state_name VARCHAR(100) NOT NULL,
    state_code VARCHAR(6),
    last_update_date TIMESTAMP,
    FOREIGN KEY (country_id) REFERENCES virginia_dev_saayam_rdbms.country (country_id)
);

INSERT INTO virginia_dev_saayam_rdbms.state (state_id, country_id, state_name, state_code)
VALUES
    ('NY', 1, 'New York', 'NY'),
    ('CA', 1, 'California', 'CA'),
    ('TX', 1, 'Texas', 'TX'),
    ('IL', 1, 'Illinois', 'IL'),
    ('MA', 1, 'Massachusetts', 'MA')
ON CONFLICT (state_id) DO NOTHING;

-- ----------------------------------------------------------------------------
-- org_id_seq (referenced by generate_org_id() but never created in the DDL)
-- ----------------------------------------------------------------------------
CREATE SEQUENCE IF NOT EXISTS virginia_dev_saayam_rdbms.org_id_seq;

-- ----------------------------------------------------------------------------
-- organizations table
-- NOTE: FK fixed to reference `state`, not `states` (see header comment).
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS virginia_dev_saayam_rdbms.organizations CASCADE;
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
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'UTC'),
  last_updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'UTC'),
  FOREIGN KEY (state_id) REFERENCES virginia_dev_saayam_rdbms.state(state_id) ON DELETE SET NULL
);

CREATE INDEX idx_org_name ON virginia_dev_saayam_rdbms.organizations(org_name);
CREATE INDEX idx_org_state_id ON virginia_dev_saayam_rdbms.organizations(state_id);
CREATE INDEX idx_org_city_state ON virginia_dev_saayam_rdbms.organizations(city_name, state_id);

CREATE OR REPLACE FUNCTION virginia_dev_saayam_rdbms.generate_org_id()
    RETURNS trigger
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE NOT LEAKPROOF
AS $BODY$
DECLARE
    seq_id INT;
    new_id VARCHAR(20);
BEGIN
    seq_id := nextval('virginia_dev_saayam_rdbms.org_id_seq');
    new_id := 'ORG-00-' || LPAD(FLOOR(seq_id / 1000000)::TEXT, 3, '0') || '-' ||
              LPAD(FLOOR((seq_id % 1000000) / 1000)::TEXT, 3, '0') || '-' ||
              LPAD((seq_id % 1000)::TEXT, 3, '0');
    NEW.org_id := new_id;
    RETURN NEW;
END;
$BODY$;

CREATE OR REPLACE TRIGGER before_insert_organizations
    BEFORE INSERT
    ON virginia_dev_saayam_rdbms.organizations
    FOR EACH ROW
    EXECUTE FUNCTION virginia_dev_saayam_rdbms.generate_org_id();

-- ----------------------------------------------------------------------------
-- Mock data: 25 organizations spanning every dimension the two dashboards
-- slice by (type, size, rating incl. NULLs, collaborator flag, state/city,
-- and created_at spread across the past ~14 months for the trend chart).
-- org_id is auto-generated by the trigger, so it's omitted from the INSERT.
-- ----------------------------------------------------------------------------
INSERT INTO virginia_dev_saayam_rdbms.organizations
    (org_name, street, city_name, state_id, zip_code, mission, web_url, phone, email,
     org_type, org_size, org_rating, is_collaborator, created_at)
VALUES
    ('Hope Kitchen NY', '10 Main St', 'Syracuse', 'NY', '13210', 'Food security for families', 'https://hopekitchen.org', '315-555-0101', 'info@hopekitchen.org', 'non_profit', 'small', 5, TRUE, NOW() - INTERVAL '13 months'),
    ('Bright Path Shelter', '22 Oak Ave', 'Buffalo', 'NY', '14201', 'Emergency housing', 'https://brightpath.org', '716-555-0102', 'contact@brightpath.org', 'non_profit', 'medium', 4, TRUE, NOW() - INTERVAL '12 months'),
    ('CareForward Health', '5 Elm St', 'Rochester', 'NY', '14604', 'Community health clinics', 'https://careforward.org', '585-555-0103', 'hello@careforward.org', 'non_profit', 'large', 5, FALSE, NOW() - INTERVAL '11 months'),
    ('Golden State Aid', '100 Sunset Blvd', 'Los Angeles', 'CA', '90001', 'Disaster relief', 'https://goldenstateaid.org', '213-555-0104', 'info@goldenstateaid.org', 'non_profit', 'large', 3, TRUE, NOW() - INTERVAL '10 months'),
    ('Bay Area Builders', '200 Market St', 'San Francisco', 'CA', '94103', 'Affordable housing construction', 'https://bayareabuilders.com', '415-555-0105', 'contact@bayareabuilders.com', 'for_profit', 'medium', 4, FALSE, NOW() - INTERVAL '9 months'),
    ('Sunrise Youth Services', '15 Palm Dr', 'San Diego', 'CA', '92101', 'Youth mentorship', 'https://sunriseyouth.org', '619-555-0106', 'info@sunriseyouth.org', 'non_profit', 'small', NULL, FALSE, NOW() - INTERVAL '8 months'),
    ('Lone Star Relief', '300 Congress Ave', 'Austin', 'TX', '78701', 'Emergency response', 'https://lonestarrelief.org', '512-555-0107', 'info@lonestarrelief.org', 'non_profit', 'medium', 5, TRUE, NOW() - INTERVAL '7 months'),
    ('Houston Helping Hands', '400 Main St', 'Houston', 'TX', '77002', 'Food and shelter', 'https://houstonhelpinghands.org', '713-555-0108', 'contact@houstonhelpinghands.org', 'non_profit', 'small', 2, FALSE, NOW() - INTERVAL '6 months'),
    ('Alamo Analytics Group', '500 Commerce St', 'San Antonio', 'TX', '78205', 'Nonprofit data consulting', 'https://alamoanalytics.com', '210-555-0109', 'info@alamoanalytics.com', 'for_profit', 'small', 4, TRUE, NOW() - INTERVAL '5 months'),
    ('Windy City Outreach', '600 State St', 'Chicago', 'IL', '60601', 'Homeless outreach', 'https://windycityoutreach.org', '312-555-0110', 'info@windycityoutreach.org', 'non_profit', 'large', 5, TRUE, NOW() - INTERVAL '4 months'),
    ('Prairie Health Partners', '700 Wacker Dr', 'Chicago', 'IL', '60602', 'Rural health access', 'https://prairiehealth.org', '312-555-0111', 'contact@prairiehealth.org', 'non_profit', 'medium', NULL, FALSE, NOW() - INTERVAL '3 months'),
    ('Beacon Hill Foundation', '800 Boylston St', 'Boston', 'MA', '02116', 'Education access', 'https://beaconhillfound.org', '617-555-0112', 'info@beaconhillfound.org', 'non_profit', 'medium', 4, TRUE, NOW() - INTERVAL '2 months'),
    ('Bunker Hill Builders Co', '900 Congress St', 'Boston', 'MA', '02114', 'Community infrastructure', 'https://bunkerhillbuilders.com', '617-555-0113', 'info@bunkerhillbuilders.com', 'for_profit', 'large', 3, FALSE, NOW() - INTERVAL '1 month'),
    ('Empire Meals Program', '11 5th Ave', 'New York', 'NY', '10001', 'School meal programs', 'https://empiremeals.org', '212-555-0114', 'info@empiremeals.org', 'non_profit', 'small', 5, TRUE, NOW() - INTERVAL '25 days'),
    ('Manhattan Mutual Aid', '12 Broadway', 'New York', 'NY', '10004', 'Neighbor-to-neighbor aid', 'https://manhattanmutualaid.org', '212-555-0115', 'info@manhattanmutualaid.org', 'non_profit', 'small', NULL, TRUE, NOW() - INTERVAL '20 days'),
    ('Pacific Rim Relief', '13 Ocean Ave', 'Los Angeles', 'CA', '90002', 'Refugee resettlement support', 'https://pacificrimrelief.org', '213-555-0116', 'info@pacificrimrelief.org', 'non_profit', 'medium', 4, FALSE, NOW() - INTERVAL '18 days'),
    ('Silicon Valley Cares', '14 Innovation Way', 'San Jose', 'CA', '95110', 'Tech-for-good grants', 'https://svcares.org', '408-555-0117', 'info@svcares.org', 'for_profit', 'small', 5, TRUE, NOW() - INTERVAL '15 days'),
    ('Texas Hill Country Aid', '15 Ranch Rd', 'Austin', 'TX', '78702', 'Rural disaster recovery', 'https://hillcountryaid.org', '512-555-0118', 'info@hillcountryaid.org', 'non_profit', 'medium', 3, TRUE, NOW() - INTERVAL '12 days'),
    ('Gulf Coast Response', '16 Bay St', 'Houston', 'TX', '77003', 'Hurricane response', 'https://gulfcoastresponse.org', '713-555-0119', 'info@gulfcoastresponse.org', 'non_profit', 'large', NULL, FALSE, NOW() - INTERVAL '10 days'),
    ('Great Lakes Foundation', '17 Michigan Ave', 'Chicago', 'IL', '60603', 'Environmental & housing grants', 'https://greatlakesfound.org', '312-555-0120', 'info@greatlakesfound.org', 'non_profit', 'large', 5, TRUE, NOW() - INTERVAL '8 days'),
    ('Midwest Micro-Grants LLC', '18 River Rd', 'Chicago', 'IL', '60604', 'Small nonprofit funding', 'https://midwestmicro.com', '312-555-0121', 'info@midwestmicro.com', 'for_profit', 'small', 2, FALSE, NOW() - INTERVAL '6 days'),
    ('Old North Aid Society', '19 Freedom Trail', 'Boston', 'MA', '02113', 'Historic district community aid', 'https://oldnorthaid.org', '617-555-0122', 'info@oldnorthaid.org', 'non_profit', 'small', 4, TRUE, NOW() - INTERVAL '5 days'),
    ('Cape Cod Volunteers', '20 Shore Dr', 'Barnstable', 'MA', '02630', 'Coastal community support', 'https://capecodvolunteers.org', '508-555-0123', 'info@capecodvolunteers.org', 'non_profit', 'small', NULL, FALSE, NOW() - INTERVAL '3 days'),
    ('Finger Lakes Volunteer Network', '21 Lake St', 'Syracuse', 'NY', '13202', 'Regional volunteer coordination', 'https://fingerlakesvolunteer.org', '315-555-0124', 'info@fingerlakesvolunteer.org', 'non_profit', 'medium', 5, TRUE, NOW() - INTERVAL '2 days'),
    ('Empire Analytics Partners', '22 Data Way', 'New York', 'NY', '10005', 'Nonprofit analytics consulting', 'https://empireanalytics.com', '212-555-0125', 'info@empireanalytics.com', 'for_profit', 'medium', 4, FALSE, NOW() - INTERVAL '1 day');
