-- Local dev table for help request screening (issue #422).
--
-- Help requests held back from active matching (severity score 1-3, or no
-- score because the Profanity API was unavailable) are saved here by
-- src/help_request_screening. ASSUMED: this table does not exist in the live
-- virginia_dev_saayam_rdbms schema yet -- confirm the name and columns with
-- the database team before deploying.

CREATE SCHEMA IF NOT EXISTS virginia_dev_saayam_rdbms;

CREATE TABLE IF NOT EXISTS virginia_dev_saayam_rdbms.flagged_help_requests (
    req_id VARCHAR(255) PRIMARY KEY,   -- request.req_id
    severity_score SMALLINT CHECK (severity_score BETWEEN 1 AND 3),  -- NULL = unscored
    severity_label VARCHAR(64) NOT NULL,
    route VARCHAR(32) NOT NULL,        -- hold_for_review | support_follow_up
    flagged_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
