-- Invoke with a top-level CALL in autocommit mode, not inside BEGIN/COMMIT.
-- Internal commits persist the start/failure log even when an export fails.
CREATE OR REPLACE PROCEDURE requests_archival.archive_requests()
LANGUAGE plpgsql
SECURITY INVOKER
AS $procedure$
DECLARE
    settings requests_archival.config%ROWTYPE;
    attempt bigint;
    previous timestamptz;
    lower_bound timestamptz;
    upper_bound timestamptz;
    partition record;
    exported record;
    expected bigint := 0;
    total_rows bigint := 0;
    total_files bigint := 0;
    total_bytes bigint := 0;
    manifest jsonb := '[]';
    object_key text;
    export_query text;
    failure_code text;
    failure_message text;
BEGIN
    -- Session lock spans the commits below. Use a dedicated job connection.
    IF NOT pg_try_advisory_lock(416, 1) THEN
        INSERT INTO requests_archival.runs(status, finished_at, error_message)
        VALUES ('skipped', clock_timestamp(), 'Another archival run is active');
        COMMIT;
        RETURN;
    END IF;

    BEGIN
        -- A prior terminated session released its lock but left a durable log.
        UPDATE requests_archival.runs
        SET status = 'interrupted', finished_at = clock_timestamp(),
            error_message = 'Previous worker ended before recording completion'
        WHERE status = 'running';
        INSERT INTO requests_archival.runs(status) VALUES ('running')
        RETURNING run_id INTO attempt;
    EXCEPTION WHEN OTHERS THEN
        PERFORM pg_advisory_unlock(416, 1);
        RAISE;
    END;
    COMMIT;

    BEGIN
        PERFORM set_config('TimeZone', 'UTC', true);
        SELECT * INTO STRICT settings FROM requests_archival.config
        WHERE job_name = 'requests';
        INSERT INTO requests_archival.watermark(job_name) VALUES ('requests')
        ON CONFLICT (job_name) DO NOTHING;
        SELECT completed_through INTO STRICT previous
        FROM requests_archival.watermark WHERE job_name = 'requests';
        upper_bound := clock_timestamp() - settings.safety_lag;
        IF upper_bound < previous THEN
            RAISE EXCEPTION 'Cutoff precedes the successful watermark';
        END IF;
        lower_bound := previous - settings.replay_overlap;

        -- NULL update times cannot participate in an incremental export.
        IF EXISTS (SELECT 1 FROM public.requests
                   WHERE last_updated_at IS NULL) THEN
            RAISE EXCEPTION 'Source contains NULL last_updated_at values';
        END IF;

        -- One SELECT snapshot: live changes cannot invalidate reconciliation.
        -- Only the temporary copy is read by the exporter; requests is read-only.
        CREATE TEMP TABLE requests_archive_batch ON COMMIT DROP AS
        SELECT * FROM public.requests
        WHERE last_updated_at >= lower_bound AND last_updated_at <= upper_bound;
        SELECT count(*) INTO expected FROM pg_temp.requests_archive_batch;

        FOR partition IN
            SELECT date_trunc('month', last_updated_at) AS month_start,
                   count(*) AS row_count
            FROM pg_temp.requests_archive_batch
            GROUP BY 1 ORDER BY 1
        LOOP
            object_key := format(
                '%s/year=%s/month=%s/run_id=%s/requests.csv',
                trim(settings.prefix, '/'),
                to_char(partition.month_start, 'YYYY'),
                to_char(partition.month_start, 'MM'), attempt
            );
            export_query := format(
                'SELECT * FROM pg_temp.requests_archive_batch '
                'WHERE last_updated_at >= %L::timestamptz '
                'AND last_updated_at < %L::timestamptz',
                partition.month_start,
                partition.month_start + interval '1 month'
            );
            SELECT * INTO STRICT exported FROM aws_s3.query_export_to_s3(
                export_query, settings.bucket, object_key, settings.region,
                options := 'format csv, header true, encoding ''UTF8'''
            );
            IF exported.rows_uploaded IS NULL
               OR exported.files_uploaded IS NULL
               OR exported.bytes_uploaded IS NULL THEN
                RAISE EXCEPTION 'Exporter returned incomplete statistics';
            END IF;
            total_rows := total_rows + exported.rows_uploaded;
            total_files := total_files + exported.files_uploaded;
            total_bytes := total_bytes + exported.bytes_uploaded;
            manifest := manifest || jsonb_build_array(jsonb_build_object(
                'bucket', settings.bucket, 'region', settings.region,
                'key', object_key, 'source_rows', partition.row_count,
                'uploaded_rows', exported.rows_uploaded,
                'files', exported.files_uploaded,
                'bytes', exported.bytes_uploaded
            ));
            IF exported.rows_uploaded <> partition.row_count THEN
                RAISE EXCEPTION 'Partition count mismatch: expected %, uploaded %',
                    partition.row_count, exported.rows_uploaded;
            END IF;
        END LOOP;

        IF expected <> total_rows THEN
            RAISE EXCEPTION 'Run count mismatch: expected %, uploaded %',
                expected, total_rows;
        END IF;
        UPDATE requests_archival.watermark
        SET completed_through = upper_bound, updated_at = clock_timestamp()
        WHERE job_name = 'requests';
    EXCEPTION
        -- Export effects on S3 are not rolled back. Failed run IDs are excluded
        -- by consumers; a retry uses a new ID and the old successful watermark.
        WHEN query_canceled OR OTHERS THEN
            GET STACKED DIAGNOSTICS failure_code = RETURNED_SQLSTATE,
                                    failure_message = MESSAGE_TEXT;
    END;

    BEGIN
        UPDATE requests_archival.runs
        SET finished_at = clock_timestamp(),
            status = CASE WHEN failure_code IS NULL THEN 'success' ELSE 'failed' END,
            previous_watermark = previous, window_start = lower_bound,
            window_end = upper_bound, source_rows = expected,
            uploaded_rows = total_rows, uploaded_files = total_files,
            uploaded_bytes = total_bytes, outputs = manifest,
            error_sqlstate = failure_code, error_message = failure_message
        WHERE run_id = attempt;
    EXCEPTION WHEN OTHERS THEN
        PERFORM pg_advisory_unlock(416, 1);
        RAISE;
    END;
    COMMIT;
    PERFORM pg_advisory_unlock(416, 1);
    IF failure_code IS NOT NULL THEN
        -- Raising after writing the failure log would confuse callers about
        -- rollback. The runs table, not CALL's exit status, is authoritative.
        RAISE WARNING 'Archival run % failed [%]: %',
            attempt, failure_code, failure_message;
    END IF;
END;
$procedure$;

REVOKE EXECUTE ON PROCEDURE requests_archival.archive_requests() FROM PUBLIC;
