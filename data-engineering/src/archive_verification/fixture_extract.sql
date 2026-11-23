-- REFERENCE EXTRACT - TEST FIXTURE ONLY. NOT THE PRODUCTION EXTRACT.
--
-- Task 2 (issue #574) owns the real `Data_ArchiveRequestData` extract. That
-- issue is closed but its code is not merged into `dev`, `main` or `test`, so
-- there is nothing in this repository for #586's checks to run against.
--
-- This file exists so the seven checks can be executed and proven today. It is
-- deliberately the simplest query that satisfies the contract #586 verifies, so
-- that a check which passes here passes for the right reason. When Task 2's
-- extract lands, point the verifier at it instead and nothing else changes:
--
--   python -m src.archive_verification.verify --extractor src.your_module:extract
--
-- Do not promote this file to production use. It has no masking (issue #585
-- owns PII in `req_subj` / `req_desc`), no S3 write path and no watermark
-- table; it is a query, not a pipeline.
--
-- Two placeholders are substituted before execution, so one file serves both
-- the SQLite local copy and the real Postgres source:
--
--   {prefix}  table-name prefix - '' for SQLite, 'virginia_dev_saayam_rdbms.'
--             for Postgres
--   {p}       parameter marker  - '?' for sqlite3, '%s' for psycopg2
--
-- Three properties of this query are load-bearing, and the mutation table in
-- README.md shows which check catches the loss of each:
--
--   1. Every join is a LEFT JOIN. An INNER JOIN on `lead_volunteer_id` would
--      return 3 of 221 real rows and the count would look small rather than
--      wrong. That is the failure #586 most wants ruled out.
--   2. The window is half-open, `>= low AND < high`. A closed window
--      double-archives rows that sit exactly on a boundary; an exclusive low
--      bound drops them. Real rows do share `last_updated_at` to the
--      microsecond.
--   3. `ORDER BY req_id` is what makes a re-run byte-identical. Without an
--      ORDER BY, row order is unspecified and check 6 can only compare content.
--
-- `help_categories_map` is deliberately absent. It is the category tree, not a
-- join table for requests, and joining through it fans each request out into
-- one row per child category.

SELECT
    r.req_id,

    -- Kept alongside the readable words below, not replaced by them. A row
    -- whose id is present while its word is empty is exactly the evidence
    -- check 5 needs: the reference is broken and the row survived anyway.
    r.creator_id,
    r.beneficiary_id,
    r.lead_volunteer_id,
    cu.user_id  AS creator_user_id,
    bu.user_id  AS beneficiary_user_id,
    lu.user_id  AS lead_volunteer_user_id,

    r.req_cat_id,
    hc.cat_name,
    r.req_for_id,
    rf.req_for,
    r.req_islead_id,
    ril.req_islead,
    r.req_type_id,
    rt.req_type,
    r.req_priority_id,
    rp.req_priority,
    r.req_status_id,
    rs.req_status,

    r.req_subj,
    r.req_desc,
    r.req_doc_link,
    r.audio_req_desc,
    r.deletion_reason,

    r.req_loc,
    r.created_loc,
    r.iscalamity,
    r.to_public,

    r.submission_date,
    r.serviced_date,
    r.last_updated_at

FROM {prefix}requests r
LEFT JOIN {prefix}users              cu  ON cu.user_id         = r.creator_id
LEFT JOIN {prefix}users              bu  ON bu.user_id         = r.beneficiary_id
LEFT JOIN {prefix}users              lu  ON lu.user_id         = r.lead_volunteer_id
LEFT JOIN {prefix}help_categories    hc  ON hc.cat_id          = r.req_cat_id
LEFT JOIN {prefix}request_for        rf  ON rf.req_for_id      = r.req_for_id
LEFT JOIN {prefix}request_isleadvol  ril ON ril.req_islead_id  = r.req_islead_id
LEFT JOIN {prefix}request_types      rt  ON rt.req_type_id     = r.req_type_id
LEFT JOIN {prefix}request_priorities rp  ON rp.req_priority_id = r.req_priority_id
LEFT JOIN {prefix}request_statuses   rs  ON rs.req_status_id   = r.req_status_id

WHERE r.last_updated_at >= {p}
  AND r.last_updated_at <  {p}

ORDER BY r.req_id
