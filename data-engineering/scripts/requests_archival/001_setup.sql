-- #416: metadata only. This script never alters public.requests.
CREATE SCHEMA IF NOT EXISTS requests_archival;

CREATE TABLE IF NOT EXISTS requests_archival.config (
    job_name text PRIMARY KEY CHECK (job_name = 'requests'),
    bucket text NOT NULL CHECK (length(trim(bucket)) > 0),
    region text NOT NULL CHECK (length(trim(region)) > 0),
    prefix text NOT NULL DEFAULT 'requests' CHECK (length(trim(prefix, '/')) > 0),
    -- Re-read a bounded interval to catch late commits and timestamp ties.
    replay_overlap interval NOT NULL DEFAULT interval '1 day'
        CHECK (replay_overlap >= interval '0'),
    safety_lag interval NOT NULL DEFAULT interval '5 minutes'
        CHECK (safety_lag >= interval '0')
);

CREATE TABLE IF NOT EXISTS requests_archival.watermark (
    job_name text PRIMARY KEY REFERENCES requests_archival.config(job_name),
    completed_through timestamptz NOT NULL DEFAULT '-infinity',
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS requests_archival.runs (
    run_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    finished_at timestamptz,
    status text NOT NULL CHECK (status IN (
        'running', 'success', 'failed', 'interrupted', 'skipped'
    )),
    previous_watermark timestamptz,
    window_start timestamptz,
    window_end timestamptz,
    source_rows bigint,
    uploaded_rows bigint NOT NULL DEFAULT 0,
    uploaded_files bigint NOT NULL DEFAULT 0,
    uploaded_bytes bigint NOT NULL DEFAULT 0,
    -- JSON manifest: exact partition counts, object base keys, and part counts.
    outputs jsonb NOT NULL DEFAULT '[]',
    error_sqlstate text,
    error_message text,
    CHECK (status <> 'success' OR (
        source_rows IS NOT NULL AND source_rows = uploaded_rows
    ))
);

REVOKE ALL ON SCHEMA requests_archival FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA requests_archival FROM PUBLIC;
