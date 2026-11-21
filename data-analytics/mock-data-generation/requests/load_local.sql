-- Loads the generated CSVs into a local database.
-- Run from the requests folder: psql -d saayam_mock -f load_local.sql
SET client_encoding TO 'UTF8';
SET search_path TO virginia_dev_saayam_rdbms, public;

\cd output
\copy request_for FROM 'request_for.csv' CSV HEADER
\copy request_isleadvol FROM 'request_isleadvol.csv' CSV HEADER
\copy request_types FROM 'request_types.csv' CSV HEADER
\copy request_priorities FROM 'request_priorities.csv' CSV HEADER
\copy request_statuses FROM 'request_statuses.csv' CSV HEADER
\copy help_categories FROM 'help_categories.csv' CSV HEADER
\copy help_categories_map FROM 'help_categories_map.csv' CSV HEADER
\copy users (user_id) FROM 'users.csv' CSV HEADER
\copy requests FROM 'requests.csv' CSV HEADER

SELECT count(*) AS requests,
       count(*) FILTER (WHERE lead_volunteer_id IS NULL) AS no_lead,
       count(*) FILTER (WHERE beneficiary_id IS NULL) AS no_beneficiary,
       count(*) FILTER (WHERE req_islead_id = 1 AND lead_volunteer_id IS NULL) AS flagged_but_no_lead
FROM requests;
