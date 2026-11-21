"""AWS entry point: Data_ArchiveRequestData.lambda_function.lambda_handler."""

import json
import logging

from .archive import create_archive, object_key
from .config import Settings
from .db_client import DatabaseClient


LOGGER = logging.getLogger(__name__)


def run_archive(event, *, environ=None, database_factory=None, s3_factory=None):
    """Run the same export path in Lambda and in the dependency-injected demo."""
    settings = Settings.from_event(event, environ)
    factory = database_factory or DatabaseClient.production
    db = factory(settings.schema)
    try:
        with create_archive(db, settings) as (csv_file, report):
            report["uploaded"] = False
            if not settings.dry_run:
                if s3_factory is None:
                    import boto3

                    s3 = boto3.client("s3")
                else:
                    s3 = s3_factory()
                extra = {"ContentType": "text/csv; charset=utf-8",
                         "Metadata": {"sha256": report["sha256"],
                                      "request-count": str(report["exported_count"])},
                         "ServerSideEncryption": "AES256"}
                if settings.kms_key_id:
                    extra.update(ServerSideEncryption="aws:kms", SSEKMSKeyId=settings.kms_key_id)
                key = object_key(settings, report)
                s3.upload_fileobj(csv_file, settings.bucket, key, ExtraArgs=extra)
                report.update(uploaded=True, bucket=settings.bucket, key=key)
            return report
    finally:
        db.close()


def lambda_handler(event, context):
    """Propagate failures so Lambda/scheduler retries cannot mistake success."""
    try:
        result = run_archive(event)
    except Exception as exc:
        # Do not log exception messages, DSNs, request text, or database values.
        LOGGER.error("Data_ArchiveRequestData failed (%s)", type(exc).__name__)
        raise
    LOGGER.info("Archive validation: %s", json.dumps(result, sort_keys=True))
    return result
