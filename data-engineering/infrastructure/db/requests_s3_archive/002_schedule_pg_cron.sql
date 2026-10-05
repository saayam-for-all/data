-- Issue #416: Schedule the requests S3 archive job.
--
-- Prerequisites:
-- 1. Add pg_cron to shared_preload_libraries and restart the DB instance.
-- 2. Attach an IAM role with S3 write permission to the RDS/Aurora instance.
-- 3. Run 001_requests_s3_archive.sql in the Saayam application database.
--
-- Replace the bucket and region placeholders before running this file.

CREATE EXTENSION IF NOT EXISTS pg_cron;

INSERT INTO archive.requests_s3_config (
    config_id,
    s3_bucket,
    s3_region,
    s3_prefix,
    kms_key_id,
    enabled
)
VALUES (
    true,
    '<replace-with-request-archive-bucket>',
    '<replace-with-aws-region>',
    'requests',
    NULL,
    true
)
ON CONFLICT (config_id) DO UPDATE
SET s3_bucket = EXCLUDED.s3_bucket,
    s3_region = EXCLUDED.s3_region,
    s3_prefix = EXCLUDED.s3_prefix,
    kms_key_id = EXCLUDED.kms_key_id,
    enabled = EXCLUDED.enabled,
    updated_at = clock_timestamp();

SELECT cron.schedule(
    'requests-s3-archive-weekly',
    '0 6 * * 0',
    $$SELECT archive.export_requests_to_s3_from_config();$$
)
WHERE NOT EXISTS (
    SELECT 1
    FROM cron.job
    WHERE jobname = 'requests-s3-archive-weekly'
);
