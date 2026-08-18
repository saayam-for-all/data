-- Local dev seed for the Organization Analytics API (issue #228).
--
-- Confirmed columns (org_name, city_name, phone, email, web_url, mission,
-- source, org_type, is_collaborator) come from src/saayam-org-aggregator and
-- the unmerged sanobar_113 branch's org queries. org_size, rating, and
-- registered_at are ASSUMED (no DDL for this table exists in the repo) --
-- verify against the real virginia_dev_saayam_rdbms.organizations table and
-- update src/main.py's ORG_SIZE_COLUMN / ORG_RATING_COLUMN /
-- ORG_REGISTERED_AT_COLUMN + this file if the real names differ.

CREATE SCHEMA IF NOT EXISTS virginia_dev_saayam_rdbms;

CREATE TABLE IF NOT EXISTS virginia_dev_saayam_rdbms.organizations (
    org_id SERIAL PRIMARY KEY,
    org_name TEXT NOT NULL,
    city_name TEXT,
    phone TEXT,
    email TEXT,
    web_url TEXT,
    mission TEXT,
    source TEXT,
    org_type TEXT,
    is_collaborator BOOLEAN DEFAULT FALSE,
    org_size TEXT,               -- ASSUMED
    rating NUMERIC(3, 2),        -- ASSUMED
    registered_at TIMESTAMPTZ DEFAULT now()  -- ASSUMED
);

INSERT INTO virginia_dev_saayam_rdbms.organizations
    (org_name, city_name, phone, email, web_url, mission, source, org_type, is_collaborator, org_size, rating, registered_at)
VALUES
    ('Helping Hands Reston', 'Reston', '555-0100', 'contact@helpinghands.org', 'https://helpinghands.org', 'Education', 'manual', 'Nonprofit', TRUE, 'Medium', 4.80, now() - interval '2 days'),
    ('Fairfax Food Bank', 'Fairfax', '555-0101', 'info@fairfaxfoodbank.org', 'https://fairfaxfoodbank.org', 'Hunger Relief', 'manual', 'Nonprofit', TRUE, 'Large', 4.50, now() - interval '5 days'),
    ('Arlington Shelter Network', 'Arlington', '555-0102', 'hello@arlingtonshelter.org', 'https://arlingtonshelter.org', 'Housing', 'manual', 'Nonprofit', FALSE, 'Small', 4.20, now() - interval '15 days'),
    ('Loudoun Literacy Council', 'Leesburg', '555-0103', 'contact@loudounliteracy.org', 'https://loudounliteracy.org', 'Education', 'genai', 'Community Group', FALSE, 'Small', 3.90, now() - interval '25 days'),
    ('Alexandria Youth Services', 'Alexandria', '555-0104', 'info@alexyouth.org', 'https://alexyouth.org', 'Youth Development', 'manual', 'Nonprofit', TRUE, 'Medium', 4.60, now() - interval '45 days'),
    ('Prince William Free Clinic', 'Woodbridge', '555-0105', 'contact@pwfreeclinic.org', 'https://pwfreeclinic.org', 'Healthcare', 'manual', 'Nonprofit', TRUE, 'Large', 4.70, now() - interval '90 days'),
    ('Manassas Senior Center', 'Manassas', '555-0106', 'info@manassasseniors.org', 'https://manassasseniors.org', 'Elder Care', 'genai', 'Community Group', FALSE, 'Small', NULL, now() - interval '120 days'),
    ('Herndon Immigrant Aid', 'Herndon', '555-0107', 'contact@herndonimmigrant.org', 'https://herndonimmigrant.org', 'Immigration Services', 'manual', 'Nonprofit', FALSE, 'Medium', 4.10, now() - interval '200 days'),
    ('Reston Environmental Coalition', 'Reston', '555-0108', 'info@restonenv.org', 'https://restonenv.org', 'Environment', 'manual', 'Nonprofit', TRUE, 'Medium', 4.30, now() - interval '400 days'),
    ('Fairfax Disability Alliance', 'Fairfax', '555-0109', 'contact@fairfaxdisability.org', 'https://fairfaxdisability.org', 'Disability Services', 'genai', 'Nonprofit', FALSE, 'Small', 4.90, now() - interval '500 days');
