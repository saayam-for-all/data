-- #416: copy changed rows of public.requests to S3 as monthly CSV partitions.
-- Invoke as a top-level CALL in autocommit mode, never inside BEGIN/COMMIT:
-- the procedure commits its run log so a failure is still recorded.
-- The only statements that touch public.requests are SELECTs.
CREATE OR REPLACE PROCEDURE request_archive.run()
LANGUAGE plpgsql
SECURITY INVOKER
AS $procedure$
DECLARE
    settings request_archive.config%ROWTYPE;
    this_run bigint;
    previous timestamptz;
    window_lo timestamptz;
    window_hi timestamptz;
    part record;
    sent record;
    object_key text;
    export_query text;
    expected bigint := 0;
    total_rows bigint := 0;
    total_files bigint := 0;
    total_bytes bigint := 0;
    manifest jsonb := '[]';
    failure_code text;
    failure_message text;
BEGIN
    -- Session-level lock: it spans the COMMITs below, so run each job on its
    -- own connection. A second overlapping run logs 'skipped' and leaves.
    IF NOT pg_try_advisory_lock(416, 1) THEN
        INSERT INTO request_archive.run_log(status, finished_at, error_message)
        VALUES ('skipped', clock_timestamp(), 'Another archive run is active');
        COMMIT;
        RETURN;
    END IF;

    BEGIN
        -- A 'running' row that survives to here belongs to a dead session.
        UPDATE request_archive.run_log
        SET status = 'interrupted', finished_at = clock_timestamp(),
            error_message = 'Worker ended before recording completion'
        WHERE status = 'running';
        INSERT INTO request_archive.run_log(status) VALUES ('running')
        RETURNING run_id INTO this_run;
    EXCEPTION WHEN OTHERS THEN
        PERFORM pg_advisory_unlock(416, 1);
        RAISE;
    END;
    COMMIT;

    -- Everything below reads one snapshot, so a request edited while the
    -- export is running cannot make the source count disagree with the upload.
    -- Must be the first statement after COMMIT and outside the EXCEPTION block.
    SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;

    BEGIN
        SELECT * INTO STRICT settings FROM request_archive.config
        WHERE job_name = 'requests';
        INSERT INTO request_archive.watermark(job_name) VALUES ('requests')
        ON CONFLICT (job_name) DO NOTHING;
        SELECT archived_through INTO STRICT previous
        FROM request_archive.watermark WHERE job_name = 'requests';

        window_hi := clock_timestamp() - settings.safety_lag;
        IF window_hi < previous THEN
            RAISE EXCEPTION 'Window end % precedes the watermark %',
                window_hi, previous;
        END IF;
        window_lo := previous - settings.replay_overlap;

        -- A NULL last_updated_at can never match the window, so those rows
        -- would be silently skipped forever. Fail loudly instead.
        IF EXISTS (SELECT 1 FROM public.requests
                   WHERE last_updated_at IS NULL) THEN
            RAISE EXCEPTION 'public.requests has NULL last_updated_at values';
        END IF;

        FOR part IN
            SELECT date_trunc('month', last_updated_at AT TIME ZONE 'UTC')
                       AS month_start,
                   count(*) AS row_count
            FROM public.requests
            WHERE last_updated_at >= window_lo AND last_updated_at <= window_hi
            GROUP BY 1 ORDER BY 1
        LOOP
            expected := expected + part.row_count;
            object_key := format(
                '%s/year=%s/month=%s/run_id=%s/requests.csv',
                trim(settings.prefix, '/'),
                to_char(part.month_start, 'YYYY'),
                to_char(part.month_start, 'MM'), this_run
            );
            export_query := format(
                'SELECT * FROM public.requests '
                'WHERE last_updated_at >= %L::timestamptz '
                'AND last_updated_at <= %L::timestamptz '
                'AND last_updated_at >= (%L::timestamp AT TIME ZONE ''UTC'') '
                'AND last_updated_at < (%L::timestamp + interval ''1 month'') '
                    'AT TIME ZONE ''UTC''',
                window_lo, window_hi, part.month_start, part.month_start
            );
            SELECT * INTO STRICT sent FROM aws_s3.query_export_to_s3(
                export_query, settings.bucket, object_key, settings.region,
                options := 'format csv, header true, encoding ''UTF8'''
            );
            IF sent.rows_uploaded IS NULL OR sent.files_uploaded IS NULL
               OR sent.bytes_uploaded IS NULL THEN
                RAISE EXCEPTION 'Export returned incomplete statistics';
            END IF;
            total_rows := total_rows + sent.rows_uploaded;
            total_files := total_files + sent.files_uploaded;
            total_bytes := total_bytes + sent.bytes_uploaded;
            manifest := manifest || jsonb_build_array(jsonb_build_object(
                'bucket', settings.bucket, 'key', object_key,
                'source_rows', part.row_count,
                'uploaded_rows', sent.rows_uploaded,
                'files', sent.files_uploaded, 'bytes', sent.bytes_uploaded
            ));
            IF sent.rows_uploaded <> part.row_count THEN
                RAISE EXCEPTION 'Partition % mismatch: source %, uploaded %',
                    object_key, part.row_count, sent.rows_uploaded;
            END IF;
        END LOOP;

        IF expected <> total_rows THEN
            RAISE EXCEPTION 'Run mismatch: source %, uploaded %',
                expected, total_rows;
        END IF;
    EXCEPTION
        -- S3 writes are not rolled back. Files from a failed run stay in the
        -- bucket; readers use only run_ids whose run_log status is 'success'.
        WHEN query_canceled OR OTHERS THEN
            GET STACKED DIAGNOSTICS failure_code = RETURNED_SQLSTATE,
                                    failure_message = MESSAGE_TEXT;
    END;

    -- End the snapshot transaction, then write the outcome and (on success
    -- only) move the watermark together in a new transaction.
    COMMIT;

    BEGIN
        IF failure_code IS NULL THEN
            UPDATE request_archive.watermark
            SET archived_through = window_hi, updated_at = clock_timestamp()
            WHERE job_name = 'requests';
        END IF;
        UPDATE request_archive.run_log
        SET finished_at = clock_timestamp(),
            status = CASE WHEN failure_code IS NULL THEN 'success'
                          ELSE 'failed' END,
            window_start = window_lo, window_end = window_hi,
            source_rows = expected, uploaded_rows = total_rows,
            uploaded_files = total_files, uploaded_bytes = total_bytes,
            outputs = manifest,
            error_sqlstate = failure_code, error_message = failure_message
        WHERE run_id = this_run;
    EXCEPTION WHEN OTHERS THEN
        PERFORM pg_advisory_unlock(416, 1);
        RAISE;
    END;
    COMMIT;
    PERFORM pg_advisory_unlock(416, 1);

    -- The log is already committed, so raising now cannot lose it. It lets
    -- pg_cron (cron.job_run_details) and any caller see the run failed.
    IF failure_code IS NOT NULL THEN
        RAISE EXCEPTION 'Request archive run % failed [%]: %',
            this_run, failure_code, failure_message;
    END IF;
END;
$procedure$;

REVOKE EXECUTE ON PROCEDURE request_archive.run() FROM PUBLIC;
