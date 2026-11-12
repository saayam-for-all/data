-- Unschedule the requests archival job without dropping archive metadata.

SELECT cron.unschedule(jobid)
FROM cron.job
WHERE jobname = 'requests-s3-archive-weekly';
