-- Spot-check that the special cases survived loading. Run after load.sql:
--     psql -d saayam_mock -f verify.sql
\pset pager off
SET search_path TO virginia_dev_saayam_rdbms;

\echo 'Row counts (expect 500 requests, 150 users, 61 categories, 53 map rows)'
SELECT (SELECT count(*) FROM requests) AS requests, (SELECT count(*) FROM users) AS users,
       (SELECT count(*) FROM help_categories) AS categories, (SELECT count(*) FROM help_categories_map) AS map_rows;

\echo 'Case 1: nulls (expect lead 493 null, beneficiary 18 null)'
SELECT count(*) FILTER (WHERE lead_volunteer_id IS NULL) AS lead_null,
       count(*) FILTER (WHERE beneficiary_id IS NULL) AS beneficiary_null FROM requests;

\echo 'Case 1: inner join on lead volunteer (expect 7, the trap)'
SELECT count(*) FROM requests r JOIN users u ON u.user_id = r.lead_volunteer_id;

\echo 'Case 2: shared last_updated_at (expect two values, 4 rows each)'
SELECT last_updated_at, count(*) FROM requests GROUP BY 1 HAVING count(*) > 1;

\echo 'Case 3: updated before submitted (expect 3)'
SELECT count(*) FROM requests WHERE last_updated_at < submission_date;

\echo 'Case 5: non-ASCII descriptions (expect 18)'
SELECT count(*) FROM requests WHERE req_desc ~ '[^\x01-\x7F]';

\echo 'Case 7: empty vs NULL (each column should show both)'
SELECT 'req_doc_link' AS col, count(*) FILTER (WHERE req_doc_link = '') AS empty, count(*) FILTER (WHERE req_doc_link IS NULL) AS nulls FROM requests
UNION ALL SELECT 'audio_req_desc', count(*) FILTER (WHERE audio_req_desc = ''), count(*) FILTER (WHERE audio_req_desc IS NULL) FROM requests
UNION ALL SELECT 'deletion_reason', count(*) FILTER (WHERE deletion_reason = ''), count(*) FILTER (WHERE deletion_reason IS NULL) FROM requests;

\echo 'Case 8: maximum lengths in characters and bytes'
SELECT max(char_length(req_subj)) AS subj_chars, max(octet_length(req_subj)) AS subj_bytes,
       max(char_length(req_desc)) AS desc_chars, max(octet_length(req_desc)) AS desc_bytes,
       max(char_length(audio_req_desc)) AS audio_chars FROM requests;

\echo 'Case 9: lookup values with no request (expect no rows)'
SELECT 'status', req_status FROM request_statuses s WHERE NOT EXISTS (SELECT 1 FROM requests r WHERE r.req_status_id = s.req_status_id)
UNION ALL SELECT 'priority', req_priority FROM request_priorities p WHERE NOT EXISTS (SELECT 1 FROM requests r WHERE r.req_priority_id = p.req_priority_id)
UNION ALL SELECT 'category', cat_id FROM help_categories c WHERE NOT EXISTS (SELECT 1 FROM requests r WHERE r.req_cat_id = c.cat_id);

\echo 'Case 10: flagged with no lead volunteer (expect 13)'
SELECT count(*) FROM requests WHERE req_islead_id = 1 AND lead_volunteer_id IS NULL;
