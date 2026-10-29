--
-- Bookkeeping tables for the requests archival Lambda (#416).
--
-- These two tables are the pipeline's own. They are the only tables it writes
-- to. Against application tables it issues SELECT and nothing else.
--
-- Created in the application schema by the DBA. The pipeline needs
-- SELECT / INSERT / UPDATE on these two tables and nothing further.
--
-- Run once, as a role allowed to create objects in the schema. There are no
-- DROP statements here on purpose: dropping archive_watermark loses the record
-- of where the last run stopped, and the next run would re-export from
-- initial_value.
--

SET search_path TO virginia_dev_saayam_rdbms;


-- Where the last successful run stopped, one row per (table, stream).
-- Written only after S3 confirms the upload.
CREATE TABLE IF NOT EXISTS archive_watermark (
    source_table   varchar(100) NOT NULL,
    stream         varchar(50)  NOT NULL,
    last_value_at  timestamp(6),
    last_run_at    timestamp(6),
    PRIMARY KEY (source_table, stream)
);

COMMENT ON TABLE  archive_watermark IS
    'Last archived source timestamp per table and stream. Advanced only after a confirmed S3 upload.';
COMMENT ON COLUMN archive_watermark.last_value_at IS
    'Upper bound of the last successful run. The next run selects rows > this value.';
COMMENT ON COLUMN archive_watermark.last_run_at IS
    'When a run last touched this row, including runs that found nothing.';


-- One row per table per invocation, including runs that exported nothing and
-- runs that failed. Without the empty rows, "fired and found nothing" and
-- "never fired" look identical.
CREATE TABLE IF NOT EXISTS archive_run_log (
    run_id           bigserial    PRIMARY KEY,
    invocation_id    varchar(100),
    source_table     varchar(100),
    stream           varchar(50),
    started_at       timestamp(6),
    finished_at      timestamp(6),
    range_from       timestamp(6),
    range_to         timestamp(6),
    s3_key           varchar(500),
    source_rows      bigint,
    rows_written     bigint,
    bytes_written    bigint,
    columns_dropped  integer,
    columns_masked   integer,
    status           varchar(30),
    error_message    text,
    triggered_by     varchar(50)
);

COMMENT ON TABLE  archive_run_log IS
    'One row per table per invocation. Status is success, nothing_to_do or failed.';
COMMENT ON COLUMN archive_run_log.invocation_id IS
    'AWS request ID, so a row here can be matched to its CloudWatch log stream.';
COMMENT ON COLUMN archive_run_log.source_rows IS
    'Rows counted in the source window. Must equal rows_written or the run fails and the watermark is not advanced.';

CREATE INDEX IF NOT EXISTS idx_archive_run_log_table_started
    ON archive_run_log (source_table, started_at DESC);


-- Grants. Replace the role name with the one the Lambda connects as.
--
-- GRANT SELECT, INSERT, UPDATE ON archive_watermark TO <archival_role>;
-- GRANT SELECT, INSERT         ON archive_run_log   TO <archival_role>;
-- GRANT USAGE, SELECT ON SEQUENCE archive_run_log_run_id_seq TO <archival_role>;


-- Verification
--
--   SELECT * FROM archive_watermark;
--   SELECT run_id, source_table, status, range_from, range_to,
--          source_rows, rows_written, bytes_written, error_message
--   FROM archive_run_log ORDER BY run_id DESC LIMIT 20;
