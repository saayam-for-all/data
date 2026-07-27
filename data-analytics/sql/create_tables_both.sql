-- create_tables.sql
-- Creates the 5 tables actually queried by volunteer_application_analytics.py:
-- users, volunteer_details, country, user_skills, help_categories
-- Run once per schema (virginia_dev_saayam_rdbms and ireland_dev_saayam_rdbms).

-- ===================== country =====================
CREATE TABLE IF NOT EXISTS virginia_dev_saayam_rdbms.country (
    country_id      INTEGER PRIMARY KEY,
    country_name    VARCHAR(100),
    phone_code      VARCHAR(5),
    country_code    VARCHAR(6),
    last_update_date TIMESTAMP,
    is_eu_member    BOOLEAN
);

-- ===================== help_categories =====================
CREATE TABLE IF NOT EXISTS virginia_dev_saayam_rdbms.help_categories (
    cat_id      VARCHAR(50) PRIMARY KEY,
    cat_name    VARCHAR(100),
    cat_desc    VARCHAR(150)
);

-- ===================== users =====================
CREATE TABLE IF NOT EXISTS virginia_dev_saayam_rdbms.users (
    user_id                             VARCHAR(255) PRIMARY KEY,
    state_id                            VARCHAR(50),
    country_id                          INTEGER,
    user_status_id                      BIGINT,
    user_category_id                    INTEGER,
    full_name                           VARCHAR(255),
    first_name                          VARCHAR(255),
    middle_name                         VARCHAR(255),
    last_name                           VARCHAR(255),
    primary_email_address               VARCHAR(255),
    primary_phone_number                VARCHAR(255),
    addr_ln1                            VARCHAR(255),
    addr_ln2                            VARCHAR(255),
    addr_ln3                            VARCHAR(255),
    city_name                           VARCHAR(255),
    zip_code                            VARCHAR(255),
    last_location                       VARCHAR(255),
    last_update_date                    TIMESTAMPTZ,
    time_zone                           VARCHAR(255),
    profile_picture_path                VARCHAR(255),
    gender                               VARCHAR(255),
    language_1                          VARCHAR(255),
    language_2                          VARCHAR(255),
    language_3                          VARCHAR(255),
    promotion_wizard_stage              INTEGER,
    promotion_wizard_last_update_date   TIMESTAMPTZ,
    external_auth_provider              VARCHAR(20),
    dob                                  DATE
);

-- ===================== volunteer_details =====================
CREATE TABLE IF NOT EXISTS virginia_dev_saayam_rdbms.volunteer_details (
    user_id               VARCHAR(255) PRIMARY KEY,
    terms_and_conditions  BOOLEAN,
    terms_accepted_at     TIMESTAMP,
    govt_id_path1         TEXT,
    govt_id_path2         TEXT,
    path1_updated_at      TIMESTAMP,
    path2_updated_at      TIMESTAMP,
    availability_days     JSONB,
    availability_times    JSONB,
    created_at            TIMESTAMP,
    last_updated_at       TIMESTAMP,
    CONSTRAINT fk_vd_user FOREIGN KEY (user_id) REFERENCES virginia_dev_saayam_rdbms.users(user_id)
);

-- ===================== user_skills =====================
CREATE TABLE IF NOT EXISTS virginia_dev_saayam_rdbms.user_skills (
    user_id           VARCHAR(255),
    cat_id            VARCHAR(50),
    created_date      TIMESTAMP,
    last_update_date  TIMESTAMP,
    PRIMARY KEY (user_id, cat_id),
    CONSTRAINT fk_us_user FOREIGN KEY (user_id) REFERENCES virginia_dev_saayam_rdbms.users(user_id),
    CONSTRAINT fk_us_cat FOREIGN KEY (cat_id) REFERENCES virginia_dev_saayam_rdbms.help_categories(cat_id)
);
-- create_tables.sql
-- Creates the 5 tables actually queried by volunteer_application_analytics.py:
-- users, volunteer_details, country, user_skills, help_categories
-- Run once per schema (virginia_dev_saayam_rdbms and ireland_dev_saayam_rdbms).

-- ===================== country =====================
CREATE TABLE IF NOT EXISTS ireland_dev_saayam_rdbms.country (
    country_id      INTEGER PRIMARY KEY,
    country_name    VARCHAR(100),
    phone_code      VARCHAR(5),
    country_code    VARCHAR(6),
    last_update_date TIMESTAMP,
    is_eu_member    BOOLEAN
);

-- ===================== help_categories =====================
CREATE TABLE IF NOT EXISTS ireland_dev_saayam_rdbms.help_categories (
    cat_id      VARCHAR(50) PRIMARY KEY,
    cat_name    VARCHAR(100),
    cat_desc    VARCHAR(150)
);

-- ===================== users =====================
CREATE TABLE IF NOT EXISTS ireland_dev_saayam_rdbms.users (
    user_id                             VARCHAR(255) PRIMARY KEY,
    state_id                            VARCHAR(50),
    country_id                          INTEGER,
    user_status_id                      BIGINT,
    user_category_id                    INTEGER,
    full_name                           VARCHAR(255),
    first_name                          VARCHAR(255),
    middle_name                         VARCHAR(255),
    last_name                           VARCHAR(255),
    primary_email_address               VARCHAR(255),
    primary_phone_number                VARCHAR(255),
    addr_ln1                            VARCHAR(255),
    addr_ln2                            VARCHAR(255),
    addr_ln3                            VARCHAR(255),
    city_name                           VARCHAR(255),
    zip_code                            VARCHAR(255),
    last_location                       VARCHAR(255),
    last_update_date                    TIMESTAMPTZ,
    time_zone                           VARCHAR(255),
    profile_picture_path                VARCHAR(255),
    gender                               VARCHAR(255),
    language_1                          VARCHAR(255),
    language_2                          VARCHAR(255),
    language_3                          VARCHAR(255),
    promotion_wizard_stage              INTEGER,
    promotion_wizard_last_update_date   TIMESTAMPTZ,
    external_auth_provider              VARCHAR(20),
    dob                                  DATE
);

-- ===================== volunteer_details =====================
CREATE TABLE IF NOT EXISTS ireland_dev_saayam_rdbms.volunteer_details (
    user_id               VARCHAR(255) PRIMARY KEY,
    terms_and_conditions  BOOLEAN,
    terms_accepted_at     TIMESTAMP,
    govt_id_path1         TEXT,
    govt_id_path2         TEXT,
    path1_updated_at      TIMESTAMP,
    path2_updated_at      TIMESTAMP,
    availability_days     JSONB,
    availability_times    JSONB,
    created_at            TIMESTAMP,
    last_updated_at       TIMESTAMP,
    CONSTRAINT fk_vd_user FOREIGN KEY (user_id) REFERENCES ireland_dev_saayam_rdbms.users(user_id)
);

-- ===================== user_skills =====================
CREATE TABLE IF NOT EXISTS ireland_dev_saayam_rdbms.user_skills (
    user_id           VARCHAR(255),
    cat_id            VARCHAR(50),
    created_date      TIMESTAMP,
    last_update_date  TIMESTAMP,
    PRIMARY KEY (user_id, cat_id),
    CONSTRAINT fk_us_user FOREIGN KEY (user_id) REFERENCES ireland_dev_saayam_rdbms.users(user_id),
    CONSTRAINT fk_us_cat FOREIGN KEY (cat_id) REFERENCES ireland_dev_saayam_rdbms.help_categories(cat_id)
);
