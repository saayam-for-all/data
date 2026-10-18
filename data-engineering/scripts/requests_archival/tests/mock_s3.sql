-- LOCAL TEST DATABASE ONLY. This function never contacts AWS.
CREATE SCHEMA aws_s3;
CREATE SCHEMA archival_test;
CREATE TABLE archival_test.exports (object_key text, payload jsonb);
CREATE TABLE archival_test.control (mode text NOT NULL);
INSERT INTO archival_test.control VALUES ('success');

CREATE FUNCTION aws_s3.query_export_to_s3(
    query text, bucket text, file_path text, region text, options text,
    OUT rows_uploaded bigint, OUT files_uploaded bigint, OUT bytes_uploaded bigint
)
RETURNS record LANGUAGE plpgsql AS $$
DECLARE
    mode text;
    payload jsonb;
BEGIN
    SELECT c.mode INTO mode FROM archival_test.control c;
    IF mode = 'failure' OR (mode = 'partial_failure' AND
        EXISTS (SELECT 1 FROM archival_test.exports)) THEN
        RAISE EXCEPTION 'Simulated S3 upload failure';
    END IF;
    IF options <> 'format csv, header true, encoding ''UTF8''' THEN
        RAISE EXCEPTION 'CSV options missing';
    END IF;
    IF mode = 'concurrent_update' THEN
        -- Simulate the live source changing after the batch snapshot.
        UPDATE public.requests SET status = 'resolved',
            last_updated_at = clock_timestamp();
        UPDATE archival_test.control SET mode = 'success';
    END IF;
    EXECUTE 'SELECT count(*), jsonb_agg(to_jsonb(batch)) FROM (' || query ||
            ') batch' INTO rows_uploaded, payload;
    INSERT INTO archival_test.exports VALUES (file_path, payload);
    files_uploaded := 1;
    bytes_uploaded := octet_length(payload::text);
    IF mode = 'mismatch' THEN rows_uploaded := rows_uploaded - 1; END IF;
END;
$$;
