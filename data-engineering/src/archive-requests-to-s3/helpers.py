import json
import os

import psycopg2
from psycopg2 import sql
from aws_lambda_powertools.utilities import parameters


DB_PARAMETER = "/dev/saayam/db/Virginia/Analytics/user"


def get_db_connection():
    """
    Create a PostgreSQL connection using credentials stored in
    AWS Systems Manager Parameter Store.
    """
    creds = json.loads(
        parameters.get_parameter(
            DB_PARAMETER,
            decrypt=True,
            max_age=3600,
        )
    )

    connection = psycopg2.connect(
        host=creds["HOST"],
        user=creds["USERNAME"],
        password=creds["PASSWORD"],
        database=creds["DATABASE_NAME"],
        port=creds["PORT"],
        sslmode="require",
    )

    return connection, creds["DATABASE_NAME"]

def ensure_watermark_table(connection, db_name):
    """
    Create the archive watermark table if it does not already exist
    and initialize the request archive watermark.
    """
    with connection.cursor() as cursor:
        cursor.execute(
    sql.SQL(
        """
        CREATE TABLE IF NOT EXISTS {}.request_archive_watermark (
            archive_name VARCHAR(100) PRIMARY KEY,
            last_successful_watermark TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
                DEFAULT CURRENT_TIMESTAMP
        )
        """
    ).format(sql.Identifier(db_name))
)

        cursor.execute(
    sql.SQL(
        """
        INSERT INTO {}.request_archive_watermark (
            archive_name,
            last_successful_watermark
        )
        VALUES (
            'request_archive_to_s3',
            TIMESTAMP '1970-01-01 00:00:00'
        )
        ON CONFLICT (archive_name) DO NOTHING
        """
    ).format(sql.Identifier(db_name))
)


def get_previous_watermark(connection, db_name):
    """
    Return the last successfully archived watermark.
    """
    with connection.cursor() as cursor:
        cursor.execute(
    sql.SQL(
        """
        SELECT last_successful_watermark
        FROM {}.request_archive_watermark
        WHERE archive_name = 'request_archive_to_s3'
        """
    ).format(sql.Identifier(db_name))
)

        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("Request archive watermark was not found.")

    return row[0]

def get_source_count(connection, db_name, previous_watermark, current_watermark):
    """
    Count request rows eligible for the current incremental archive run.
    """
    with connection.cursor() as cursor:
        cursor.execute(
    sql.SQL(
        """
        SELECT COUNT(*)
        FROM {}.request
        WHERE last_update_date > %s
          AND last_update_date <= %s
        """
    ).format(sql.Identifier(db_name)),
    (previous_watermark, current_watermark),
)

        row = cursor.fetchone()

    return row[0]

def export_requests_to_s3(
    connection,
    db_name,
    previous_watermark,
    current_watermark,
    bucket,
    key,
    region,
):
    """
    Export the current incremental request batch from PostgreSQL to S3.

    Returns AWS export statistics:
    rows_uploaded, files_uploaded, bytes_uploaded.
    """
    export_query = sql.SQL(
    """
    SELECT *
    FROM {}.request
    WHERE last_update_date > %L
      AND last_update_date <= %L
    ORDER BY last_update_date, req_id
    """
).format(sql.Identifier(db_name)).as_string(connection)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT rows_uploaded, files_uploaded, bytes_uploaded
            FROM aws_s3.query_export_to_s3(
                format(%s, %s, %s),
                aws_commons.create_s3_uri(%s, %s, %s),
                options := 'format csv, header true'
            )
            """,
            (
                export_query,
                previous_watermark,
                current_watermark,
                bucket,
                key,
                region,
            ),
        )

        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("S3 export did not return export statistics.")

    return {
        "rows_uploaded": row[0],
        "files_uploaded": row[1],
        "bytes_uploaded": row[2],
    }

def update_watermark(
    connection,
    db_name,
    current_watermark,
    source_count,
    rows_uploaded,
):
    """
    Advance the archive watermark only after successful row-count reconciliation.
    """
    if source_count != rows_uploaded:
        raise RuntimeError(
            "Archive reconciliation failed: "
            f"source_count={source_count}, "
            f"rows_uploaded={rows_uploaded}."
        )

    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                """
                UPDATE {}.request_archive_watermark
                SET last_successful_watermark = %s,
                updated_at = CURRENT_TIMESTAMP
                WHERE archive_name = 'request_archive_to_s3'
                """
            ).format(sql.Identifier(db_name)),
            (current_watermark,),
        )

        if cursor.rowcount != 1:
            raise RuntimeError(
                "Archive watermark update did not affect exactly one row."
            )
    connection.commit()

def archive_requests():
    """
    Run one incremental request archival cycle.
    """
    bucket = os.environ["ARCHIVE_BUCKET"]
    region = os.environ["AWS_REGION"]

    connection = None

    try:
        connection, db_name = get_db_connection()

        ensure_watermark_table(connection, db_name)

        previous_watermark = get_previous_watermark(connection, db_name)

        with connection.cursor() as cursor:
            cursor.execute("SELECT CURRENT_TIMESTAMP")
            current_watermark = cursor.fetchone()[0]

        source_count = get_source_count(
            connection,
            db_name,
            previous_watermark,
            current_watermark,
        )
        if source_count == 0:
            update_watermark(
        connection,
        db_name,
        current_watermark,
        0,
        0,
    )

        connection.commit()

        return {
        "status": "success",
        "message": "No request records required archiving.",
        "previous_watermark": previous_watermark,
        "current_watermark": current_watermark,
        "source_count": 0,
        "rows_uploaded": 0,
        "files_uploaded": 0,
        "bytes_uploaded": 0,
    }

    # Use a unique prefix for each archival window.
        archive_key = (
            "request-archive/"
            f"from={previous_watermark.isoformat()}/"
            f"to={current_watermark.isoformat()}/"
            "requests"
        )

        export_stats = export_requests_to_s3(
            connection,
            db_name,
            previous_watermark,
            current_watermark,
            bucket,
            archive_key,
            region,
        )

        update_watermark(
            connection,
            db_name,
            current_watermark,
            source_count,
            export_stats["rows_uploaded"],
        )
        connection.commit()

        return {
            "status": "success",
            "previous_watermark": previous_watermark,
            "current_watermark": current_watermark,
            "source_count": source_count,
            **export_stats,
            "s3_bucket": bucket,
            "s3_key": archive_key,
        }

    except Exception:
        if connection is not None:
            connection.rollback()
        raise

    finally:
        if connection is not None:
            connection.close()