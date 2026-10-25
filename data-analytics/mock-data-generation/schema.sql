-- DDL for the 10 tables covered by the mock data, used to load-test the CSVs
-- (see README.md, "Validation"). Mirrors the Virginia schema from the
-- saayam-for-all/database wiki ("Changes to the Database, Waiting for
-- Microservice") using the pluralized table names (states, cities, countries).
--
-- Requires PostGIS (geography columns). user_status and supporting_languages are
-- out of scope for the mock data; minimal stubs are created below only so the
-- users foreign keys resolve.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA IF NOT EXISTS virginia_dev_saayam_rdbms;
SET search_path TO virginia_dev_saayam_rdbms, public;

CREATE TYPE skill_levels AS ENUM ('BEGINNER', 'INTERMEDIATE', 'ADVANCED', 'EXPERT');
CREATE TYPE org_type_enum AS ENUM ('non_profit', 'for_profit');
CREATE TYPE org_size_enum AS ENUM ('small', 'medium', 'large');

-- Stubs for out-of-scope lookup tables referenced by users -------------------
CREATE TABLE user_status (
    user_status_id INT PRIMARY KEY,
    user_status VARCHAR(50)
);
INSERT INTO user_status VALUES (1, 'ACTIVE');

CREATE TABLE supporting_languages (
    language_id BIGINT PRIMARY KEY,
    language_name VARCHAR(100)
);
INSERT INTO supporting_languages VALUES
    (1, 'English'), (2, 'Mandarin Chinese'), (3, 'Hindi'), (4, 'Spanish'),
    (5, 'French'), (6, 'Arabic'), (7, 'Bengali'), (8, 'Portuguese'),
    (9, 'Russian'), (10, 'Urdu'), (11, 'German'), (12, 'Telugu');

-- In-scope tables -------------------------------------------------------------
CREATE TABLE countries (
    country_id SERIAL PRIMARY KEY,
    country_name VARCHAR(100) NOT NULL,
    phone_code VARCHAR(5) NOT NULL,
    country_code VARCHAR(6) NOT NULL,
    last_updated_at TIMESTAMP WITHOUT TIME ZONE
        DEFAULT (now() AT TIME ZONE 'UTC'),
    is_eu_member BOOLEAN DEFAULT FALSE,
    UNIQUE (country_id)
);

CREATE TABLE states (
    state_id VARCHAR(50) PRIMARY KEY,
    country_id INT NOT NULL,
    state_name VARCHAR(100) NOT NULL,
    state_code VARCHAR(6),
    last_updated_at TIMESTAMP WITHOUT TIME ZONE
        DEFAULT (now() AT TIME ZONE 'UTC'),
    FOREIGN KEY (country_id) REFERENCES countries (country_id)
);

CREATE TABLE cities (
    city_id SERIAL PRIMARY KEY,
    state_id VARCHAR(50) NOT NULL,
    city_name VARCHAR(30) NOT NULL,
    lattitude DECIMAL(9, 6),
    longitude DECIMAL(9, 6),
    last_updated_at TIMESTAMP WITHOUT TIME ZONE
        DEFAULT (now() AT TIME ZONE 'UTC'),
    UNIQUE (city_id),
    FOREIGN KEY (state_id) REFERENCES states (state_id)
);

CREATE TABLE help_categories (
    cat_id VARCHAR(50) PRIMARY KEY,
    cat_name VARCHAR(100) NOT NULL,
    cat_desc VARCHAR(150) NOT NULL,
    last_updated_at TIMESTAMP WITHOUT TIME ZONE
        DEFAULT (now() AT TIME ZONE 'UTC')
);

CREATE TABLE users (
    user_id VARCHAR(255) PRIMARY KEY,
    state_id VARCHAR(30) NULL,
    country_id INT NULL,
    user_status_id INT NULL,
    full_name VARCHAR(255) NULL,
    first_name VARCHAR(255) NULL,
    middle_name VARCHAR(255) NULL,
    last_name VARCHAR(255) NULL,
    primary_email_address VARCHAR(255) NULL,
    primary_phone_number VARCHAR(255) NULL,
    addr_ln1 VARCHAR(255) NULL,
    addr_ln2 VARCHAR(255) NULL,
    addr_ln3 VARCHAR(255) NULL,
    city_name VARCHAR(255) NULL,
    zip_code VARCHAR(255) NULL,
    last_location point,
    last_updated_at TIMESTAMP WITHOUT TIME ZONE
        DEFAULT (now() AT TIME ZONE 'UTC'),
    time_zone VARCHAR(255) NULL,
    profile_picture_path VARCHAR(255) NULL,
    gender VARCHAR(255) NULL,
    language_1 BIGINT NULL,
    language_2 BIGINT NULL,
    language_3 BIGINT NULL,
    promotion_wizard_stage INT NULL,
    promotion_wizard_last_updated_at TIMESTAMP WITHOUT TIME ZONE
        DEFAULT (now() AT TIME ZONE 'UTC'),
    external_auth_provider VARCHAR(20) NULL,
    dob date,
    is_eu BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (country_id) REFERENCES countries (country_id) ON DELETE SET NULL,
    FOREIGN KEY (state_id) REFERENCES states (state_id) ON DELETE SET NULL,
    FOREIGN KEY (user_status_id) REFERENCES user_status (user_status_id),
    FOREIGN KEY (language_1) REFERENCES supporting_languages (language_id) ON DELETE SET NULL,
    FOREIGN KEY (language_2) REFERENCES supporting_languages (language_id) ON DELETE SET NULL,
    FOREIGN KEY (language_3) REFERENCES supporting_languages (language_id) ON DELETE SET NULL
);

CREATE TABLE volunteer_details (
    user_id VARCHAR(255) PRIMARY KEY,
    terms_and_conditions BOOLEAN,
    terms_accepted_at TIMESTAMP WITHOUT TIME ZONE
        DEFAULT (now() AT TIME ZONE 'UTC'),
    govt_id_path1 TEXT,
    govt_id_path2 TEXT,
    path1_updated_at TIMESTAMP WITHOUT TIME ZONE
        DEFAULT (now() AT TIME ZONE 'UTC'),
    path2_updated_at TIMESTAMP WITHOUT TIME ZONE
        DEFAULT (now() AT TIME ZONE 'UTC'),
    availability_days JSONB,
    availability_times JSONB,
    created_at TIMESTAMP WITHOUT TIME ZONE
        DEFAULT (now() AT TIME ZONE 'UTC'),
    last_updated_at TIMESTAMP WITHOUT TIME ZONE
        DEFAULT (now() AT TIME ZONE 'UTC'),
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);

CREATE TABLE user_skills (
    user_id VARCHAR(255),
    cat_id VARCHAR(50) NOT NULL,
    skill_level skill_levels,
    created_at TIMESTAMP WITHOUT TIME ZONE
        DEFAULT (now() AT TIME ZONE 'UTC'),
    last_updated_at TIMESTAMP WITHOUT TIME ZONE
        DEFAULT (now() AT TIME ZONE 'UTC'),
    PRIMARY KEY (user_id, cat_id),
    FOREIGN KEY (user_id) REFERENCES users (user_id),
    FOREIGN KEY (cat_id) REFERENCES help_categories (cat_id)
);

CREATE TABLE volunteer_locations (
    user_id VARCHAR(255) NOT NULL PRIMARY KEY,
    prev_loc geography(Point, 4326),
    curr_loc geography(Point, 4326),
    last_updated_at TIMESTAMP WITHOUT TIME ZONE
        DEFAULT (now() AT TIME ZONE 'UTC'),
    CONSTRAINT volunteer_locations_user_fk
        FOREIGN KEY (user_id) REFERENCES volunteer_details (user_id) ON DELETE CASCADE
);

CREATE TABLE user_locations (
    user_id VARCHAR(255) NOT NULL PRIMARY KEY,
    prev_loc geography(Point, 4326),
    curr_loc geography(Point, 4326),
    last_updated_at TIMESTAMP WITHOUT TIME ZONE
        DEFAULT (now() AT TIME ZONE 'UTC'),
    CONSTRAINT user_locations_user_fk
        FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
);

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
    is_contributor BOOLEAN,
    created_at TIMESTAMP WITHOUT TIME ZONE
        DEFAULT (now() AT TIME ZONE 'UTC'),
    last_updated_at TIMESTAMP WITHOUT TIME ZONE
        DEFAULT (now() AT TIME ZONE 'UTC'),
    FOREIGN KEY (state_id) REFERENCES states (state_id) ON DELETE SET NULL
);
