"""Integration checks against a disposable local PostgreSQL database.

The fixture replaces only aws_s3, not PostgreSQL transactions or SQL execution.
Set ARCHIVAL_TEST_DSN to a loopback database named issue416_* before running.
Never point this suite at a shared database: it recreates fixture schemas.
"""

import os
from pathlib import Path
import unittest

import psycopg2
from psycopg2.extensions import parse_dsn


class ArchivalTests(unittest.TestCase):
    """Exercise export selection, reconciliation, and recovery in PostgreSQL."""

    @classmethod
    def setUpClass(cls):
        """Install the real pipeline and a local replacement for S3."""
        cls.dsn = os.environ.get("ARCHIVAL_TEST_DSN", "")
        params = parse_dsn(cls.dsn)
        if params.get("host") not in {"127.0.0.1", "localhost", "::1"}:
            raise RuntimeError("Tests require an explicit loopback host")
        if not params.get("dbname", "").startswith("issue416_"):
            raise RuntimeError("Tests require a disposable issue416_* database")
        cls.conn = psycopg2.connect(cls.dsn)
        cls.conn.autocommit = True
        cls.cur = cls.conn.cursor()
        cls.cur.execute("""
            DROP SCHEMA IF EXISTS requests_archival CASCADE;
            DROP SCHEMA IF EXISTS archival_test CASCADE;
            DROP SCHEMA IF EXISTS aws_s3 CASCADE;
            DROP TABLE IF EXISTS public.requests;
            CREATE TABLE public.requests (
                req_id text PRIMARY KEY,
                last_updated_at timestamptz NOT NULL,
                status text, description text
            );
        """)
        root = Path(__file__).resolve().parents[1]
        for file in (root / "001_setup.sql", root / "tests/mock_s3.sql",
                     root / "002_archive.sql"):
            cls.cur.execute(file.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        """Close the dedicated test session and release any remaining locks."""
        cls.cur.close()
        cls.conn.close()

    def setUp(self):
        """Reset only the disposable test database between scenarios."""
        self.cur.execute("""
            TRUNCATE requests_archival.config,
                requests_archival.watermark, requests_archival.runs,
                public.requests, archival_test.exports RESTART IDENTITY;
            INSERT INTO requests_archival.config
                (job_name, bucket, region, safety_lag, replay_overlap)
            VALUES ('requests', 'local-test-only', 'us-east-1', '0', '0');
            UPDATE archival_test.control SET mode = 'success';
        """)

    def run_job(self):
        """Call in autocommit mode and retrieve the authoritative run result."""
        self.cur.execute("CALL requests_archival.archive_requests()")
        self.cur.execute("""
            SELECT status, source_rows, uploaded_rows, outputs
            FROM requests_archival.runs ORDER BY run_id DESC LIMIT 1
        """)
        return self.cur.fetchone()

    def seed(self):
        """Insert two old requests in separate month partitions."""
        self.cur.execute("""
            INSERT INTO public.requests VALUES
                ('a', '2024-01-01', 'open', 'first'),
                ('b', '2024-02-01', 'open', 'second')
        """)

    def watermark(self):
        """Read the committed cutoff, or None when no run has succeeded."""
        self.cur.execute("SELECT completed_through FROM requests_archival.watermark")
        row = self.cur.fetchone()
        return row[0] if row else None

    def test_backfill_and_partition_counts(self):
        """First execution archives all history without editing source rows."""
        self.seed()
        status, source, uploaded, outputs = self.run_job()
        self.assertEqual((status, source, uploaded), ("success", 2, 2))
        self.assertEqual(len(outputs), 2)
        self.assertIn("year=2024/month=01/run_id=1/", outputs[0]["key"])
        self.cur.execute("SELECT count(*) FROM public.requests WHERE status='open'")
        self.assertEqual(self.cur.fetchone()[0], 2)

    def test_unchanged_and_empty_runs(self):
        """Empty source and unchanged source both succeed with zero uploads."""
        self.assertEqual(self.run_job()[:3], ("success", 0, 0))
        self.seed()
        # Reset the watermark for historical fixture inserts, not production.
        self.cur.execute("UPDATE requests_archival.watermark SET completed_through='-infinity'")
        self.run_job()
        self.assertEqual(self.run_job()[:3], ("success", 0, 0))

    def test_insert_and_updated_request(self):
        """Changes after a successful cutoff are exported with their new values."""
        self.seed()
        self.run_job()
        self.cur.execute("""
            UPDATE public.requests SET status='resolved',
                last_updated_at=clock_timestamp() WHERE req_id='a';
            INSERT INTO public.requests VALUES ('c', clock_timestamp(), 'open', 'new');
        """)
        self.assertEqual(self.run_job()[:3], ("success", 2, 2))
        self.cur.execute("SELECT payload FROM archival_test.exports ORDER BY object_key DESC LIMIT 1")
        self.assertIn("resolved", str(self.cur.fetchone()[0]))

    def test_count_mismatch_preserves_watermark(self):
        """A mismatch is persisted as failure; it cannot advance the cutoff."""
        self.seed()
        self.cur.execute("UPDATE archival_test.control SET mode='mismatch'")
        self.assertEqual(self.run_job()[:3], ("failed", 2, 0))
        self.assertIsNone(self.watermark())
        self.cur.execute("UPDATE archival_test.control SET mode='success'")
        self.assertEqual(self.run_job()[:3], ("success", 2, 2))

    def test_upload_failure_and_retry(self):
        """A failed re-export leaves the existing successful watermark intact."""
        self.seed()
        self.run_job()
        previous = self.watermark()
        self.cur.execute("UPDATE public.requests SET last_updated_at=clock_timestamp()")
        self.cur.execute("UPDATE archival_test.control SET mode='failure'")
        self.assertEqual(self.run_job()[0], "failed")
        self.assertEqual(self.watermark(), previous)
        self.cur.execute("UPDATE archival_test.control SET mode='success'")
        self.assertEqual(self.run_job()[:3], ("success", 2, 2))

    def test_partial_upload_failure(self):
        """Successful earlier partitions do not make the whole run successful."""
        self.seed()
        self.cur.execute("UPDATE archival_test.control SET mode='partial_failure'")
        result = self.run_job()
        self.assertEqual(result[:3], ("failed", 2, 1))
        self.assertEqual(len(result[3]), 1)
        self.assertIsNone(self.watermark())

    def test_concurrent_run_is_skipped(self):
        """A second session cannot export while the job lock is held."""
        other = psycopg2.connect(self.dsn)
        other.autocommit = True
        try:
            with other.cursor() as cur:
                cur.execute("SELECT pg_advisory_lock(416, 1)")
            self.assertEqual(self.run_job()[0], "skipped")
            self.assertIsNone(self.watermark())
        finally:
            other.close()

    def test_abandoned_run_is_recorded(self):
        """An abandoned durable start record is marked interrupted next time."""
        self.cur.execute("INSERT INTO requests_archival.runs(status) VALUES ('running')")
        self.run_job()
        self.cur.execute("SELECT status FROM requests_archival.runs ORDER BY run_id")
        self.assertEqual(self.cur.fetchall(), [("interrupted",), ("success",)])

    def test_replay_overlap_catches_late_row(self):
        """A late-visible change in the configured replay interval is included."""
        self.run_job()
        self.cur.execute("""
            UPDATE requests_archival.config SET replay_overlap='1 day';
            INSERT INTO public.requests VALUES
                ('late', clock_timestamp() - interval '1 hour', 'open', 'late');
        """)
        self.assertEqual(self.run_job()[:3], ("success", 1, 1))

    def test_safety_lag_excludes_recent_change(self):
        """The safety lag postpones recent records without losing older ones."""
        self.seed()
        self.cur.execute("""
            UPDATE requests_archival.config SET safety_lag='5 minutes';
            INSERT INTO public.requests VALUES ('new', clock_timestamp(), 'open', 'wait');
        """)
        self.assertEqual(self.run_job()[:3], ("success", 2, 2))

    def test_timestamp_ties_at_watermark(self):
        """Inclusive lower bounds avoid skipping equal-timestamp arrivals."""
        self.run_job()
        self.cur.execute("""
            INSERT INTO public.requests
            SELECT 'boundary', completed_through, 'open', 'tie'
            FROM requests_archival.watermark;
        """)
        self.assertEqual(self.run_job()[:3], ("success", 1, 1))

    def test_missing_configuration_is_logged(self):
        """Deployment misconfiguration leaves a durable failed run."""
        self.cur.execute("DELETE FROM requests_archival.config")
        self.assertEqual(self.run_job()[0], "failed")
        self.assertIsNone(self.watermark())

    def test_export_uses_snapshot_when_source_changes(self):
        """Source mutations during upload do not change the counted batch."""
        self.seed()
        self.cur.execute("UPDATE archival_test.control SET mode='concurrent_update'")
        self.assertEqual(self.run_job()[:3], ("success", 2, 2))
        self.cur.execute("SELECT payload FROM archival_test.exports")
        self.assertTrue(all(
            item["status"] == "open"
            for (payload,) in self.cur.fetchall() for item in payload
        ))
        self.assertEqual(self.run_job()[:3], ("success", 2, 2))

    def test_source_select_only_role(self):
        """The procedure succeeds without source INSERT/UPDATE/DELETE rights."""
        self.seed()
        self.cur.execute("""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles
                               WHERE rolname='issue416_reader') THEN
                    CREATE ROLE issue416_reader;
                END IF;
            END $$;
            GRANT USAGE ON SCHEMA public, requests_archival, aws_s3,
                archival_test TO issue416_reader;
            GRANT SELECT ON public.requests TO issue416_reader;
            GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA
                requests_archival TO issue416_reader;
            GRANT USAGE ON ALL SEQUENCES IN SCHEMA requests_archival
                TO issue416_reader;
            GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA archival_test
                TO issue416_reader;
            GRANT EXECUTE ON PROCEDURE requests_archival.archive_requests()
                TO issue416_reader;
            SET ROLE issue416_reader;
        """)
        try:
            self.assertEqual(self.run_job()[:3], ("success", 2, 2))
        finally:
            self.cur.execute("RESET ROLE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
