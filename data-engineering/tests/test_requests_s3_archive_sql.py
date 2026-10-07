from pathlib import Path
import re


ARCHIVE_DIR = Path(__file__).resolve().parents[1] / "infrastructure" / "db" / "requests_s3_archive"
MIGRATION_SQL = (ARCHIVE_DIR / "001_requests_s3_archive.sql").read_text(encoding="utf-8")
SCHEDULE_SQL = (ARCHIVE_DIR / "002_schedule_pg_cron.sql").read_text(encoding="utf-8")


def _without_comments(sql: str) -> str:
    return re.sub(r"--.*?$", "", sql, flags=re.MULTILINE).lower()


def test_archive_job_exports_with_aws_s3_and_csv_header():
    sql = MIGRATION_SQL.lower()

    assert "aws_s3.query_export_to_s3" in sql
    assert "aws_commons.create_s3_uri" in sql
    assert "format csv" in sql
    assert "header true" in sql


def test_archive_job_is_incremental_on_last_updated_at():
    sql = MIGRATION_SQL.lower()

    assert "last_successful_watermark" in sql
    assert "where last_updated_at > v_watermark_start" in sql
    assert "and last_updated_at <= v_watermark_end" in sql


def test_archive_job_does_not_mutate_source_requests_table():
    sql = _without_comments(MIGRATION_SQL)

    forbidden = [
        r"\binsert\s+into\s+public\.requests\b",
        r"\bupdate\s+public\.requests\b",
        r"\bdelete\s+from\s+public\.requests\b",
        r"\btruncate\s+public\.requests\b",
    ]

    for pattern in forbidden:
        assert not re.search(pattern, sql)


def test_success_requires_source_and_uploaded_counts_to_match():
    sql = MIGRATION_SQL.lower()

    assert "v_source_rows <> v_total_rows_uploaded" in sql
    assert "requests s3 archive count mismatch" in sql
    assert "status = 'success'" in sql


def test_schedule_uses_pg_cron_weekly_job():
    sql = SCHEDULE_SQL.lower()

    assert "create extension if not exists pg_cron" in sql
    assert "cron.schedule" in sql
    assert "requests-s3-archive-weekly" in sql
    assert "'0 6 * * 0'" in sql
