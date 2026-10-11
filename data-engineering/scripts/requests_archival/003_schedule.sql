-- Run only on the target AWS database after configuration and a manual export
-- have been verified. Requires pg_cron installed by the database administrator.
-- psql -v target_database=saayam -v cron_expression='0 2 * * 0' -f 003_schedule.sql
\set ON_ERROR_STOP on
\if :{?target_database}
\else
    \echo 'Supply -v target_database=<database containing the archival procedure>'
    \quit 1
\endif
\if :{?cron_expression}
\else
    \set cron_expression '0 2 * * 0'
\endif

-- Run in the database holding the cron extension. A stable job name lets
-- repeated application update the schedule instead of creating duplicate jobs.
SELECT cron.schedule_in_database(
    'requests-archive-weekly', :'cron_expression',
    'CALL requests_archival.archive_requests()', :'target_database'
);
