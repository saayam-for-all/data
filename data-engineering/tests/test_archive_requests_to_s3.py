import importlib.util
from pathlib import Path

import pytest


HELPERS_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "archive-requests-to-s3"
    / "helpers.py"
)

spec = importlib.util.spec_from_file_location(
    "archive_requests_helpers",
    HELPERS_PATH,
)
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)


class FakeCursor:
    def __init__(self):
        self.rowcount = 1
        self.executed_query = None
        self.executed_params = None

    def execute(self, query, params=None):
        self.executed_query = query
        self.executed_params = params

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class FakeConnection:
    def __init__(self):
        self.commit_called = False
        self.cursor_instance = FakeCursor()

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commit_called = True


def test_watermark_not_updated_when_counts_do_not_match():
    connection = FakeConnection()

    with pytest.raises(RuntimeError, match="Archive reconciliation failed"):
        helpers.update_watermark(
            connection=connection,
            db_name="virginia_dev_saayam_rdbms",
            current_watermark="2026-10-06 03:00:00",
            source_count=10,
            rows_uploaded=9,
        )

    assert connection.commit_called is False

def test_watermark_updated_when_counts_match():
    connection = FakeConnection()

    helpers.update_watermark(
        connection=connection,
        db_name="virginia_dev_saayam_rdbms",
        current_watermark="2026-10-06 03:00:00",
        source_count=10,
        rows_uploaded=10,
    )

    assert connection.commit_called is True
    assert connection.cursor_instance.rowcount == 1
    assert connection.cursor_instance.executed_params == (
        "2026-10-06 03:00:00",
    )