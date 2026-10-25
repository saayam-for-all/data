"""Integration tests for the requests -> S3 archive procedure (#416).

They run the real SQL against a disposable local PostgreSQL database and
replace only the aws_s3 extension with tests/mock_aws_s3.sql.

    ARCHIVAL_TEST_DSN="host=127.0.0.1 port=5432 dbname=issue416_test user=postgres" \
        python -m unittest data-engineering/scripts/requests_s3_archive/tests/test_archive.py

The suite drops and recreates its fixture schemas, so it refuses to run unless
the host is loopback and the database name starts with issue416_.
"""

import os
import threading
import unittest
from pathlib import Path

import psycopg2
from psycopg2 import errors
from psycopg2.extensions import parse_dsn

ROOT = Path(__file__).resolve().parents[1]


class ArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ.get("ARCHIVAL_TEST_DSN", "")
        params = parse_dsn(cls.dsn)
        if params.get("host") not in {"127.0.0.1", "localhost", "::1"}:
            raise RuntimeError("Tests require an explicit loopback host")
        if not params.get("dbname", "").startswith("issue416_"):
            raise RuntimeError("Tests require a disposable issue416_* database")
        cls.conn = cls.connect()
        cls.cur = cls.conn.cursor()
        cls.cur.execute("""
            DROP SCHEMA IF EXISTS request_archive CASCADE;
            DROP SCHEMA IF EXISTS archival_test CASCADE;
            DROP SCHEMA IF EXISTS aws_s3 CASCADE;
            DROP TABLE IF EXISTS public.requests;
            CREATE TABLE public.requests (
                req_id text PRIMARY KEY,
                req_status_id int,
                last_updated_at timestamptz,
                req_desc text
            );
        """)
        for name in ("001_setup.sql", "tests/mock_aws_s3.sql", "002_archive.sql"):
            cls.cur.execute((ROOT / name).read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.cur.close()
        cls.conn.close()

    @classmethod
    def connect(cls):
        conn = psycopg2.connect(cls.dsn)
        conn.autocommit = True  # the procedure must be CALLed outside a txn
        return conn

    def setUp(self):
        self.cur.execute("""
            RESET ROLE;
            TRUNCATE request_archive.config, request_archive.watermark,
                request_archive.run_log, public.requests,
                archival_test.exports, archival_test.behavior
                RESTART IDENTITY CASCADE;
            INSERT INTO request_archive.config
                (bucket, region, safety_lag, replay_overlap)
            VALUES ('test-bucket', 'us-east-1', interval '0', interval '0');
            INSERT INTO archival_test.behavior DEFAULT VALUES;
        """)

    # -- helpers ----------------------------------------------------------
    def add(self, req_id, when, status=1):
        self.cur.execute(
            "INSERT INTO public.requests VALUES (%s, %s, %s, 'x')",
            (req_id, status, when))

    def call(self):
        self.cur.execute("CALL request_archive.run()")

    def last_run(self):
        self.cur.execute("""
            SELECT status, source_rows, uploaded_rows, error_message
            FROM request_archive.run_log ORDER BY run_id DESC LIMIT 1""")
        return self.cur.fetchone()

    def watermark(self):
        self.cur.execute("SELECT archived_through FROM request_archive.watermark")
        row = self.cur.fetchone()
        return row[0] if row else None

    def keys(self):
        self.cur.execute("SELECT file_path FROM archival_test.exports ORDER BY id")
        return [r[0] for r in self.cur.fetchall()]

    # -- tests ------------------------------------------------------------
    def test_initial_backfill_partitions_by_last_updated_month(self):
        self.add("R1", "2025-01-10 12:00+00")
        self.add("R2", "2025-01-31 23:59:59+00")
        self.add("R3", "2025-02-01 00:00:00+00")
        self.call()
        self.assertEqual(self.last_run()[:3], ("success", 3, 3))
        self.assertEqual(self.keys(), [
            "requests/year=2025/month=01/run_id=1/requests.csv",
            "requests/year=2025/month=02/run_id=1/requests.csv",
        ])
        self.cur.execute("SELECT outputs FROM request_archive.run_log")
        outputs = self.cur.fetchone()[0]
        self.assertEqual([o["uploaded_rows"] for o in outputs], [2, 1])
        self.assertGreater(str(self.watermark()), "2026")

    def test_partition_boundaries_use_utc_not_session_time_zone(self):
        self.cur.execute("SET TIME ZONE 'Asia/Kolkata'")
        self.add("R1", "2025-01-31 22:00:00+00")   # 03:30 Feb 1 in Kolkata
        self.call()
        self.cur.execute("RESET TIME ZONE")
        self.assertEqual(self.keys(),
                         ["requests/year=2025/month=01/run_id=1/requests.csv"])

    def test_second_run_exports_nothing_when_nothing_changed(self):
        self.add("R1", "2025-01-10 12:00+00")
        self.call()
        self.call()
        self.assertEqual(self.last_run()[:3], ("success", 0, 0))
        self.assertEqual(len(self.keys()), 1)  # only the first run uploaded

    def test_updated_row_is_archived_again_with_new_value(self):
        self.add("R1", "2025-01-10 12:00+00")
        self.call()
        self.cur.execute("""UPDATE public.requests
            SET req_status_id = 9, last_updated_at = clock_timestamp()
            WHERE req_id = 'R1'""")
        self.call()
        self.assertEqual(self.last_run()[:3], ("success", 1, 1))
        self.assertEqual(len(self.keys()), 2)
        self.assertIn("run_id=2", self.keys()[1])

    def test_overlap_reexports_rows_near_the_watermark(self):
        self.cur.execute("UPDATE request_archive.config "
                         "SET replay_overlap = interval '1 day'")
        self.cur.execute("INSERT INTO public.requests VALUES "
                         "('R1', 1, clock_timestamp(), 'x')")
        self.call()
        self.call()
        self.assertEqual(self.last_run()[:3], ("success", 1, 1))

    def test_source_is_never_modified(self):
        self.add("R1", "2025-01-10 12:00+00")
        self.cur.execute("SELECT md5(string_agg(t::text, '' ORDER BY req_id)) "
                         "FROM public.requests t")
        before = self.cur.fetchone()
        self.call()
        self.cur.execute("SELECT md5(string_agg(t::text, '' ORDER BY req_id)) "
                         "FROM public.requests t")
        self.assertEqual(before, self.cur.fetchone())

    def test_runs_with_select_only_privileges_on_requests(self):
        self.cur.execute("""
            DROP ROLE IF EXISTS archiver_416;
            CREATE ROLE archiver_416;
            GRANT USAGE ON SCHEMA request_archive, aws_s3, archival_test
                TO archiver_416;
            GRANT ALL ON ALL TABLES IN SCHEMA request_archive TO archiver_416;
            GRANT ALL ON ALL TABLES IN SCHEMA archival_test TO archiver_416;
            GRANT EXECUTE ON PROCEDURE request_archive.run() TO archiver_416;
            GRANT SELECT ON public.requests TO archiver_416;
        """)
        self.add("R1", "2025-01-10 12:00+00")
        self.cur.execute("SET ROLE archiver_416")
        try:
            self.call()
            self.assertEqual(self.last_run()[0], "success")
            with self.assertRaises(errors.InsufficientPrivilege):
                self.cur.execute("DELETE FROM public.requests")
        finally:
            self.cur.execute("RESET ROLE")

    def test_count_mismatch_fails_and_keeps_watermark(self):
        self.add("R1", "2025-01-10 12:00+00")
        self.cur.execute("UPDATE archival_test.behavior SET row_delta = -1")
        with self.assertRaises(psycopg2.Error):
            self.call()
        status, source, uploaded, message = self.last_run()
        self.assertEqual((status, source, uploaded), ("failed", 1, 0))
        self.assertIn("mismatch", message)
        self.cur.execute("SELECT count(*) FROM request_archive.watermark "
                         "WHERE archived_through > '-infinity'")
        self.assertEqual(self.cur.fetchone()[0], 0)

    def test_failed_upload_is_logged_and_retry_succeeds(self):
        self.add("R1", "2025-01-10 12:00+00")
        self.cur.execute("UPDATE archival_test.behavior SET fail_always = true")
        with self.assertRaises(psycopg2.Error):
            self.call()
        self.assertEqual(self.last_run()[0], "failed")
        self.cur.execute("UPDATE archival_test.behavior SET fail_always = false")
        self.call()
        self.assertEqual(self.last_run()[:3], ("success", 1, 1))
        self.cur.execute("SELECT status FROM request_archive.run_log ORDER BY 1")
        self.assertEqual([r[0] for r in self.cur.fetchall()],
                         ["failed", "success"])

    def test_null_last_updated_at_fails_instead_of_skipping_rows(self):
        self.add("R1", None)
        with self.assertRaises(psycopg2.Error):
            self.call()
        self.assertEqual(self.last_run()[0], "failed")
        self.assertIn("NULL", self.last_run()[3])

    def test_missing_config_is_logged_as_failure(self):
        self.cur.execute("TRUNCATE request_archive.config CASCADE")
        with self.assertRaises(psycopg2.Error):
            self.call()
        self.assertEqual(self.last_run()[0], "failed")

    def test_overlapping_run_is_skipped(self):
        other = self.connect()
        try:
            other.cursor().execute("SELECT pg_advisory_lock(416, 1)")
            self.call()
            self.assertEqual(self.last_run()[0], "skipped")
            self.assertEqual(self.keys(), [])
        finally:
            other.close()

    def test_abandoned_running_row_is_marked_interrupted(self):
        self.cur.execute("INSERT INTO request_archive.run_log(status) "
                         "VALUES ('running')")
        self.call()
        self.cur.execute("SELECT status FROM request_archive.run_log "
                         "ORDER BY run_id")
        self.assertEqual([r[0] for r in self.cur.fetchall()],
                         ["interrupted", "success"])

    def test_edit_during_export_does_not_break_reconciliation(self):
        self.add("R1", "2025-01-10 12:00+00")
        self.add("R2", "2025-02-10 12:00+00")
        self.cur.execute("UPDATE archival_test.behavior SET sleep_seconds = 1")

        def edit_midway():
            other = self.connect()
            other.cursor().execute("""SELECT pg_sleep(0.5);
                UPDATE public.requests SET last_updated_at = clock_timestamp()
                WHERE req_id = 'R2'""")
            other.close()

        worker = threading.Thread(target=edit_midway)
        worker.start()
        self.call()
        worker.join()
        self.assertEqual(self.last_run()[:3], ("success", 2, 2))
        # The edit was after the snapshot, so the next run picks it up.
        self.call()
        self.assertEqual(self.last_run()[:3], ("success", 1, 1))


if __name__ == "__main__":
    unittest.main()
