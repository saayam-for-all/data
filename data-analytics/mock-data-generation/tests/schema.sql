-- Isolated integration-test schema; CREATE fails if this schema already exists.
-- In-scope columns/types/constraints transcribed from the issue #301 wiki
-- "Table after changes" blocks and pluralization, checked 2026-09-08.
-- Only ID-replacement triggers are needed for this CSV insert smoke test.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA virginia_dev_saayam_rdbms;
SET search_path = virginia_dev_saayam_rdbms, public;
CREATE TYPE skill_levels AS ENUM ('BEGINNER','INTERMEDIATE','ADVANCED','EXPERT');
CREATE TYPE org_type_enum AS ENUM ('non_profit','for_profit');
CREATE TYPE org_size_enum AS ENUM ('small','medium','large');
CREATE TABLE countries (
 country_id SERIAL PRIMARY KEY, country_name VARCHAR(100) NOT NULL,
 phone_code VARCHAR(5) NOT NULL, country_code VARCHAR(6) NOT NULL,
 last_updated_at TIMESTAMP DEFAULT (now() AT TIME ZONE 'UTC'), is_eu_member BOOLEAN DEFAULT FALSE
);
CREATE TABLE states (
 state_id VARCHAR(50) PRIMARY KEY, country_id INT NOT NULL REFERENCES countries,
 state_name VARCHAR(100) NOT NULL, state_code VARCHAR(6),
 last_updated_at TIMESTAMP DEFAULT (now() AT TIME ZONE 'UTC')
);
CREATE TABLE cities (
 city_id SERIAL PRIMARY KEY, state_id VARCHAR(50) NOT NULL REFERENCES states,
 city_name VARCHAR(30) NOT NULL, lattitude DECIMAL(9,6), longitude DECIMAL(9,6),
 last_updated_at TIMESTAMP DEFAULT (now() AT TIME ZONE 'UTC')
);
CREATE TABLE help_categories (
 cat_id VARCHAR(50) PRIMARY KEY, cat_name VARCHAR(100) NOT NULL,
 cat_desc VARCHAR(150) NOT NULL, last_updated_at TIMESTAMP DEFAULT (now() AT TIME ZONE 'UTC')
);
CREATE TABLE supporting_languages (
 language_id BIGSERIAL PRIMARY KEY, language_name VARCHAR(64) NOT NULL,
 iso_code CHAR(2) NOT NULL, locale_code VARCHAR(10) NOT NULL,
 writing_direction VARCHAR(3) NOT NULL DEFAULT 'LTR', total_speakers_m NUMERIC(10,1),
 is_active BOOLEAN NOT NULL DEFAULT TRUE,
 created_at TIMESTAMP DEFAULT (now() AT TIME ZONE 'UTC'),
 last_updated_at TIMESTAMP DEFAULT (now() AT TIME ZONE 'UTC'),
 UNIQUE(iso_code,locale_code), CHECK(writing_direction IN ('LTR','RTL')),
 CHECK(iso_code ~ '^[A-Za-z]{2}$'), CHECK(locale_code ~ '^[a-z]{2}_[A-Z]{2}$')
);
CREATE TABLE user_status (
 user_status_id SERIAL PRIMARY KEY, user_status VARCHAR(255) NOT NULL,
 user_status_desc VARCHAR(255), last_updated_at TIMESTAMP DEFAULT (now() AT TIME ZONE 'UTC')
);
CREATE TABLE users (
 user_id VARCHAR(255) PRIMARY KEY, state_id VARCHAR(30) REFERENCES states ON DELETE SET NULL,
 country_id INT REFERENCES countries ON DELETE SET NULL, user_status_id INT REFERENCES user_status,
 full_name VARCHAR(255), first_name VARCHAR(255), middle_name VARCHAR(255), last_name VARCHAR(255),
 primary_email_address VARCHAR(255), primary_phone_number VARCHAR(255),
 addr_ln1 VARCHAR(255), addr_ln2 VARCHAR(255), addr_ln3 VARCHAR(255),
 city_name VARCHAR(255), zip_code VARCHAR(255), last_location point,
 last_updated_at TIMESTAMP DEFAULT (now() AT TIME ZONE 'UTC'),
 time_zone VARCHAR(255), profile_picture_path VARCHAR(255), gender VARCHAR(255),
 language_1 BIGINT REFERENCES supporting_languages ON DELETE SET NULL,
 language_2 BIGINT REFERENCES supporting_languages ON DELETE SET NULL,
 language_3 BIGINT REFERENCES supporting_languages ON DELETE SET NULL,
 promotion_wizard_stage INT,
 promotion_wizard_last_updated_at TIMESTAMP DEFAULT (now() AT TIME ZONE 'UTC'),
 external_auth_provider VARCHAR(20), dob DATE, is_eu BOOLEAN DEFAULT FALSE
);
CREATE TABLE user_skills (
 user_id VARCHAR(255) REFERENCES users, cat_id VARCHAR(50) NOT NULL REFERENCES help_categories,
 skill_level skill_levels, created_at TIMESTAMP DEFAULT (now() AT TIME ZONE 'UTC'),
 last_updated_at TIMESTAMP DEFAULT (now() AT TIME ZONE 'UTC'), PRIMARY KEY(user_id,cat_id)
);
CREATE TABLE user_locations (
 user_id VARCHAR(255) PRIMARY KEY REFERENCES users ON DELETE CASCADE,
 prev_loc geography(Point,4326), curr_loc geography(Point,4326),
 last_updated_at TIMESTAMP DEFAULT (now() AT TIME ZONE 'UTC')
);
CREATE TABLE volunteer_details (
 user_id VARCHAR(255) PRIMARY KEY REFERENCES users, terms_and_conditions BOOLEAN,
 terms_accepted_at TIMESTAMP DEFAULT (now() AT TIME ZONE 'UTC'),
 govt_id_path1 TEXT, govt_id_path2 TEXT,
 path1_updated_at TIMESTAMP DEFAULT (now() AT TIME ZONE 'UTC'),
 path2_updated_at TIMESTAMP DEFAULT (now() AT TIME ZONE 'UTC'),
 availability_days JSONB, availability_times JSONB,
 created_at TIMESTAMP DEFAULT (now() AT TIME ZONE 'UTC'),
 last_updated_at TIMESTAMP DEFAULT (now() AT TIME ZONE 'UTC')
);
CREATE TABLE volunteer_locations (
 user_id VARCHAR(255) PRIMARY KEY REFERENCES volunteer_details ON DELETE CASCADE,
 prev_loc geography(Point,4326), curr_loc geography(Point,4326),
 last_updated_at TIMESTAMP DEFAULT (now() AT TIME ZONE 'UTC')
);
CREATE TABLE organizations (
 org_id VARCHAR(255) PRIMARY KEY, org_name VARCHAR(125) NOT NULL,
 street VARCHAR(255), city_name VARCHAR(100), state_id VARCHAR(50) REFERENCES states ON DELETE SET NULL,
 zip_code VARCHAR(10), mission TEXT, web_url VARCHAR(255) CHECK(web_url IS NULL OR web_url LIKE 'http%'),
 phone VARCHAR(20), email VARCHAR(255) CHECK(email IS NULL OR email LIKE '%@%'),
 org_type org_type_enum, org_size org_size_enum, org_rating INTEGER CHECK(org_rating BETWEEN 1 AND 5),
 is_collaborator BOOLEAN, is_contributor BOOLEAN,
 created_at TIMESTAMP DEFAULT (now() AT TIME ZONE 'UTC'),
 last_updated_at TIMESTAMP DEFAULT (now() AT TIME ZONE 'UTC')
);
CREATE SEQUENCE user_id_seq START 1 MAXVALUE 19999999999;
CREATE FUNCTION generate_sid() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE padded text;
BEGIN
 padded := lpad(nextval('virginia_dev_saayam_rdbms.user_id_seq')::text,15,'0');
 NEW.user_id := 'SID-00-' || substr(padded,1,3) || '-' || substr(padded,4,3) || '-' ||
 substr(padded,7,3) || '-' || substr(padded,10,3) || '-' || substr(padded,13,3);
 RETURN NEW;
END $$;
CREATE TRIGGER before_insert_users BEFORE INSERT ON users
FOR EACH ROW EXECUTE FUNCTION generate_sid();
CREATE SEQUENCE org_id_seq START 1 MAXVALUE 999999999999;
CREATE FUNCTION generate_org_id() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE padded text;
BEGIN
 padded := lpad(nextval('virginia_dev_saayam_rdbms.org_id_seq')::text,13,'0');
 NEW.org_id := 'ORG-' || substr(padded,1,3) || '-' || substr(padded,4,3) || '-' ||
 substr(padded,7,3) || '-' || substr(padded,10,4);
 RETURN NEW;
END $$;
CREATE TRIGGER before_insert_organizations BEFORE INSERT ON organizations
FOR EACH ROW EXECUTE FUNCTION generate_org_id();

