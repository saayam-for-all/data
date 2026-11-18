-- Issue #416: Incremental, database-side archival of public.requests to S3.
--
-- This script intentionally does not create Lambda, Glue, boto3 clients, AWS
-- credentials, or application-side CSV uploads. Exports are performed inside
-- PostgreSQL/RDS with the aws_s3 extension and the IAM role attached to RDS.
--
-- public.requests is treated as read-only. The archive function only SELECTs
-- from public.requests; all archival state is stored in request_archive tables.

CREATE SCHEMA IF NOT EXISTS request_archive;

CREATE TABLE IF NOT EXISTS request_archive.archive_watermarks (
    source_table TEXT PRIMARY KEY,
    last_successful_watermark TIMESTAMPTZ NOT NULL DEFAULT '-infinity'::timestamptz,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (source_table = 'public.requests')
);

CREATE TABLE IF NOT EXISTS request_archive.archive_runs (
    run_id BIGSERIAL PRIMARY KEY,
    source_table TEXT NOT NULL DEFAULT 'public.requests',
    s3_bucket TEXT NOT NULL,
    s3_region TEXT NOT NULL,
    s3_object_key TEXT,
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    source_row_count BIGINT NOT NULL DEFAULT 0,
    exported_row_count BIGINT NOT NULL DEFAULT 0,
    files_uploaded BIGINT NOT NULL DEFAULT 0,
    bytes_uploaded BIGINT NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    failure_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    finished_at TIMESTAMPTZ,
    CHECK (source_table = 'public.requests'),
    CHECK (status IN ('running', 'success', 'failed'))
);

INSERT INTO request_archive.archive_watermarks (source_table)
VALUES ('public.requests')
ON CONFLICT (source_table) DO NOTHING;

CREATE OR REPLACE FUNCTION request_archive.archive_public_requests_to_s3(
    p_s3_bucket TEXT,
    p_s3_region TEXT,
    p_s3_prefix TEXT DEFAULT 'archives/public.requests',
    p_window_end TIMESTAMPTZ DEFAULT clock_timestamp()
)
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    v_run_id BIGINT;
    v_window_start TIMESTAMPTZ;
    v_effective_watermark TIMESTAMPTZ;
    v_max_exported_watermark TIMESTAMPTZ;
    v_source_row_count BIGINT := 0;
    v_exported_row_count BIGINT := 0;
    v_files_uploaded BIGINT := 0;
    v_bytes_uploaded BIGINT := 0;
    v_s3_prefix TEXT := trim(BOTH '/' FROM p_s3_prefix);
    v_s3_object_key TEXT;
    v_export_query TEXT;
    v_export_result RECORD;
