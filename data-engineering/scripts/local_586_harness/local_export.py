"""
Local stand-in for archive.export_requests_to_s3() (see
data-engineering/infrastructure/db/requests_s3_archive/001_requests_s3_archive.sql).

The real function uses the aws_s3 Postgres extension, which only exists on AWS
RDS/Aurora -- it can't run in a local Docker Postgres. This script reproduces
the SAME watermark/partitioning/bookkeeping logic in Python, writing each
day's partition to a local CSV (at the same s3_key-shaped relative path)
instead of calling aws_s3.query_export_to_s3, and writes the same rows into
archive.requests_s3_runs / requests_s3_run_files that the real function would.

Run twice with the same explicit --watermark-end to test idempotency (issue
#586 check 6), or with no args to advance the watermark to "now" like the
real scheduled job would.
"""
import argparse
import csv
import datetime
import os

import psycopg2

OUT_ROOT = os.path.join(os.path.dirname(__file__), "local_s3", "requests")

COLUMNS = [
    "req_id", "creator_id", "beneficiary_id", "lead_volunteer_id",
    "req_cat_id", "req_for_id", "req_islead_id", "req_type_id", "req_priority_id", "req_status_id",
    "req_subj", "req_desc", "req_doc_link", "audio_req_desc", "deletion_reason",
    "req_loc", "created_loc", "iscalamity", "to_public",
    "submission_date", "serviced_date", "last_updated_at",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--watermark-end", default=None, help="ISO timestamp; defaults to now (UTC)")
    args = parser.parse_args()

    conn = psycopg2.connect(host="localhost", port=55432, user="postgres", password="postgres", dbname="saayam")
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SET search_path TO virginia_dev_saayam_rdbms, public;")

    watermark_end = (
        datetime.datetime.fromisoformat(args.watermark_end)
        if args.watermark_end
        else datetime.datetime.utcnow()
    )

    cur.execute("SELECT last_successful_watermark FROM archive.requests_s3_watermark WHERE watermark_id = true;")
    watermark_start = cur.fetchone()[0]

    if watermark_end <= watermark_start:
        print(f"nothing to do: watermark_end {watermark_end} <= current watermark {watermark_start}")
        return

    cur.execute(
        """
        INSERT INTO archive.requests_s3_runs (status, watermark_start, watermark_end, s3_bucket, s3_region, s3_prefix)
        VALUES ('running', %s, %s, 'local-fake-bucket', 'local', 'requests')
        RETURNING run_id;
        """,
        (watermark_start, watermark_end),
    )
    run_id = cur.fetchone()[0]

    cur.execute(
        """
        SELECT count(*), min(last_updated_at), max(last_updated_at)
        FROM requests
        WHERE last_updated_at > %s AND last_updated_at <= %s;
        """,
        (watermark_start, watermark_end),
    )
    source_rows, first_ts, last_ts = cur.fetchone()

    total_uploaded = 0
    if source_rows:
        day = first_ts.date()
        last_day = last_ts.date()
        while day <= last_day:
            day_start = datetime.datetime.combine(day, datetime.time.min)
            day_end = day_start + datetime.timedelta(days=1)

            cur.execute(
                f"""
                SELECT {', '.join(COLUMNS)} FROM requests
                WHERE last_updated_at > %s AND last_updated_at <= %s
                  AND last_updated_at >= %s AND last_updated_at < %s
                ORDER BY last_updated_at, req_id;
                """,
                (watermark_start, watermark_end, day_start, day_end),
            )
            partition_rows = cur.fetchall()

            if partition_rows:
                rel_key = (
                    f"last_updated_year={day.year:04d}/"
                    f"last_updated_month={day.month:02d}/"
                    f"last_updated_day={day.day:02d}/"
                    f"run_id={run_id}/requests.csv"
                )
                out_path = os.path.join(OUT_ROOT, *rel_key.split("/"))
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with open(out_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f, lineterminator="\n")
                    writer.writerow(COLUMNS)
                    writer.writerows(partition_rows)

                cur.execute(
                    """
                    INSERT INTO archive.requests_s3_run_files
                        (run_id, partition_date, s3_key, source_row_count, uploaded_row_count, uploaded_file_count, uploaded_bytes)
                    VALUES (%s, %s, %s, %s, %s, 1, %s);
                    """,
                    (run_id, day, "requests/" + rel_key, len(partition_rows), len(partition_rows), os.path.getsize(out_path)),
                )
                total_uploaded += len(partition_rows)

            day += datetime.timedelta(days=1)

    if source_rows != total_uploaded:
        cur.execute(
            "UPDATE archive.requests_s3_runs SET status='failed', finished_at=clock_timestamp(), "
            "source_row_count=%s, uploaded_row_count=%s, error_message='count mismatch' WHERE run_id=%s;",
            (source_rows, total_uploaded, run_id),
        )
        conn.commit()
        raise SystemExit(f"count mismatch: source={source_rows} uploaded={total_uploaded}")

    cur.execute(
        "UPDATE archive.requests_s3_runs SET status='success', finished_at=clock_timestamp(), "
        "source_row_count=%s, uploaded_row_count=%s, uploaded_file_count=(SELECT count(*) FROM archive.requests_s3_run_files WHERE run_id=%s) "
        "WHERE run_id=%s;",
        (source_rows, total_uploaded, run_id, run_id),
    )
    cur.execute(
        "UPDATE archive.requests_s3_watermark SET last_successful_watermark=%s, last_successful_run_id=%s, updated_at=clock_timestamp() "
        "WHERE watermark_id=true;",
        (watermark_end, run_id),
    )
    conn.commit()
    print(f"run_id={run_id} watermark {watermark_start} -> {watermark_end}: {total_uploaded} rows uploaded")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
