-- Reproducible local setup for testing organization_analytics.py.
-- Usage (local Postgres):
--   createdb saayam_local
--   psql -d saayam_local -f local_setup.sql
-- Then run the API with LOCAL_DB=true (see README).

CREATE SCHEMA IF NOT EXISTS virginia_dev_saayam_rdbms;
SET search_path TO virginia_dev_saayam_rdbms;

CREATE TABLE IF NOT EXISTS country (
    country_id INT PRIMARY KEY,
    country_name VARCHAR(100),
    country_code VARCHAR(6)
);

CREATE TABLE IF NOT EXISTS state (
    state_id VARCHAR(50) PRIMARY KEY,
    country_id INT NOT NULL,
    state_name VARCHAR(100) NOT NULL,
    state_code VARCHAR(6),
    last_update_date TIMESTAMP,
    FOREIGN KEY (country_id) REFERENCES country(country_id)
);

DO $$ BEGIN CREATE TYPE org_type_enum AS ENUM ('non_profit','for_profit'); EXCEPTION WHEN duplicate_object THEN null; END $$;
DO $$ BEGIN CREATE TYPE org_size_enum AS ENUM ('small','medium','large'); EXCEPTION WHEN duplicate_object THEN null; END $$;

CREATE TABLE IF NOT EXISTS organizations (
  org_id VARCHAR(255) PRIMARY KEY,
  org_name VARCHAR(125) NOT NULL,
  street VARCHAR(255),
  city_name VARCHAR(100),
  state_id VARCHAR(50),
  zip_code VARCHAR(10),
  mission TEXT,
  web_url VARCHAR(255),
  phone VARCHAR(20),
  email VARCHAR(255),
  org_type org_type_enum,
  org_size org_size_enum,
  org_rating INTEGER CHECK (org_rating >= 1 AND org_rating <= 5),
  is_collaborator BOOLEAN,
  is_contributor BOOLEAN,
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'UTC'),
  last_updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'UTC'),
  FOREIGN KEY (state_id) REFERENCES state(state_id) ON DELETE SET NULL
);

INSERT INTO country VALUES (1,'United States','US') ON CONFLICT DO NOTHING;
INSERT INTO state (state_id,country_id,state_name,state_code) VALUES
 ('VA',1,'Virginia','VA'),('CA',1,'California','CA'),('TX',1,'Texas','TX'),('NY',1,'New York','NY')
 ON CONFLICT DO NOTHING;

TRUNCATE organizations;
INSERT INTO organizations
(org_id, org_name, city_name, state_id, org_type, org_size, org_rating, is_collaborator, is_contributor, created_at) VALUES
('ORG-00-000-000-001','Helping Hands','Richmond','VA','non_profit','large',5,TRUE, TRUE, CURRENT_DATE - INTERVAL '2 days'),
('ORG-00-000-000-002','Bright Future','Norfolk','VA','non_profit','medium',4,TRUE, FALSE,CURRENT_DATE - INTERVAL '5 days'),
('ORG-00-000-000-003','Care Collective','Los Angeles','CA','non_profit','small',5,FALSE,TRUE, CURRENT_DATE - INTERVAL '10 days'),
('ORG-00-000-000-004','Open Aid','San Diego','CA','non_profit','large',3,TRUE, FALSE,CURRENT_DATE - INTERVAL '20 days'),
('ORG-00-000-000-005','Unity Works','Austin','TX','for_profit','medium',4,FALSE,TRUE, CURRENT_DATE - INTERVAL '25 days'),
('ORG-00-000-000-006','Green Path','Dallas','TX','for_profit','small',2,NULL, FALSE,CURRENT_DATE - INTERVAL '40 days'),
('ORG-00-000-000-007','Hope Line','Buffalo','NY','non_profit','medium',NULL,TRUE, NULL, CURRENT_DATE - INTERVAL '60 days'),
('ORG-00-000-000-008','Solid Ground','New York','NY','for_profit','large',5,TRUE, TRUE, CURRENT_DATE - INTERVAL '80 days'),
('ORG-00-000-000-009','Warm Meals','Richmond','VA','non_profit','small',4,FALSE,FALSE,CURRENT_DATE - INTERVAL '100 days'),
('ORG-00-000-000-010','Tech4Good','San Diego','CA','for_profit','medium',3,NULL, FALSE,CURRENT_DATE - INTERVAL '150 days'),
('ORG-00-000-000-011','Shelter Plus','Austin','TX','non_profit','large',NULL,FALSE,NULL, CURRENT_DATE - INTERVAL '200 days'),
('ORG-00-000-000-012','Kind Roots','New York','NY','non_profit','small',5,TRUE, TRUE, CURRENT_DATE - INTERVAL '250 days'),
('ORG-00-000-000-013','Rise Together','Norfolk','VA','for_profit','medium',1,FALSE,FALSE,CURRENT_DATE - INTERVAL '300 days'),
('ORG-00-000-000-014','City Cares','Los Angeles','CA','non_profit','large',4,TRUE, TRUE, CURRENT_DATE - INTERVAL '350 days'),
('ORG-00-000-000-015','Fresh Start','Dallas','TX','non_profit','medium',3,NULL, FALSE,CURRENT_DATE - INTERVAL '400 days'),
('ORG-00-000-000-016','Bridge Point','Buffalo','NY','for_profit','small',2,FALSE,FALSE,CURRENT_DATE - INTERVAL '500 days'),
('ORG-00-000-000-017','Safe Harbor','Richmond','VA','non_profit','large',5,TRUE, FALSE,CURRENT_DATE - INTERVAL '4 days'),
('ORG-00-000-000-018','Give Back','San Diego','CA','non_profit','medium',4,TRUE, TRUE, CURRENT_DATE - INTERVAL '15 days'),
('ORG-00-000-000-019','Neighbor Net','Austin','TX','non_profit','small',NULL,NULL,NULL, CURRENT_DATE - INTERVAL '28 days'),
('ORG-00-000-000-020','Prime Impact','New York','NY','for_profit','large',3,FALSE,TRUE, CURRENT_DATE - INTERVAL '3 days');
