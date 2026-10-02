-- Run from data-analytics/mock-data-generation with:
-- psql -X -v ON_ERROR_STOP=1 -d saayam_mock_301 -f load_local.sql
-- Requires the current Virginia schema, PostGIS, and empty in-scope tables.
-- This script is for an isolated local development database.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL TIME ZONE 'UTC';
SET LOCAL datestyle = 'ISO, YMD';

-- Refuse to append to an existing dataset. No table is truncated or dropped.
LOCK TABLE virginia_dev_saayam_rdbms.countries,
           virginia_dev_saayam_rdbms.states,
           virginia_dev_saayam_rdbms.cities,
           virginia_dev_saayam_rdbms.help_categories,
           virginia_dev_saayam_rdbms.users,
           virginia_dev_saayam_rdbms.user_skills,
           virginia_dev_saayam_rdbms.user_locations,
           virginia_dev_saayam_rdbms.volunteer_details,
           virginia_dev_saayam_rdbms.volunteer_locations,
           virginia_dev_saayam_rdbms.organizations IN SHARE ROW EXCLUSIVE MODE;
DO $$
DECLARE t text; populated boolean;
BEGIN
    FOREACH t IN ARRAY ARRAY['countries','states','cities','help_categories','users','user_skills','user_locations','volunteer_details','volunteer_locations','organizations'] LOOP
        EXECUTE format('SELECT EXISTS (SELECT 1 FROM virginia_dev_saayam_rdbms.%I)', t)
          INTO populated;
        IF populated THEN
            RAISE EXCEPTION 'Table % is not empty; use a fresh local database', t;
        END IF;
    END LOOP;
END $$;

\ir seed_local_lookups.sql

-- Only the two ID-replacement triggers are disabled; FK/check triggers remain active.
-- ALTER TABLE changes table state, not a session setting. Both are restored before COMMIT.
ALTER TABLE virginia_dev_saayam_rdbms.users DISABLE TRIGGER before_insert_users;
ALTER TABLE virginia_dev_saayam_rdbms.organizations DISABLE TRIGGER before_insert_organizations;

\copy virginia_dev_saayam_rdbms.countries FROM 'output_csv_files/countries.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');
\copy virginia_dev_saayam_rdbms.states FROM 'output_csv_files/states.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');
\copy virginia_dev_saayam_rdbms.cities FROM 'output_csv_files/cities.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');
\copy virginia_dev_saayam_rdbms.help_categories FROM 'output_csv_files/help_categories.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');
\copy virginia_dev_saayam_rdbms.users FROM 'output_csv_files/users.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');
\copy virginia_dev_saayam_rdbms.user_skills FROM 'output_csv_files/user_skills.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');
\copy virginia_dev_saayam_rdbms.user_locations FROM 'output_csv_files/user_locations.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');
\copy virginia_dev_saayam_rdbms.volunteer_details FROM 'output_csv_files/volunteer_details.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');
\copy virginia_dev_saayam_rdbms.volunteer_locations FROM 'output_csv_files/volunteer_locations.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');
\copy virginia_dev_saayam_rdbms.organizations FROM 'output_csv_files/organizations.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');

ALTER TABLE virginia_dev_saayam_rdbms.users ENABLE TRIGGER before_insert_users;
ALTER TABLE virginia_dev_saayam_rdbms.organizations ENABLE TRIGGER before_insert_organizations;

-- Explicit CSV/seed IDs do not advance SERIAL sequences. Leave future inserts usable.
SELECT setval(pg_get_serial_sequence('virginia_dev_saayam_rdbms.countries','country_id'),
              (SELECT max(country_id) FROM virginia_dev_saayam_rdbms.countries));
SELECT setval(pg_get_serial_sequence('virginia_dev_saayam_rdbms.cities','city_id'),
              (SELECT max(city_id) FROM virginia_dev_saayam_rdbms.cities));
SELECT setval(pg_get_serial_sequence('virginia_dev_saayam_rdbms.supporting_languages','language_id'),
              (SELECT max(language_id) FROM virginia_dev_saayam_rdbms.supporting_languages));
SELECT setval(pg_get_serial_sequence('virginia_dev_saayam_rdbms.user_status','user_status_id'),
              (SELECT max(user_status_id) FROM virginia_dev_saayam_rdbms.user_status));
COMMIT;

