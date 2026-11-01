-- Load the generated mock data into a local Postgres.
-- Run from this folder (\copy paths are relative to where psql runs):
--     psql -d saayam_mock -f load.sql
-- Rebuilds the schema from scratch each time.
\pset pager off
\set ON_ERROR_STOP on


CREATE EXTENSION IF NOT EXISTS postgis;
DROP SCHEMA IF EXISTS virginia_dev_saayam_rdbms CASCADE;
CREATE SCHEMA virginia_dev_saayam_rdbms;

\ir saayam_schema.sql

\copy virginia_dev_saayam_rdbms.request_for (req_for_id, req_for, req_for_desc, last_updated_at) FROM 'output/request_for.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy virginia_dev_saayam_rdbms.request_isleadvol (req_islead_id, req_islead, req_islead_desc, last_updated_at) FROM 'output/request_isleadvol.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy virginia_dev_saayam_rdbms.request_types (req_type_id, req_type, req_type_desc, last_updated_at) FROM 'output/request_types.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy virginia_dev_saayam_rdbms.request_priorities (req_priority_id, req_priority, req_priority_desc, last_updated_at) FROM 'output/request_priorities.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy virginia_dev_saayam_rdbms.request_statuses (req_status_id, req_status, req_status_desc, last_updated_at) FROM 'output/request_statuses.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy virginia_dev_saayam_rdbms.help_categories (cat_id, cat_name, cat_desc, last_updated_at) FROM 'output/help_categories.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy virginia_dev_saayam_rdbms.help_categories_map (parent_id, child_id, last_updated_at) FROM 'output/help_categories_map.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy virginia_dev_saayam_rdbms.users (user_id) FROM 'output/users.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy virginia_dev_saayam_rdbms.requests (req_id, creator_id, beneficiary_id, lead_volunteer_id, req_cat_id, req_for_id, req_islead_id, req_type_id, req_priority_id, req_status_id, req_subj, req_desc, req_doc_link, audio_req_desc, deletion_reason, req_loc, created_loc, iscalamity, to_public, submission_date, serviced_date, last_updated_at) FROM 'output/requests.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')

-- Lookup IDs were inserted explicitly, so move each serial past them.
SELECT setval(pg_get_serial_sequence('virginia_dev_saayam_rdbms.request_for', 'req_for_id'), (SELECT max(req_for_id) FROM virginia_dev_saayam_rdbms.request_for));
SELECT setval(pg_get_serial_sequence('virginia_dev_saayam_rdbms.request_isleadvol', 'req_islead_id'), (SELECT max(req_islead_id) FROM virginia_dev_saayam_rdbms.request_isleadvol));
SELECT setval(pg_get_serial_sequence('virginia_dev_saayam_rdbms.request_types', 'req_type_id'), (SELECT max(req_type_id) FROM virginia_dev_saayam_rdbms.request_types));
SELECT setval(pg_get_serial_sequence('virginia_dev_saayam_rdbms.request_priorities', 'req_priority_id'), (SELECT max(req_priority_id) FROM virginia_dev_saayam_rdbms.request_priorities));
SELECT setval(pg_get_serial_sequence('virginia_dev_saayam_rdbms.request_statuses', 'req_status_id'), (SELECT max(req_status_id) FROM virginia_dev_saayam_rdbms.request_statuses));
