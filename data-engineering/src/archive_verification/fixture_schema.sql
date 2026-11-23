-- Local copy of the `requests` table and every table it references (#586).
--
-- Derived from `saayam_schema.sql`, attached to issue #573. That file is the
-- authoritative DDL; this is a local SQLite copy of it, which exists because
-- #586 says the source database is read only and a broken-reference row has to
-- be created somewhere:
--
--   "You cannot insert into the source database, it is read only. So build a
--    local copy of the schema, put a request in it whose category points at
--    nothing, and run the extract against that."
--
-- All nine foreign keys from `requests` are declared here exactly as they are
-- declared upstream, because checks 4 and 5 are entirely about whether the
-- extract honours them with LEFT joins.
--
-- Deviations from the upstream DDL are listed in README.md. The two that matter
-- while reading this file:
--
--   * `req_loc` / `created_loc` are `public.geometry(Point,4326)` upstream and
--     plain TEXT here. SQLite has no PostGIS and no check inspects geometry.
--   * Timestamps are TEXT in canonical `YYYY-MM-DD HH:MM:SS.ffffff` form.
--     Lexical order equals chronological order in that form, so the half-open
--     window comparison behaves as it does against Postgres `timestamp(6)`,
--     microsecond ties included.

CREATE TABLE help_categories (
    cat_id          TEXT PRIMARY KEY,
    cat_name        TEXT NOT NULL,
    cat_desc        TEXT NOT NULL,
    last_updated_at TEXT
);

-- The category tree, parent to child. Upstream DDL warns this is NOT a join
-- table for requests: `requests.req_cat_id` joins straight to
-- `help_categories.cat_id`. Joining through here fans each request out to one
-- row per child category, which is the duplicate-row failure check 2 looks for.
CREATE TABLE help_categories_map (
    parent_id       TEXT REFERENCES help_categories(cat_id),
    child_id        TEXT PRIMARY KEY REFERENCES help_categories(cat_id),
    last_updated_at TEXT
);

CREATE TABLE request_for (
    req_for_id      INTEGER PRIMARY KEY,
    req_for         TEXT NOT NULL,
    req_for_desc    TEXT,
    last_updated_at TEXT
);

CREATE TABLE request_isleadvol (
    req_islead_id   INTEGER PRIMARY KEY,
    req_islead      TEXT NOT NULL,
    req_islead_desc TEXT,
    last_updated_at TEXT
);

CREATE TABLE request_types (
    req_type_id     INTEGER PRIMARY KEY,
    req_type        TEXT,
    req_type_desc   TEXT,
    last_updated_at TEXT
);

CREATE TABLE request_priorities (
    req_priority_id   INTEGER PRIMARY KEY,
    req_priority      TEXT NOT NULL,
    req_priority_desc TEXT,
    last_updated_at   TEXT
);

CREATE TABLE request_statuses (
    req_status_id   INTEGER PRIMARY KEY,
    req_status      TEXT NOT NULL,
    req_status_desc TEXT,
    last_updated_at TEXT
);

-- Key column only, as upstream. The rest of the table holds personal data that
-- this work does not need.
CREATE TABLE users (
    user_id         TEXT PRIMARY KEY,
    last_updated_at TEXT
);

CREATE TABLE requests (
    req_id            TEXT PRIMARY KEY,

    creator_id        TEXT NOT NULL REFERENCES users(user_id),
    beneficiary_id    TEXT REFERENCES users(user_id),
    lead_volunteer_id TEXT REFERENCES users(user_id),

    req_cat_id        TEXT NOT NULL REFERENCES help_categories(cat_id),
    req_for_id        INTEGER NOT NULL REFERENCES request_for(req_for_id),
    req_islead_id     INTEGER NOT NULL REFERENCES request_isleadvol(req_islead_id),
    req_type_id       INTEGER NOT NULL REFERENCES request_types(req_type_id),
    req_priority_id   INTEGER NOT NULL REFERENCES request_priorities(req_priority_id),
    req_status_id     INTEGER NOT NULL REFERENCES request_statuses(req_status_id),

    req_subj          TEXT NOT NULL,
    req_desc          TEXT NOT NULL,
    req_doc_link      TEXT,
    audio_req_desc    TEXT,
    deletion_reason   TEXT,

    req_loc           TEXT,
    created_loc       TEXT,

    iscalamity        INTEGER,
    to_public         INTEGER DEFAULT 0,

    submission_date   TEXT,
    serviced_date     TEXT,
    last_updated_at   TEXT
);

-- `last_updated_at` drives the archival watermark, so the window predicate
-- reads it constantly. Upstream has no index on it either; noted because a
-- missing index is a plausible reason for a slow run once the table is large,
-- and #586 asks for a timing baseline.
CREATE INDEX idx_requests_last_updated_at ON requests(last_updated_at);
