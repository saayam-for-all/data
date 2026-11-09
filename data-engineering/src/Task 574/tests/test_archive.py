"""Execute real SQL against synthetic SQLite; never contact AWS or production."""

import csv
import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

from Data_ArchiveRequestData.archive import ValidationError
from Data_ArchiveRequestData.config import REFERENCES, Settings
from Data_ArchiveRequestData.db_client import DatabaseClient
from Data_ArchiveRequestData.lambda_function import lambda_handler, run_archive
from local_fixture import LocalS3, REQUEST_COLUMNS, create_fixture


class ArchiveTests(unittest.TestCase):
    """Exercise the data-preservation contract and failure-before-upload order."""

    def setUp(self):
        """Give each test independent source data and an upload destination."""
        self.temporary = tempfile.TemporaryDirectory(prefix="task574-test-")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.path = self.folder / "fixture.sqlite3"
        create_fixture(self.path)
        self.sink = LocalS3(self.folder / "requests.csv")
        self.env = {"ARCHIVE_S3_BUCKET": "local-test", "ARCHIVE_BATCH_SIZE": "2"}
        self.factory = Mock(side_effect=lambda schema: DatabaseClient.local(self.path))
        self.s3_factory = Mock(return_value=self.sink)
        network = patch("socket.socket.connect", side_effect=AssertionError("Unexpected network"))
        network.start()
        self.addCleanup(network.stop)

    def change(self, query, params=()):
        """Mutate only the synthetic source before starting an archive run."""
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(query, params)

    def run_export(self, event=None):
        """Call production orchestration with local connection/storage factories."""
        return run_archive({} if event is None else event, environ=self.env,
                           database_factory=self.factory, s3_factory=self.s3_factory)

    def rows(self):
        """Read the actual exported CSV with the standard parser."""
        with self.sink.destination.open(encoding="utf-8", newline="") as file:
            return list(csv.DictReader(file))

    def assert_rejected(self, message):
        """Ensure invalid data never reaches even the S3 client factory."""
        with self.assertRaisesRegex(ValidationError, message):
            self.run_export()
        self.s3_factory.assert_not_called()
        self.assertFalse(self.sink.destination.exists())

    def test_full_snapshot_preserves_all_request_ids_and_columns(self):
        """The CSV represents every source row exactly once, including every status."""
        before = self.path.read_bytes()
        report = self.run_export()
        rows = self.rows()
        self.assertEqual(report["source_count"], 12)
        self.assertEqual(report["exported_count"], 12)
        self.assertEqual({row["req_id"] for row in rows}, {f"SYN-REQ-{i:03}" for i in range(1, 13)})
        self.assertEqual(len(rows), len({row["req_id"] for row in rows}))
        self.assertEqual([name for name in rows[0] if name in REQUEST_COLUMNS], list(REQUEST_COLUMNS))
        self.assertEqual(len(rows[0]), len(REQUEST_COLUMNS) + 6)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(len(self.sink.calls), 1)

    def test_readable_values_next_to_ids_and_user_ids_untouched(self):
        """Labels enrich raw IDs, with no user data lookup or hashing."""
        self.run_export()
        row = self.rows()[0]
        self.assertEqual(row["req_category"], "Food assistance")
        self.assertEqual(row["req_status"], "CREATED")
        self.assertEqual(row["req_for"], "OTHER")
        self.assertEqual(row["creator_id"], "SYN-USER-001")
        for ref in REFERENCES:
            columns = list(row)
            self.assertEqual(columns[columns.index(ref.source) + 1], ref.output)

    def test_null_and_unmatched_references_are_retained_for_every_lookup(self):
        """Unresolvable lookups never remove a request or erase its reference ID."""
        report = self.run_export()
        rows = {row["req_id"]: row for row in self.rows()}
        for ref in REFERENCES:
            with self.subTest(reference=ref.source):
                self.assertEqual(report["references"][ref.source]["null"], 1)
                self.assertEqual(report["references"][ref.source]["unmatched"], 1)
                self.assertEqual(report["references"][ref.source]["matched"], 10)
                self.assertEqual(rows["SYN-REQ-010"][ref.output], "")
                self.assertEqual(rows["SYN-REQ-011"][ref.output], "")
                self.assertNotEqual(rows["SYN-REQ-011"][ref.source], "")

    def test_null_label_is_not_an_unmatched_key(self):
        """An existing request_type with NULL label is tracked separately."""
        report = self.run_export()
        self.assertEqual(report["references"]["req_type_id"]["missing_label"], 1)
        self.assertEqual(report["references"]["req_type_id"]["unmatched"], 1)

    def test_csv_round_trip_preserves_quotes_newlines_unicode_and_raw_location(self):
        """CSV escaping must preserve the full description and source geometry text."""
        self.run_export()
        with closing(sqlite3.connect(self.path)) as connection:
            expected = connection.execute("SELECT req_desc, req_loc FROM requests ORDER BY req_id LIMIT 1").fetchone()
        actual = self.rows()[0]
        self.assertEqual((actual["req_desc"], actual["req_loc"]), expected)

    def test_duplicate_lookup_keys_rejected_for_each_table(self):
        """Never arbitrarily deduplicate conflicting lookup values."""
        for ref in REFERENCES:
            with self.subTest(table=ref.table):
                self.change(f"INSERT INTO {ref.table} SELECT * FROM {ref.table} LIMIT 1")
                self.assert_rejected("Duplicate lookup key")
                self.change(f"DELETE FROM {ref.table} WHERE rowid = (SELECT MAX(rowid) FROM {ref.table})")

    def test_duplicate_request_ids_rejected(self):
        """Source identity errors stop the archive."""
        self.change("INSERT INTO requests SELECT * FROM requests LIMIT 1")
        self.assert_rejected("duplicate or null req_id")

    def test_null_request_id_rejected(self):
        """An unidentifiable source request cannot pass validation."""
        self.change("UPDATE requests SET req_id = NULL WHERE req_id = 'SYN-REQ-001'")
        self.assert_rejected("duplicate or null req_id")

    def test_new_source_column_is_exported_without_data_loss(self):
        """Discovery includes newly added fields and safely quotes unusual names."""
        self.change('ALTER TABLE requests ADD COLUMN "new field" TEXT')
        self.change('UPDATE requests SET "new field" = ?', ("keep this value",))
        self.run_export()
        self.assertEqual(self.rows()[0]["new field"], "keep this value")

    def test_readable_column_collision_rejected(self):
        """Never produce ambiguous duplicate CSV headers after schema changes."""
        self.change("ALTER TABLE requests ADD COLUMN req_status TEXT")
        self.assert_rejected("collisions")

    def test_missing_reference_column_rejected(self):
        """A renamed foreign key cannot silently disable enrichment."""
        self.change("ALTER TABLE requests RENAME COLUMN req_cat_id TO wrong_category")
        self.assert_rejected("missing")

    def test_missing_lookup_label_rejected(self):
        """A malformed lookup schema fails before upload."""
        self.change("ALTER TABLE request_types RENAME COLUMN req_type TO wrong_label")
        self.assert_rejected("Required key/label")

    def test_row_limit_stops_before_upload(self):
        """Oversized windows must be narrowed explicitly."""
        self.env["ARCHIVE_MAX_ROWS"] = "5"
        self.assert_rejected("MAX_ROWS")

    def test_byte_limit_stops_before_upload(self):
        """Large text cannot silently exhaust the configured spool budget."""
        self.env["ARCHIVE_MAX_BYTES"] = "600"
        self.assert_rejected("MAX_BYTES")

    def test_empty_source_still_has_csv_headers(self):
        """A zero-row run is valid and produces a readable empty export."""
        self.change("DELETE FROM requests")
        result = self.run_export()
        self.assertEqual(result["exported_count"], 0)
        self.assertEqual(self.rows(), [])
        self.assertTrue(self.sink.destination.read_text().startswith("req_id,"))

    def test_incremental_window_is_lower_exclusive_upper_inclusive(self):
        """Exact endpoints belong to one and only one adjacent window."""
        report = self.run_export({"watermark_start": "2026-10-24T12:00:00Z",
                                  "watermark_end": "2026-10-25T12:00:00Z"})
        self.assertEqual([row["req_id"] for row in self.rows()], ["SYN-REQ-002"])
        self.assertEqual(report["excluded_null_timestamps"], 1)

    def test_adjacent_incremental_windows_do_not_overlap(self):
        """The shared boundary is not emitted twice."""
        self.run_export({"watermark_start": "2026-10-23T12:00:00Z", "watermark_end": "2026-10-25T12:00:00Z"})
        first = {row["req_id"] for row in self.rows()}
        self.run_export({"watermark_start": "2026-10-25T12:00:00Z", "watermark_end": "2026-10-28T12:00:00Z"})
        second = {row["req_id"] for row in self.rows()}
        self.assertTrue(first.isdisjoint(second))
        self.assertEqual(first | second, {"SYN-REQ-001", "SYN-REQ-002", "SYN-REQ-004", "SYN-REQ-005"})

    def test_timezone_offsets_are_normalized_to_utc(self):
        """UTC convention is preserved for PostgreSQL's naive timestamp column."""
        self.run_export({"watermark_start": "2026-10-24T08:00:00-04:00",
                         "watermark_end": "2026-10-25T08:00:00-04:00"})
        self.assertEqual([row["req_id"] for row in self.rows()], ["SYN-REQ-002"])

    def test_snapshot_retains_null_last_updated_at(self):
        """A full backup includes rows that an incremental window cannot select."""
        result = self.run_export()
        self.assertEqual(result["source_null_timestamps"], 1)
        self.assertEqual(result["excluded_null_timestamps"], 0)
        self.assertIn("SYN-REQ-003", {row["req_id"] for row in self.rows()})

    def test_dry_run_never_constructs_an_s3_client(self):
        """Validation-only execution performs no upload and needs no bucket."""
        self.env.pop("ARCHIVE_S3_BUCKET")
        result = self.run_export({"dry_run": True})
        self.s3_factory.assert_not_called()
        self.assertFalse(result["uploaded"])
        self.assertEqual(result["exported_count"], 12)

    def test_upload_failure_propagates_and_connection_closes(self):
        """Schedulers receive a failure and the source remains unchanged."""
        db = DatabaseClient.local(self.path)
        self.factory.side_effect = lambda schema: db
        self.sink.upload_fileobj = Mock(side_effect=OSError("simulated upload failure"))
        before = self.path.read_bytes()
        with self.assertRaisesRegex(OSError, "simulated"):
            self.run_export()
        with self.assertRaises(sqlite3.ProgrammingError):
            db.connection.execute("SELECT 1")
        self.assertEqual(before, self.path.read_bytes())

    def test_handler_propagates_failure_for_lambda_retries(self):
        """Returning a success-shaped error would suppress scheduled retries."""
        with patch("Data_ArchiveRequestData.lambda_function.run_archive", side_effect=RuntimeError("failed")):
            with self.assertLogs("Data_ArchiveRequestData.lambda_function", level="ERROR"):
                with self.assertRaises(RuntimeError):
                    lambda_handler({}, None)

    def test_retry_is_content_addressed_and_changed_data_gets_new_key(self):
        """Unchanged retries reuse a key; changed snapshots preserve prior objects."""
        first = self.run_export()
        second = self.run_export()
        self.assertEqual(first["key"], second["key"])
        self.assertEqual(first["sha256"], hashlib.sha256(self.sink.destination.read_bytes()).hexdigest())
        self.change("UPDATE requests SET req_desc = 'changed' WHERE req_id = 'SYN-REQ-001'")
        third = self.run_export()
        self.assertNotEqual(first["key"], third["key"])

    def test_s3_encryption_metadata_and_kms_options(self):
        """The upload includes an integrity digest and the selected encryption mode."""
        first = self.run_export()
        args = self.sink.calls[-1]["extra_args"]
        self.assertEqual(args["ServerSideEncryption"], "AES256")
        self.assertEqual(args["Metadata"]["sha256"], first["sha256"])
        self.env["ARCHIVE_KMS_KEY_ID"] = "alias/synthetic-test"
        self.run_export()
        args = self.sink.calls[-1]["extra_args"]
        self.assertEqual(args["ServerSideEncryption"], "aws:kms")
        self.assertEqual(args["SSEKMSKeyId"], "alias/synthetic-test")

    def test_database_snapshot_refuses_writes(self):
        """The local read-only protection is exercised against a real database."""
        db = DatabaseClient.local(self.path)
        try:
            with db.snapshot():
                with self.assertRaisesRegex(sqlite3.OperationalError, "readonly"):
                    db.connection.execute("DELETE FROM requests")
        finally:
            db.close()

    def test_concurrent_change_does_not_change_snapshot(self):
        """Counts and output see one snapshot even if a writer commits between them."""
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("PRAGMA journal_mode=WAL")
        db = DatabaseClient.local(self.path)
        original = db.cursor

        @contextmanager
        def cursor_with_writer(stream=False):
            """Commit an independent write just before opening the export cursor."""
            if stream:
                self.change("DELETE FROM requests WHERE req_id = 'SYN-REQ-001'")
            with original(stream) as cursor:
                yield cursor

        db.cursor = cursor_with_writer
        self.factory.side_effect = lambda schema: db
        report = self.run_export()
        self.assertEqual(report["source_count"], 12)
        self.assertEqual(len(self.rows()), 12)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM requests").fetchone()[0], 11)

    def test_stream_uses_fetchmany_without_fetchall(self):
        """The export consumes bounded batches and executes six LEFT JOINs."""
        db = DatabaseClient.local(self.path)
        original = db.cursor
        streams = []

        @contextmanager
        def observed_cursor(stream=False):
            """Observe streaming calls while executing the real SQL underneath."""
            with original(stream) as cursor:
                if stream:
                    wrapper = Mock(wraps=cursor)
                    wrapper.fetchall.side_effect = AssertionError("Unbounded fetch")
                    streams.append(wrapper)
                    yield wrapper
                else:
                    yield cursor

        db.cursor = observed_cursor
        self.factory.side_effect = lambda schema: db
        self.run_export()
        self.assertEqual(streams[0].fetchmany.call_count, 7)
        sql = streams[0].execute.call_args.args[0]
        self.assertEqual(sql.count("LEFT JOIN"), 6)
        self.assertNotIn("INNER JOIN", sql)
        self.assertNotIn('"users"', sql)

    def test_count_mismatch_blocks_upload(self):
        """An inconsistent count is treated as data loss, never as success."""
        from Data_ArchiveRequestData.archive import inspect_source

        def incorrect_count(db, settings):
            """Inject a faulty count to exercise reconciliation independently."""
            columns, count, nulls = inspect_source(db, settings)
            return columns, count + 1, nulls

        with patch("Data_ArchiveRequestData.archive.inspect_source", side_effect=incorrect_count):
            self.assert_rejected("row mismatch")

    def test_invalid_event_never_opens_a_connection(self):
        """Ambiguous windows and unexpected options fail before any I/O."""
        events = [[], {"dry_run": "false"}, {"bucket": "unexpected"},
                  {"watermark_start": "2026-10-24T00:00:00Z"},
                  {"watermark_start": "2026-10-24", "watermark_end": "2026-10-25"},
                  {"watermark_start": "2026-10-25T00:00:00Z", "watermark_end": "2026-10-24T00:00:00Z"},
                  {"watermark_start": None, "watermark_end": None}]
        for event in events:
            with self.subTest(event=event), self.assertRaises(ValueError):
                self.run_export(event)
        self.factory.assert_not_called()

    def test_configuration_rejects_invalid_identifiers_and_limits(self):
        """SQL identifiers and resource limits are validated, not interpolated blindly."""
        for key, value in (("ARCHIVE_DB_SCHEMA", 'public"; DROP TABLE requests; --'),
                           ("ARCHIVE_MAX_ROWS", "0"), ("ARCHIVE_BATCH_SIZE", "-1"),
                           ("ARCHIVE_MAX_BYTES", "bad"), ("ARCHIVE_S3_PREFIX", "../outside")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                Settings.from_event({}, {**self.env, key: value})

    def test_postgres_adapter_snapshot_and_cursor_contract(self):
        """Check adapter wiring; this is not a live PostgreSQL integration test."""
        connection = Mock()
        db = DatabaseClient(connection, "public")
        with db.snapshot():
            with db.cursor(stream=True):
                pass
        connection.set_session.assert_called_once_with(isolation_level="REPEATABLE READ",
                                                      readonly=True, autocommit=False)
        connection.cursor.assert_called_once_with(name="task574_requests")
        connection.rollback.assert_called_once()
        settings = Settings.from_event({"watermark_start": "2026-10-24T00:00:00Z",
                                        "watermark_end": "2026-10-25T00:00:00Z"}, self.env)
        predicate, params = db.selection(settings)
        self.assertEqual(predicate.count("%s"), 2)
        self.assertIsNone(params[0].tzinfo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
