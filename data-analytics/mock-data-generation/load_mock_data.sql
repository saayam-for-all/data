-- Load the generated mock-data CSVs into a local PostgreSQL database.
--
-- Prerequisites:
--   1. PostgreSQL with the PostGIS extension (the two location tables use
--      geography(Point, 4326)).
--   2. The virginia_dev_saayam_rdbms schema already created from the DDL in
--      https://github.com/saayam-for-all/database (ddl/Tables/), with the
--      "Table after changes" updates from the wiki applied.
--
-- Run from this directory so the relative paths resolve:
--   psql -d saayam_local -v ON_ERROR_STOP=1 -f load_mock_data.sql
--
-- Tables are loaded in foreign-key order. Empty CSV fields are read as NULL,
-- which is the default for FORMAT csv.

\set ON_ERROR_STOP on
SET search_path TO virginia_dev_saayam_rdbms;

-- Insert triggers on users and organizations overwrite the supplied id with a
-- sequence-generated one. The generated ids already follow those sequences, so
-- disable the triggers for the load to keep the foreign keys in the other
-- files pointing at the right rows.
ALTER TABLE users DISABLE TRIGGER before_insert_users;
ALTER TABLE organizations DISABLE TRIGGER before_insert_organizations;

\copy countries           FROM 'countries.csv'           WITH (FORMAT csv, HEADER true)
\copy states              FROM 'states.csv'              WITH (FORMAT csv, HEADER true)
\copy cities              FROM 'cities.csv'              WITH (FORMAT csv, HEADER true)
\copy help_categories     FROM 'help_categories.csv'     WITH (FORMAT csv, HEADER true)
\copy users               FROM 'users.csv'               WITH (FORMAT csv, HEADER true)
\copy volunteer_details   FROM 'volunteer_details.csv'   WITH (FORMAT csv, HEADER true)
\copy user_skills         FROM 'user_skills.csv'         WITH (FORMAT csv, HEADER true)
\copy user_locations      FROM 'user_locations.csv'      WITH (FORMAT csv, HEADER true)
\copy volunteer_locations FROM 'volunteer_locations.csv' WITH (FORMAT csv, HEADER true)
\copy organizations       FROM 'organizations.csv'       WITH (FORMAT csv, HEADER true)

ALTER TABLE users ENABLE TRIGGER before_insert_users;
ALTER TABLE organizations ENABLE TRIGGER before_insert_organizations;

-- The location tables also carry an INSERT trigger that turns an INSERT into
-- an UPDATE when the user already has a row. That is harmless here because
-- each user appears at most once per file (user_id is the primary key).
