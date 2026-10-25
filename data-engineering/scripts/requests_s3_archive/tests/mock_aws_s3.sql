-- Test-only stand-in for the RDS aws_s3 extension. It runs the export query
-- (so counts are real) and records the call instead of writing to S3.
-- Behavior knobs live in archival_test.behavior (one row, reset per test).
CREATE SCHEMA IF NOT EXISTS aws_s3;
CREATE SCHEMA IF NOT EXISTS archival_test;

CREATE TABLE IF NOT EXISTS archival_test.exports (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bucket text, file_path text, region text, options text, query text,
    rows_uploaded bigint
);

CREATE TABLE IF NOT EXISTS archival_test.behavior (
    fail_always boolean NOT NULL DEFAULT false,
    row_delta bigint NOT NULL DEFAULT 0,      -- report this many extra/missing rows
    sleep_seconds numeric NOT NULL DEFAULT 0  -- pause inside each export
);

CREATE OR REPLACE FUNCTION aws_s3.query_export_to_s3(
    query text, bucket text, file_path text,
    region text DEFAULT NULL, options text DEFAULT NULL
) RETURNS TABLE (rows_uploaded bigint, files_uploaded bigint,
                 bytes_uploaded bigint)
LANGUAGE plpgsql AS $$
DECLARE
    knobs archival_test.behavior%ROWTYPE;
    n bigint;
BEGIN
    SELECT * INTO knobs FROM archival_test.behavior LIMIT 1;
    IF knobs.fail_always THEN
        RAISE EXCEPTION 'mock S3 upload failed';
    END IF;
    EXECUTE format('SELECT count(*) FROM (%s) q', query) INTO n;
    IF knobs.sleep_seconds > 0 THEN
        PERFORM pg_sleep(knobs.sleep_seconds);
    END IF;
    n := n + knobs.row_delta;
    INSERT INTO archival_test.exports(bucket, file_path, region, options,
                                      query, rows_uploaded)
    VALUES (bucket, file_path, region, options, query, n);
    RETURN QUERY SELECT n, 1::bigint, n * 100;
END;
$$;
