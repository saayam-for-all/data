\set ON_ERROR_STOP on
BEGIN;
SET TIME ZONE 'UTC';
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA virginia_dev_saayam_rdbms;
\i /schema/saayam_schema.sql

\copy virginia_dev_saayam_rdbms.help_categories FROM '/fixtures/help_categories.csv' WITH (FORMAT csv, HEADER true, NULL '\N', ENCODING 'UTF8')
\copy virginia_dev_saayam_rdbms.help_categories_map FROM '/fixtures/help_categories_map.csv' WITH (FORMAT csv, HEADER true, NULL '\N', ENCODING 'UTF8')
\copy virginia_dev_saayam_rdbms.request_for FROM '/fixtures/request_for.csv' WITH (FORMAT csv, HEADER true, NULL '\N', ENCODING 'UTF8')
\copy virginia_dev_saayam_rdbms.request_isleadvol FROM '/fixtures/request_isleadvol.csv' WITH (FORMAT csv, HEADER true, NULL '\N', ENCODING 'UTF8')
\copy virginia_dev_saayam_rdbms.request_types FROM '/fixtures/request_types.csv' WITH (FORMAT csv, HEADER true, NULL '\N', ENCODING 'UTF8')
\copy virginia_dev_saayam_rdbms.request_priorities FROM '/fixtures/request_priorities.csv' WITH (FORMAT csv, HEADER true, NULL '\N', ENCODING 'UTF8')
\copy virginia_dev_saayam_rdbms.request_statuses FROM '/fixtures/request_statuses.csv' WITH (FORMAT csv, HEADER true, NULL '\N', ENCODING 'UTF8')
\copy virginia_dev_saayam_rdbms.users (user_id) FROM '/fixtures/users.csv' WITH (FORMAT csv, HEADER true, NULL '\N', ENCODING 'UTF8')
\copy virginia_dev_saayam_rdbms.requests FROM '/fixtures/requests.csv' WITH (FORMAT csv, HEADER true, NULL '\N', ENCODING 'UTF8')

-- COPY supplies the fixed lookup IDs, so synchronize the serial sequences.
SELECT setval(pg_get_serial_sequence('virginia_dev_saayam_rdbms.request_for', 'req_for_id'), (SELECT max(req_for_id) FROM virginia_dev_saayam_rdbms.request_for));
SELECT setval(pg_get_serial_sequence('virginia_dev_saayam_rdbms.request_isleadvol', 'req_islead_id'), (SELECT max(req_islead_id) FROM virginia_dev_saayam_rdbms.request_isleadvol));
SELECT setval(pg_get_serial_sequence('virginia_dev_saayam_rdbms.request_types', 'req_type_id'), (SELECT max(req_type_id) FROM virginia_dev_saayam_rdbms.request_types));
SELECT setval(pg_get_serial_sequence('virginia_dev_saayam_rdbms.request_priorities', 'req_priority_id'), (SELECT max(req_priority_id) FROM virginia_dev_saayam_rdbms.request_priorities));
SELECT setval(pg_get_serial_sequence('virginia_dev_saayam_rdbms.request_statuses', 'req_status_id'), (SELECT max(req_status_id) FROM virginia_dev_saayam_rdbms.request_statuses));
COMMIT;
