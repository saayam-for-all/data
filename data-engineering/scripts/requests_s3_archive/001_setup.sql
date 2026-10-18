-- #416: metadata for the requests -> S3 archive job.
-- Creates only the request_archive schema. public.requests is never altered.
CREATE SCHEMA IF NOT EXISTS request_archive;

-- One row of settings. Fill in bucket and region after applying this script.
CREATE TABLE IF NOT EXISTS request_archive.config (
    job_name text PRIMARY KEY DEFAULT 'requests' CHECK (job_name = 'requests'),
    bucket text NOT NULL CHECK (length(trim(bucket)) > 0),
    region text NOT NULL CHECK (length(trim(region)) > 0),
    prefix text NOT NULL DEFAULT 'requests' CHECK (length(trim(prefix, '/')) > 0),
    -- Re-read this much history before the watermark so rows that committed
    -- late, or share the watermark's timestamp, are not missed.
    replay_overlap interval NOT NULL DEFAULT interval '1 day'
        CHECK (replay_overlap >= interval '0'),
    -- Stop the window slightly in the past so in-flight transactions settle.
    safety_lag interval NOT NULL DEFAULT interval '5 minutes'
        CHECK (safety_lag >= interval '0')
);

-- How far the archive has got. Moves only after a fully reconciled run.
CREATE TABLE IF NOT EXISTS request_archive.watermark (
    job_name text PRIMARY KEY REFERENCES request_archive.config(job_name),
    archived_through timestamptz NOT NULL DEFAULT '-infinity',
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- One row per run, written before the export starts so crashes leave a trace.
CREATE TABLE IF NOT EXISTS request_archive.run_log (
    run_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    finished_at timestamptz,
    status text NOT NULL CHECK (status IN (
        'running', 'success', 'failed', 'interrupted', 'skipped'
    )),
    window_start timestamptz,
    window_end timestamptz,
    source_rows bigint,
    uploaded_rows bigint NOT NULL DEFAULT 0,
    uploaded_files bigint NOT NULL DEFAULT 0,
    uploaded_bytes bigint NOT NULL DEFAULT 0,
    -- One entry per exported partition: S3 key, source rows, uploaded rows.
    outputs jsonb NOT NULL DEFAULT '[]',
    error_sqlstate text,
    error_message text,
    -- A run is only a success when source and uploaded counts agree.
    CHECK (status <> 'success'
           OR (source_rows IS NOT NULL AND source_rows = uploaded_rows))
);

REVOKE ALL ON SCHEMA request_archive FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA request_archive FROM PUBLIC;
