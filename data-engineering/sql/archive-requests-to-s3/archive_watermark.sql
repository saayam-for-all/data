-- Issue #416
-- Stores the last successfully archived request watermark.

CREATE TABLE IF NOT EXISTS virginia_dev_saayam_rdbms.request_archive_watermark (
    archive_name VARCHAR(100) PRIMARY KEY,
    last_successful_watermark TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Initialize the watermark for the request archive.
-- ON CONFLICT prevents an existing watermark from being overwritten.

INSERT INTO virginia_dev_saayam_rdbms.request_archive_watermark (
    archive_name,
    last_successful_watermark
)
VALUES (
    'request_archive_to_s3',
    TIMESTAMP '1970-01-01 00:00:00'
)
ON CONFLICT (archive_name) DO NOTHING;