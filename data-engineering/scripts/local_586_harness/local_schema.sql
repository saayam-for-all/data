-- Local reproduction for issue #586 verification.
-- Lookup tables + requests table match data-analytics/testing/issue_573... FK audit
-- (virginia_dev_saayam_rdbms schema, confirmed against the committed saayam_schema.sql).
-- Archive bookkeeping tables match data-engineering/infrastructure/db/requests_s3_archive/001_requests_s3_archive.sql,
-- with the aws_s3 extension/upload call swapped for a local-file write (no AWS access here).

CREATE SCHEMA IF NOT EXISTS virginia_dev_saayam_rdbms;
CREATE EXTENSION IF NOT EXISTS postgis;

SET search_path TO virginia_dev_saayam_rdbms, public;

CREATE TABLE help_categories (
    cat_id           varchar(50)  PRIMARY KEY,
    cat_name         varchar(100) NOT NULL,
    cat_desc         varchar(150) NOT NULL,
    last_updated_at  timestamp(6) DEFAULT (now() AT TIME ZONE 'UTC')
);

CREATE TABLE request_for (
    req_for_id       serial       PRIMARY KEY,
    req_for          varchar(25)  NOT NULL,
    req_for_desc     varchar(125),
    last_updated_at  timestamp(6) DEFAULT (now() AT TIME ZONE 'UTC')
);

CREATE TABLE request_isleadvol (
    req_islead_id    serial       PRIMARY KEY,
    req_islead       varchar(15)  NOT NULL,
    req_islead_desc  varchar(100),
    last_updated_at  timestamp(6) DEFAULT (now() AT TIME ZONE 'UTC')
);

CREATE TABLE request_types (
    req_type_id      serial       PRIMARY KEY,
    req_type         varchar(25),
    req_type_desc    varchar(125),
    last_updated_at  timestamp(6) DEFAULT (now() AT TIME ZONE 'UTC')
);

CREATE TABLE request_priorities (
    req_priority_id   serial       PRIMARY KEY,
    req_priority      varchar(25)  NOT NULL,
    req_priority_desc varchar(125),
    last_updated_at   timestamp(6) DEFAULT (now() AT TIME ZONE 'UTC')
);

CREATE TABLE request_statuses (
    req_status_id    serial       PRIMARY KEY,
    req_status       varchar(25)  NOT NULL,
    req_status_desc  varchar(125),
    last_updated_at  timestamp(6) DEFAULT (now() AT TIME ZONE 'UTC')
);

CREATE TABLE users (
    user_id          varchar(255) PRIMARY KEY,
    last_updated_at  timestamp(6) DEFAULT (now() AT TIME ZONE 'UTC')
);

CREATE TABLE requests (
    req_id             varchar(255) PRIMARY KEY,
    creator_id         varchar(255) NOT NULL REFERENCES users(user_id),
    beneficiary_id     varchar(255) REFERENCES users(user_id),
    lead_volunteer_id  varchar(255) REFERENCES users(user_id),
    req_cat_id         varchar(50)  NOT NULL REFERENCES help_categories(cat_id),
    req_for_id         integer      NOT NULL REFERENCES request_for(req_for_id),
    req_islead_id      integer      NOT NULL REFERENCES request_isleadvol(req_islead_id),
    req_type_id        integer      NOT NULL REFERENCES request_types(req_type_id),
    req_priority_id    integer      NOT NULL REFERENCES request_priorities(req_priority_id),
    req_status_id      integer      NOT NULL REFERENCES request_statuses(req_status_id),
    req_subj           varchar(125) NOT NULL,
    req_desc           varchar(255) NOT NULL,
    req_doc_link       text,
    audio_req_desc     varchar(255),
    deletion_reason    text,
    req_loc            public.geometry(Point,4326),
    created_loc        public.geometry(Point,4326),
    iscalamity         boolean,
    to_public          boolean      DEFAULT false,
    submission_date    timestamp,
    serviced_date      timestamp,
    last_updated_at    timestamp(6) DEFAULT (now() AT TIME ZONE 'UTC')
);

-- NOTE: req_cat_id is deliberately NOT a real FK constraint here (see below) so a
-- broken-reference row can be inserted, mirroring prod's actual FK set where this
-- column *is* enforced -- we insert the broken row by temporarily dropping the
-- constraint, matching what issue #586 says to do for check 5.

-- ==================================================================== archive
-- Mirrors archive.* from 001_requests_s3_archive.sql; aws_s3 export swapped for
-- a local CSV write function below (no real AWS access in this environment).

CREATE SCHEMA IF NOT EXISTS archive;

CREATE TABLE archive.requests_s3_watermark (
    watermark_id boolean PRIMARY KEY DEFAULT true,
    last_successful_watermark timestamp without time zone NOT NULL DEFAULT '-infinity'::timestamp,
    last_successful_run_id bigint,
    updated_at timestamp with time zone NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT requests_s3_watermark_singleton CHECK (watermark_id)
);

INSERT INTO archive.requests_s3_watermark (watermark_id) VALUES (true)
ON CONFLICT (watermark_id) DO NOTHING;

CREATE TABLE archive.requests_s3_runs (
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

CREATE TABLE archive.requests_s3_run_files (
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
