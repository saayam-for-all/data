from pathlib import Path
import re


SQL_PATH = (
    Path(__file__).resolve().parents[1]
    / "infrastructure"
    / "db"
    / "archive"
    / "001_public_requests_s3_archive.sql"
)


def archive_sql() -> str:
    return SQL_PATH.read_text(encoding="utf-8")


def without_comments(sql: str) -> str:
    return re.sub(r"--.*", "", sql).lower()


def test_public_requests_is_only_selected_from():
    sql = without_comments(archive_sql())

    assert re.search(r"\bfrom\s+public\.requests\b", sql)
    assert re.search(r"\bselect\s+(count\(\*\)|\*)", sql)

    forbidden_patterns = [
        r"\binsert\s+into\s+public\.requests\b",
        r"\bupdate\s+public\.requests\b",
        r"\bdelete\s+from\s+public\.requests\b",
        r"\btruncate\s+(table\s+)?public\.requests\b",
        r"\balter\s+table\s+public\.requests\b",
        r"\bdrop\s+table\s+public\.requests\b",
    ]
    for pattern in forbidden_patterns:
        assert not re.search(pattern, sql), pattern


def test_archive_uses_database_side_s3_export_and_audit_tables():
    sql = without_comments(archive_sql())

    assert "aws_s3.query_export_to_s3" in sql
    assert "aws_commons.create_s3_uri" in sql
    assert "create table if not exists request_archive.archive_watermarks" in sql
    assert "create table if not exists request_archive.archive_runs" in sql
    assert "source_row_count" in sql
    assert "exported_row_count" in sql
    assert "failure_message" in sql


def test_incremental_watermark_is_last_updated_at_based():
    sql = without_comments(archive_sql())

    assert "last_successful_watermark" in sql
    assert "last_updated_at <= p_window_end" in sql
    assert "last_updated_at > v_effective_watermark" in sql
    assert "max(last_updated_at)" in sql


def test_subsequent_runs_exclude_previous_watermark_timestamp():
    sql = without_comments(archive_sql())

    assert "last_updated_at >= v_effective_watermark" not in sql
    assert "last_updated_at >= %l::timestamptz" not in sql
    assert sql.count("last_updated_at > v_effective_watermark") == 1
    assert sql.count("last_updated_at > %l::timestamptz") == 1
    assert "v_effective_watermark is null or last_updated_at > v_effective_watermark" in sql
    assert "%l::timestamptz is null or last_updated_at > %l::timestamptz" in sql


def test_success_requires_count_match_before_watermark_update():
    sql = without_comments(archive_sql())

    count_match = sql.index("if v_source_row_count = v_exported_row_count then")
    watermark_update = sql.index("update request_archive.archive_watermarks")
    mismatch_failure = sql.index("exported row count mismatch")

    assert count_match < watermark_update
    assert count_match < mismatch_failure


def test_zero_row_runs_do_not_call_aws_s3_export():
    sql = without_comments(archive_sql())

    zero_branch = sql.index("if v_source_row_count = 0 then")
    export_call = sql.index("aws_s3.query_export_to_s3")
    zero_success_count = sql.index("v_exported_row_count := 0")

    assert zero_branch < zero_success_count < export_call
