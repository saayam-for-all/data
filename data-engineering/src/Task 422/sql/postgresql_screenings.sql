-- Review-only migration template. Not executed by the application.
-- Replace YOUR_APPROVED_SCHEMA after confirming the database target.
-- request and fraud_requests must already exist with the repository columns.
CREATE TABLE YOUR_APPROVED_SCHEMA.profanity_screenings (
    request_id VARCHAR(255) PRIMARY KEY,
    fingerprint VARCHAR(64) NOT NULL,
    severity_score INTEGER NOT NULL CHECK (severity_score BETWEEN 0 AND 3),
    destination VARCHAR(30) NOT NULL,
    payload JSON NOT NULL,
    receipt JSON NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
);
