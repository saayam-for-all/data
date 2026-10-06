-- Weekly schedule via pg_cron. Apply only after a manual
-- CALL request_archive.run(); has been checked against real S3 output.
-- pg_cron on RDS lives in the default database, so name the target database:
--   psql -v target_database=saayam -v cron_expression='0 2 * * 0' -f 003_schedule.sql
\set ON_ERROR_STOP on
\if :{?target_database}
\else
    \echo 'Supply -v target_database=<database that holds request_archive>'
    \quit 1
\endif
\if :{?cron_expression}
\else
    \set cron_expression '0 2 * * 0'
\endif

-- A fixed job name makes re-running this script update the job, not duplicate it.
SELECT cron.schedule_in_database(
    'request-archive-weekly', :'cron_expression',
    'CALL request_archive.run()', :'target_database'
);
