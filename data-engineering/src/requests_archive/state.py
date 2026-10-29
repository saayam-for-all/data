"""
Watermark and run-log storage. Backend is chosen with STATE_STORE.

  postgres  archive_watermark / archive_run_log in the application schema.
            The default. Queryable in SQL alongside the source data.

  s3        a JSON document in the archive bucket. No database writes, so the
            connection can stay read only.

  none      no persistence. Every run needs an explicit range in the
            invocation payload. For testing before the tables exist and for
            one-off backfills.

handler.py does not know which one it has.
"""

import json
import os
from datetime import datetime, timezone

STORE = os.environ.get("STATE_STORE", "postgres").lower()
SCHEMA = os.environ.get("ARCHIVE_SCHEMA", "virginia_dev_saayam_rdbms")
WM_TABLE = f'"{SCHEMA}".archive_watermark'
LOG_TABLE = f'"{SCHEMA}".archive_run_log'


class StateStore:
    """Base class.

    durable: whether this store keeps a watermark across invocations. The
    handler checks it before an incremental run with no explicit range.
    """

    durable = True

    def get_watermark(self, table, stream):
        raise NotImplementedError

    def set_watermark(self, table, stream, value):
        raise NotImplementedError

    def touch(self, table, stream):
        """Record that a run happened and found nothing."""

    def log_run(self, rec):
        """Persist one run record. Must not raise."""

    def flush(self):
        """Called once at the end. Only the S3 backend needs it."""


# ------------------------------------------------------------------ postgres
class PostgresState(StateStore):
    def __init__(self, conn):
        self.conn = conn

    def get_watermark(self, table, stream):
        # FOR UPDATE so two overlapping runs of the same stream cannot read the
        # same starting point and export the same rows twice.
        r = self.conn.run(
            f"SELECT last_value_at FROM {WM_TABLE} "
            "WHERE source_table = :t AND stream = :s FOR UPDATE",
            t=table, s=stream)
        return r[0][0] if r else None

    def set_watermark(self, table, stream, value):
        n = self.conn.run(
            f"UPDATE {WM_TABLE} SET last_value_at = :v, last_run_at = (now() AT TIME ZONE 'UTC') "
            "WHERE source_table = :t AND stream = :s RETURNING source_table",
            v=value, t=table, s=stream)
        if not n:
            self.conn.run(
                f"INSERT INTO {WM_TABLE} (source_table, stream, last_value_at) "
                "VALUES (:t, :s, :v)", t=table, s=stream, v=value)

    def touch(self, table, stream):
        self.conn.run(
            f"UPDATE {WM_TABLE} SET last_run_at = (now() AT TIME ZONE 'UTC') "
            "WHERE source_table = :t AND stream = :s", t=table, s=stream)

    def log_run(self, rec):
        try:
            self.conn.run(
                f"""INSERT INTO {LOG_TABLE}
                    (invocation_id, source_table, stream, started_at, finished_at,
                     range_from, range_to, s3_key, source_rows, rows_written,
                     bytes_written, columns_dropped, columns_masked, status,
                     error_message, triggered_by)
                    VALUES (:i, :t, :st, :sa, :fa, :rf, :rt, :k, :sr, :rw, :bw,
                            :cd, :cm, :s, :e, :tb)""",
                i=rec.get("invocation"), t=rec.get("table"), st=rec.get("stream"),
                sa=rec.get("started_at"), fa=rec.get("finished_at"),
                rf=rec.get("range_from"), rt=rec.get("range_to"),
                k=rec.get("s3_key"), sr=rec.get("source_rows"),
                rw=rec.get("rows_written"), bw=rec.get("bytes"),
                cd=rec.get("columns_dropped"), cm=rec.get("columns_masked"),
                s=rec.get("status"), e=rec.get("error"),
                tb=rec.get("triggered_by"))
        except Exception as exc:
            # The CloudWatch line has already been written. Don't fail the run
            # because the log insert failed.
            print(json.dumps({"event": "log_insert_failed", "error": str(exc)}))


# ------------------------------------------------------------------------ s3
class S3State(StateStore):
    def __init__(self, s3, bucket, key, run_prefix, invocation):
        self.s3, self.bucket, self.key = s3, bucket, key
        self.run_prefix, self.invocation = run_prefix, invocation
        self.doc, self.etag = self._read()
        self.dirty = False

    def _read(self):
        import botocore
        try:
            r = self.s3.get_object(Bucket=self.bucket, Key=self.key)
            return json.loads(r["Body"].read()), r["ETag"]
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404") or exc.__class__.__name__ == "NoSuchKey":
                return {"version": 1, "tables": {}}, None
            raise

    def _k(self, table, stream):
        return f"{table}@{stream}"

    def get_watermark(self, table, stream):
        e = self.doc["tables"].get(self._k(table, stream))
        return e["last_value"] if e else None

    def set_watermark(self, table, stream, value):
        self.doc["tables"][self._k(table, stream)] = {
            "last_value": str(value),
            "last_run_at": datetime.now(timezone.utc).isoformat()}
        self.dirty = True

    def touch(self, table, stream):
        e = self.doc["tables"].setdefault(self._k(table, stream), {})
        e["last_run_at"] = datetime.now(timezone.utc).isoformat()
        self.dirty = True

    def log_run(self, rec):
        try:
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            self.s3.put_object(
                Bucket=self.bucket,
                Key=f"{self.run_prefix}/ingest_date={day}/{self.invocation}-{rec['table']}.json",
                Body=json.dumps(rec, default=str).encode(),
                ContentType="application/json")
        except Exception as exc:
            print(json.dumps({"event": "log_write_failed", "error": str(exc)}))

    def flush(self):
        if not self.dirty:
            return
        kw = dict(Bucket=self.bucket, Key=self.key,
                  Body=json.dumps(self.doc, indent=2, default=str).encode(),
                  ContentType="application/json")
        # Optimistic concurrency, behind reserved concurrency of 1.
        if self.etag:
            kw["IfMatch"] = self.etag
        else:
            kw["IfNoneMatch"] = "*"
        self.s3.put_object(**kw)


# ---------------------------------------------------------------------- none
class NoState(StateStore):
    """No persistence. The caller supplies the range."""

    durable = False

    def get_watermark(self, table, stream):
        return None

    def set_watermark(self, table, stream, value):
        pass


def build(conn=None, s3=None, bucket=None, invocation=None):
    if STORE == "postgres":
        if conn is None:
            raise RuntimeError("STATE_STORE=postgres needs a database connection")
        return PostgresState(conn)
    if STORE == "s3":
        return S3State(s3, bucket,
                       os.environ.get("STATE_KEY", "_state/watermark.json"),
                       os.environ.get("RUN_PREFIX", "_state/runs"), invocation)
    if STORE == "none":
        return NoState()
    raise ValueError(f"unknown STATE_STORE {STORE!r}, expected postgres, s3 or none")
