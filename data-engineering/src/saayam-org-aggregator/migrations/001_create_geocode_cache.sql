-- Coordinate cache for saayam-org-aggregator distance calculation.
-- Keyed by a SHA-256 of the normalized address, so it works for DB orgs,
-- GenAI orgs and beneficiary profile addresses alike, and an edited address
-- simply produces a new key (no stale coordinates).
--
-- Only 'ok' and 'not_found' results are stored; transient failures
-- ('deferred', 'error') are retried on the next page load. The Lambda keeps
-- working (memory-only cache) if this table does not exist yet.
--
-- The Lambda's DB user needs SELECT, INSERT, UPDATE on this table.

CREATE TABLE IF NOT EXISTS virginia_dev_saayam_rdbms.geocode_cache (
    address_key         CHAR(64)          PRIMARY KEY,
    normalized_address  TEXT              NOT NULL,
    latitude            DOUBLE PRECISION,
    longitude           DOUBLE PRECISION,
    status              VARCHAR(20)       NOT NULL,
    provider            VARCHAR(50),
    created_at          TIMESTAMPTZ       NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ       NOT NULL DEFAULT now(),
    CONSTRAINT geocode_cache_status_chk
        CHECK (status IN ('ok', 'not_found')),
    CONSTRAINT geocode_cache_coords_chk
        CHECK (
            status <> 'ok'
            OR (latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180)
        )
);
