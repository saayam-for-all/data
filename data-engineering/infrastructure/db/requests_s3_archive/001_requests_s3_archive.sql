-- Issue #416: Incremental archival of public.requests to S3.
--
-- This migration creates only archive metadata objects and an export function.
-- The archival job reads public.requests with SELECT statements only.

CREATE SCHEMA IF NOT EXISTS archive;

CREATE EXTENSION IF NOT EXISTS aws_s3 CASCADE;

CREATE TABLE IF NOT EXISTS archive.requests_s3_watermark (
    watermark_id boolean PRIMARY KEY DEFAULT true,
    last_successful_watermark timestamp without time zone NOT NULL DEFAULT '-infinity'::timestamp,
    last_successful_run_id bigint,
    updated_at timestamp with time zone NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT requests_s3_watermark_singleton CHECK (watermark_id)
);

INSERT INTO archive.requests_s3_watermark (watermark_id)
VALUES (true)
ON CONFLICT (watermark_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS archive.requests_s3_runs (
    run_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at timestamp with time zone NOT NULL DEFAULT clock_timestamp(),
    finished_at timestamp with time zone,
    status text NOT NULL CHECK (status IN ('running', 'success', 'failed', 'skipped')),
    watermark_start timestamp without time zone NOT NULL,
    watermark_end timestamp without time zone NOT NULL,
    s3_bucket text NOT NULL,
    s3_region text NOT NULL,
    s3_prefix text NOT NULL,
    source_row_count bigint NOT NULL DEFAULT 0,
    uploaded_row_count bigint NOT NULL DEFAULT 0,
    uploaded_file_count bigint NOT NULL DEFAULT 0,
    uploaded_bytes bigint NOT NULL DEFAULT 0,
    error_message text,
    CHECK (watermark_end >= watermark_start)
);

CREATE INDEX IF NOT EXISTS idx_requests_s3_runs_started_at
    ON archive.requests_s3_runs (started_at DESC);

CREATE TABLE IF NOT EXISTS archive.requests_s3_run_files (
    run_file_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id bigint NOT NULL REFERENCES archive.requests_s3_runs (run_id),
    partition_date date NOT NULL,
    s3_key text NOT NULL,
    source_row_count bigint NOT NULL,
    uploaded_row_count bigint NOT NULL DEFAULT 0,
    uploaded_file_count bigint NOT NULL DEFAULT 0,
    uploaded_bytes bigint NOT NULL DEFAULT 0,
    created_at timestamp with time zone NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS archive.requests_s3_config (
    config_id boolean PRIMARY KEY DEFAULT true,
    s3_bucket text NOT NULL,
    s3_region text NOT NULL,
    s3_prefix text NOT NULL DEFAULT 'requests',
    kms_key_id text,
    enabled boolean NOT NULL DEFAULT true,
    updated_at timestamp with time zone NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT requests_s3_config_singleton CHECK (config_id),
    CONSTRAINT requests_s3_bucket_not_placeholder CHECK (s3_bucket <> '<replace-with-request-archive-bucket>'),
    CONSTRAINT requests_s3_region_not_placeholder CHECK (s3_region <> '<replace-with-aws-region>')
);

CREATE OR REPLACE FUNCTION archive.export_requests_to_s3(
    p_s3_bucket text,
    p_s3_region text,
    p_s3_prefix text DEFAULT 'requests',
    p_kms_key_id text DEFAULT NULL,
    p_watermark_end timestamp without time zone DEFAULT (clock_timestamp() AT TIME ZONE 'UTC')
)
RETURNS SETOF archive.requests_s3_runs
LANGUAGE plpgsql
AS $$
DECLARE
    v_run_id bigint;
    v_watermark_start timestamp without time zone;
    v_watermark_end timestamp without time zone := p_watermark_end;
    v_partition_start timestamp without time zone;
    v_partition_end timestamp without time zone;
    v_partition_date date;
    v_first_updated_at timestamp without time zone;
    v_last_updated_at timestamp without time zone;
    v_s3_key text;
    v_export_query text;
    v_copy_options text := 'FORMAT CSV, HEADER TRUE, ENCODING ''UTF8''';
    v_source_rows bigint := 0;
    v_partition_rows bigint := 0;
    v_rows_uploaded bigint := 0;
    v_files_uploaded bigint := 0;
    v_bytes_uploaded bigint := 0;
    v_total_rows_uploaded bigint := 0;
    v_total_files_uploaded bigint := 0;
    v_total_bytes_uploaded bigint := 0;
BEGIN
    IF p_s3_bucket IS NULL OR btrim(p_s3_bucket) = '' THEN
        RAISE EXCEPTION 'p_s3_bucket is required';
    END IF;

    IF p_s3_region IS NULL OR btrim(p_s3_region) = '' THEN
        RAISE EXCEPTION 'p_s3_region is required';
    END IF;

    IF NOT pg_try_advisory_xact_lock(hashtext('archive.export_requests_to_s3')) THEN
        SELECT last_successful_watermark
        INTO v_watermark_start
        FROM archive.requests_s3_watermark
        WHERE watermark_id = true;

        INSERT INTO archive.requests_s3_runs (
            status,
            watermark_start,
            watermark_end,
            s3_bucket,
            s3_region,
            s3_prefix,
            error_message,
            finished_at
        )
        VALUES (
            'skipped',
            v_watermark_start,
            v_watermark_end,
            p_s3_bucket,
            p_s3_region,
            p_s3_prefix,
            'Another requests S3 archive run is already active.',
            clock_timestamp()
        )
        RETURNING run_id INTO v_run_id;

        RETURN QUERY
            SELECT *
            FROM archive.requests_s3_runs
            WHERE run_id = v_run_id;
        RETURN;
    END IF;

    SELECT last_successful_watermark
    INTO v_watermark_start
    FROM archive.requests_s3_watermark
    WHERE watermark_id = true
    FOR UPDATE;

    IF v_watermark_end <= v_watermark_start THEN
        RAISE EXCEPTION 'watermark_end (%) must be greater than current watermark (%)',
            v_watermark_end,
            v_watermark_start;
    END IF;

    INSERT INTO archive.requests_s3_runs (
        status,
        watermark_start,
        watermark_end,
        s3_bucket,
        s3_region,
        s3_prefix
    )
    VALUES (
        'running',
        v_watermark_start,
        v_watermark_end,
        p_s3_bucket,
        p_s3_region,
        COALESCE(NULLIF(btrim(p_s3_prefix), ''), 'requests')
    )
    RETURNING run_id INTO v_run_id;

    BEGIN
        SELECT count(*), min(last_updated_at), max(last_updated_at)
        INTO v_source_rows, v_first_updated_at, v_last_updated_at
        FROM public.requests
        WHERE last_updated_at > v_watermark_start
          AND last_updated_at <= v_watermark_end;

        IF v_source_rows > 0 THEN
            FOR v_partition_start IN
                SELECT generate_series(
                    date_trunc('day', v_first_updated_at),
                    date_trunc('day', v_last_updated_at),
                    interval '1 day'
                )::timestamp without time zone
            LOOP
                v_partition_end := v_partition_start + interval '1 day';
                v_partition_date := v_partition_start::date;

                SELECT count(*)
                INTO v_partition_rows
                FROM public.requests
                WHERE last_updated_at > v_watermark_start
                  AND last_updated_at <= v_watermark_end
                  AND last_updated_at >= v_partition_start
                  AND last_updated_at < v_partition_end;

                IF v_partition_rows = 0 THEN
                    CONTINUE;
                END IF;

                v_s3_key := concat_ws(
                    '/',
                    trim(both '/' FROM COALESCE(NULLIF(btrim(p_s3_prefix), ''), 'requests')),
                    'last_updated_year=' || to_char(v_partition_date, 'YYYY'),
                    'last_updated_month=' || to_char(v_partition_date, 'MM'),
                    'last_updated_day=' || to_char(v_partition_date, 'DD'),
                    'run_id=' || v_run_id,
                    'requests.csv'
                );

                v_export_query := format(
                    $export_query$
                    SELECT *
                    FROM public.requests
                    WHERE last_updated_at > %L::timestamp
                      AND last_updated_at <= %L::timestamp
                      AND last_updated_at >= %L::timestamp
                      AND last_updated_at < %L::timestamp
                    ORDER BY last_updated_at, req_id
                    $export_query$,
                    v_watermark_start,
                    v_watermark_end,
                    v_partition_start,
                    v_partition_end
                );

                SELECT rows_uploaded, files_uploaded, bytes_uploaded
                INTO v_rows_uploaded, v_files_uploaded, v_bytes_uploaded
                FROM aws_s3.query_export_to_s3(
                    v_export_query,
                    aws_commons.create_s3_uri(p_s3_bucket, v_s3_key, p_s3_region),
                    v_copy_options,
                    p_kms_key_id
                );

                INSERT INTO archive.requests_s3_run_files (
                    run_id,
                    partition_date,
                    s3_key,
                    source_row_count,
                    uploaded_row_count,
                    uploaded_file_count,
                    uploaded_bytes
                )
                VALUES (
                    v_run_id,
                    v_partition_date,
                    v_s3_key,
                    v_partition_rows,
                    v_rows_uploaded,
                    v_files_uploaded,
                    v_bytes_uploaded
                );

                v_total_rows_uploaded := v_total_rows_uploaded + COALESCE(v_rows_uploaded, 0);
                v_total_files_uploaded := v_total_files_uploaded + COALESCE(v_files_uploaded, 0);
                v_total_bytes_uploaded := v_total_bytes_uploaded + COALESCE(v_bytes_uploaded, 0);
            END LOOP;
        END IF;

        IF v_source_rows <> v_total_rows_uploaded THEN
            RAISE EXCEPTION 'requests S3 archive count mismatch: source %, uploaded %',
                v_source_rows,
                v_total_rows_uploaded;
        END IF;

        UPDATE archive.requests_s3_watermark
        SET last_successful_watermark = v_watermark_end,
            last_successful_run_id = v_run_id,
            updated_at = clock_timestamp()
        WHERE watermark_id = true;

        UPDATE archive.requests_s3_runs
        SET status = 'success',
            finished_at = clock_timestamp(),
            source_row_count = v_source_rows,
            uploaded_row_count = v_total_rows_uploaded,
            uploaded_file_count = v_total_files_uploaded,
            uploaded_bytes = v_total_bytes_uploaded
        WHERE run_id = v_run_id;
    EXCEPTION WHEN OTHERS THEN
        UPDATE archive.requests_s3_runs
        SET status = 'failed',
            finished_at = clock_timestamp(),
            source_row_count = v_source_rows,
            uploaded_row_count = v_total_rows_uploaded,
            uploaded_file_count = v_total_files_uploaded,
            uploaded_bytes = v_total_bytes_uploaded,
            error_message = SQLERRM
        WHERE run_id = v_run_id;
    END;

    RETURN QUERY
        SELECT *
        FROM archive.requests_s3_runs
        WHERE run_id = v_run_id;
END;
$$;

CREATE OR REPLACE FUNCTION archive.export_requests_to_s3_from_config()
RETURNS SETOF archive.requests_s3_runs
LANGUAGE plpgsql
AS $$
DECLARE
    v_config archive.requests_s3_config%ROWTYPE;
BEGIN
    SELECT *
    INTO v_config
    FROM archive.requests_s3_config
    WHERE config_id = true;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'archive.requests_s3_config is not configured';
    END IF;

    IF NOT v_config.enabled THEN
        RAISE EXCEPTION 'archive.requests_s3_config is disabled';
    END IF;

    RETURN QUERY
        SELECT *
        FROM archive.export_requests_to_s3(
            v_config.s3_bucket,
            v_config.s3_region,
            v_config.s3_prefix,
            v_config.kms_key_id
        );
END;
$$;