BEGIN
    IF p_s3_bucket IS NULL OR btrim(p_s3_bucket) = '' THEN
        RAISE EXCEPTION 'p_s3_bucket is required';
    END IF;

    IF p_s3_region IS NULL OR btrim(p_s3_region) = '' THEN
        RAISE EXCEPTION 'p_s3_region is required';
    END IF;

    IF p_window_end IS NULL THEN
        RAISE EXCEPTION 'p_window_end is required';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtext('request_archive.public.requests'));

    SELECT last_successful_watermark
    INTO v_window_start
    FROM request_archive.archive_watermarks
    WHERE source_table = 'public.requests'
    FOR UPDATE;

    IF NOT FOUND THEN
        INSERT INTO request_archive.archive_watermarks (source_table)
        VALUES ('public.requests')
        RETURNING last_successful_watermark INTO v_window_start;
    END IF;

    IF p_window_end < v_window_start THEN
        RAISE EXCEPTION 'p_window_end (%) cannot be before current watermark (%)',
            p_window_end, v_window_start;
    END IF;

    v_effective_watermark := CASE
        WHEN v_window_start = '-infinity'::timestamptz THEN NULL
        ELSE v_window_start
    END;

    SELECT COUNT(*), MAX(last_updated_at)
    INTO v_source_row_count, v_max_exported_watermark
    FROM public.requests
    WHERE last_updated_at IS NOT NULL
      AND last_updated_at <= p_window_end
      AND (v_effective_watermark IS NULL OR last_updated_at > v_effective_watermark);

    INSERT INTO request_archive.archive_runs (
        s3_bucket,
        s3_region,
        window_start,
        window_end,
        source_row_count,
        status
    )
    VALUES (
        p_s3_bucket,
        p_s3_region,
        v_window_start,
        p_window_end,
        v_source_row_count,
        'running'
    )
    RETURNING run_id INTO v_run_id;

    v_s3_object_key := format(
        '%s/source_schema=public/source_table=requests/year=%s/week=%s/window_start=%s/window_end=%s/run_id=%s/requests.csv',
        v_s3_prefix,
        to_char(p_window_end AT TIME ZONE 'UTC', 'YYYY'),
        to_char(p_window_end AT TIME ZONE 'UTC', 'IW'),
        CASE
            WHEN v_window_start = '-infinity'::timestamptz THEN 'initial'
            ELSE to_char(v_window_start AT TIME ZONE 'UTC', 'YYYYMMDD"T"HH24MISS"Z"')
        END,
        to_char(p_window_end AT TIME ZONE 'UTC', 'YYYYMMDD"T"HH24MISS"Z"'),
        v_run_id
    );

    UPDATE request_archive.archive_runs
    SET s3_object_key = v_s3_object_key
    WHERE run_id = v_run_id;

    BEGIN
        IF v_source_row_count = 0 THEN
            v_exported_row_count := 0;
            v_files_uploaded := 0;
            v_bytes_uploaded := 0;
        ELSE
            v_export_query := format(
                $query$
                SELECT *
                FROM public.requests
                WHERE last_updated_at IS NOT NULL
                  AND last_updated_at <= %L::timestamptz
                  AND (%L::timestamptz IS NULL OR last_updated_at > %L::timestamptz)
                ORDER BY last_updated_at, ctid
                $query$,
                p_window_end,
                v_effective_watermark,
                v_effective_watermark
            );

            SELECT *
            INTO v_export_result
            FROM aws_s3.query_export_to_s3(
                v_export_query,
                aws_commons.create_s3_uri(p_s3_bucket, v_s3_object_key, p_s3_region),
                options := 'format csv, header true'
            );

            v_exported_row_count := COALESCE(v_export_result.rows_uploaded, 0);
            v_files_uploaded := COALESCE(v_export_result.files_uploaded, 0);
            v_bytes_uploaded := COALESCE(v_export_result.bytes_uploaded, 0);
        END IF;

        IF v_source_row_count = v_exported_row_count THEN
            UPDATE request_archive.archive_runs
            SET exported_row_count = v_exported_row_count,
                files_uploaded = v_files_uploaded,
                bytes_uploaded = v_bytes_uploaded,
                status = 'success',
                finished_at = clock_timestamp()
            WHERE run_id = v_run_id;

            IF v_max_exported_watermark IS NOT NULL THEN
                UPDATE request_archive.archive_watermarks
                SET last_successful_watermark = v_max_exported_watermark,
                    updated_at = clock_timestamp()
                WHERE source_table = 'public.requests';
            END IF;
        ELSE
            UPDATE request_archive.archive_runs
            SET exported_row_count = v_exported_row_count,
                files_uploaded = v_files_uploaded,
                bytes_uploaded = v_bytes_uploaded,
                status = 'failed',
                failure_message = format(
                    'Exported row count mismatch: source_row_count=%s, exported_row_count=%s',
                    v_source_row_count,
                    v_exported_row_count
                ),
                finished_at = clock_timestamp()
            WHERE run_id = v_run_id;
        END IF;
    EXCEPTION WHEN OTHERS THEN
        UPDATE request_archive.archive_runs
        SET exported_row_count = COALESCE(v_exported_row_count, 0),
            files_uploaded = COALESCE(v_files_uploaded, 0),
            bytes_uploaded = COALESCE(v_bytes_uploaded, 0),
            status = 'failed',
            failure_message = left(SQLERRM, 2000),
            finished_at = clock_timestamp()
        WHERE run_id = v_run_id;
    END;

    RETURN v_run_id;
END;
$$;
