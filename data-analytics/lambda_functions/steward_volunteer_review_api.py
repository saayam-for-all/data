"""AWS Lambda API for the Steward Dashboard volunteer-review queue.

Production database contract (saayam-for-all/database):

* pending review requests live in ``volunteer_applications``;
* ``application_status = 'IN_REVIEW'`` requires steward action;
* accepted applications are migrated to ``volunteer_details``.

The SSM Parameter Store names are supplied through environment variables:
``VIRGINIA_DB_SSM_PARAMETER`` and/or ``IRELAND_DB_SSM_PARAMETER``.
No credentials or Parameter Store paths are stored in this module.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence


LOGGER = logging.getLogger(__name__)

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 5
MAX_PAGE_SIZE = 100
REVIEW_STATUS = "IN_REVIEW"
REVIEW_ACTION = "Review"

RESPONSE_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}

_SQL_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class RequestValidationError(ValueError):
    """Raised when the request payload is invalid."""


class ConfigurationError(RuntimeError):
    """Raised when required deployment configuration is unavailable."""


@dataclass(frozen=True)
class RegionDefinition:
    """Static deployment settings for one regional database."""

    name: str
    parameter_environment_variable: str
    schema_environment_variable: str
    default_schema: str
    rank: int


@dataclass(frozen=True)
class ConfiguredRegion:
    """A region whose SSM parameter and schema have been resolved."""

    name: str
    parameter_name: str
    schema: str
    rank: int


@dataclass(frozen=True)
class ReviewCandidate:
    """One volunteer application waiting for steward review."""

    user_id: str
    updated_time: datetime | None
    region_rank: int


REGION_DEFINITIONS = (
    RegionDefinition(
        name="Virginia",
        parameter_environment_variable="VIRGINIA_DB_SSM_PARAMETER",
        schema_environment_variable="VIRGINIA_DB_SCHEMA",
        default_schema="virginia_dev_saayam_rdbms",
        rank=0,
    ),
    RegionDefinition(
        name="Ireland",
        parameter_environment_variable="IRELAND_DB_SSM_PARAMETER",
        schema_environment_variable="IRELAND_DB_SCHEMA",
        default_schema="ireland_dev_saayam_rdbms",
        rank=1,
    ),
)


def build_response(status_code: int, body: Mapping[str, Any]) -> dict[str, Any]:
    """Return an API Gateway proxy-compatible response."""

    return {
        "statusCode": status_code,
        "headers": dict(RESPONSE_HEADERS),
        "body": json.dumps(body, separators=(",", ":")),
    }


def is_options_request(event: Mapping[str, Any] | None) -> bool:
    """Detect API Gateway v1 and v2 CORS preflight requests."""

    if not isinstance(event, Mapping):
        return False
    if str(event.get("httpMethod", "")).upper() == "OPTIONS":
        return True

    request_context = event.get("requestContext")
    if not isinstance(request_context, Mapping):
        return False
    http_context = request_context.get("http")
    return isinstance(http_context, Mapping) and str(
        http_context.get("method", "")
    ).upper() == "OPTIONS"


def parse_payload(event: Mapping[str, Any] | None) -> dict[str, Any]:
    """Parse either a direct Lambda payload or an API Gateway body."""

    if event is None:
        return {}
    if not isinstance(event, Mapping):
        raise RequestValidationError("Request must be a JSON object.")
    if "body" not in event:
        return dict(event)

    body = event.get("body")
    if body in (None, ""):
        return {}
    if isinstance(body, Mapping):
        return dict(body)
    if not isinstance(body, str):
        raise RequestValidationError("Request body must be a JSON object.")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RequestValidationError("Request body contains invalid JSON.") from exc

    if not isinstance(payload, Mapping):
        raise RequestValidationError("Request body must be a JSON object.")
    return dict(payload)


def validate_pagination(payload: Mapping[str, Any]) -> tuple[int, int]:
    """Validate and return ``page`` and ``page_size``."""

    page = payload.get("page", DEFAULT_PAGE)
    page_size = payload.get("page_size", DEFAULT_PAGE_SIZE)

    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise RequestValidationError("page must be a positive integer.")
    if (
        isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or not 1 <= page_size <= MAX_PAGE_SIZE
    ):
        raise RequestValidationError(
            f"page_size must be an integer between 1 and {MAX_PAGE_SIZE}."
        )
    return page, page_size


def resolve_regions(
    environment: Mapping[str, str] | None = None,
) -> tuple[ConfiguredRegion, ...]:
    """Resolve configured regions without hardcoding SSM parameter paths."""

    env = os.environ if environment is None else environment
    regions: list[ConfiguredRegion] = []

    for definition in REGION_DEFINITIONS:
        parameter_name = env.get(definition.parameter_environment_variable)
        if not parameter_name:
            continue

        schema = env.get(
            definition.schema_environment_variable,
            definition.default_schema,
        )
        if not _SQL_IDENTIFIER.fullmatch(schema):
            raise ConfigurationError("Database schema configuration is invalid.")

        regions.append(
            ConfiguredRegion(
                name=definition.name,
                parameter_name=parameter_name,
                schema=schema,
                rank=definition.rank,
            )
        )

    if not regions:
        raise ConfigurationError("No regional database is configured.")
    return tuple(regions)


def create_ssm_client() -> Any:
    """Create the AWS SSM client only when the Lambda is invoked."""

    import boto3

    region_name = os.environ.get("AWS_REGION") or os.environ.get(
        "AWS_DEFAULT_REGION", "us-east-1"
    )
    return boto3.client("ssm", region_name=region_name)


def _required_config_value(
    config: Mapping[str, Any], aliases: Sequence[str]
) -> Any:
    for alias in aliases:
        value = config.get(alias)
        if value not in (None, ""):
            return value
    raise ConfigurationError("Database configuration is incomplete.")


def load_database_config(parameter_name: str, ssm_client: Any) -> dict[str, Any]:
    """Read and validate PostgreSQL credentials stored as JSON in SSM."""

    try:
        response = ssm_client.get_parameter(
            Name=parameter_name,
            WithDecryption=True,
        )
        raw_value = response["Parameter"]["Value"]
        config = json.loads(raw_value)
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("Database configuration is malformed.") from exc

    if not isinstance(config, Mapping):
        raise ConfigurationError("Database configuration is malformed.")

    port_value = _required_config_value(config, ("PORT", "port"))
    try:
        port = int(port_value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError("Database configuration is malformed.") from exc
    if not 1 <= port <= 65535:
        raise ConfigurationError("Database configuration is malformed.")

    return {
        "host": str(_required_config_value(config, ("HOST", "host"))),
        "database": str(
            _required_config_value(
                config,
                ("DATABASE NAME", "DATABASE", "database", "dbname"),
            )
        ),
        "user": str(
            _required_config_value(config, ("USERNAME", "USER", "username", "user"))
        ),
        "password": str(
            _required_config_value(config, ("PASSWORD", "password"))
        ),
        "port": port,
    }


def open_database_connection(region: ConfiguredRegion, ssm_client: Any) -> Any:
    """Open a bounded, read-only PostgreSQL connection for one region."""

    import psycopg2

    config = load_database_config(region.parameter_name, ssm_client)
    connection = psycopg2.connect(
        **config,
        sslmode="require",
        connect_timeout=5,
        options="-c statement_timeout=10000",
    )
    try:
        connection.set_session(readonly=True, autocommit=True)
    except Exception:
        connection.close()
        raise
    return connection


def build_review_query(schema: str) -> str:
    """Build SQL using a previously validated schema identifier."""

    if not _SQL_IDENTIFIER.fullmatch(schema):
        raise ConfigurationError("Database schema configuration is invalid.")

    return f"""
        SELECT
            u.user_id,
            va.last_updated_at,
            COUNT(*) OVER () AS total_records
        FROM {schema}.users AS u
        INNER JOIN {schema}.volunteer_applications AS va
            ON u.user_id = va.user_id
        WHERE va.application_status = %s
        ORDER BY
            va.last_updated_at DESC NULLS LAST,
            u.user_id ASC
        LIMIT %s
    """


def normalize_timestamp(value: datetime | None) -> datetime | None:
    """Treat database timestamps as UTC and normalize aware timestamps."""

    if value is None:
        return None
    if not isinstance(value, datetime):
        raise ValueError("Database returned an invalid timestamp.")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def fetch_region_candidates(
    connection: Any,
    region: ConfiguredRegion,
    fetch_limit: int,
) -> tuple[list[ReviewCandidate], int]:
    """Fetch enough rows for global pagination plus the regional count."""

    cursor = connection.cursor()
    try:
        cursor.execute(
            build_review_query(region.schema),
            (REVIEW_STATUS, fetch_limit),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()

    if not rows:
        return [], 0

    candidates = [
        ReviewCandidate(
            user_id=str(row[0]),
            updated_time=normalize_timestamp(row[1]),
            region_rank=region.rank,
        )
        for row in rows
    ]
    return candidates, int(rows[0][2])


def _candidate_sort_key(candidate: ReviewCandidate) -> tuple[Any, ...]:
    if candidate.updated_time is None:
        return (1, 0.0, candidate.user_id, candidate.region_rank)
    return (
        0,
        -candidate.updated_time.timestamp(),
        candidate.user_id,
        candidate.region_rank,
    )


def query_regions(
    fetch_limit: int,
    regions: Sequence[ConfiguredRegion] | None = None,
    connection_factory: Callable[[ConfiguredRegion], Any] | None = None,
) -> tuple[list[ReviewCandidate], int]:
    """Read all configured regions and merge them into one ordered queue."""

    active_regions = tuple(regions) if regions is not None else resolve_regions()
    factory = connection_factory
    if factory is None:
        ssm_client = create_ssm_client()
        factory = lambda region: open_database_connection(region, ssm_client)

    candidates: list[ReviewCandidate] = []
    total_records = 0

    for region in active_regions:
        connection = None
        try:
            connection = factory(region)
            regional_candidates, regional_total = fetch_region_candidates(
                connection,
                region,
                fetch_limit,
            )
            candidates.extend(regional_candidates)
            total_records += regional_total
        finally:
            if connection is not None:
                connection.close()

    candidates.sort(key=_candidate_sort_key)
    return candidates, total_records


def format_timestamp(value: datetime | None) -> str | None:
    """Serialize a UTC timestamp using the API's ``Z`` suffix."""

    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def build_success_payload(
    page: int,
    page_size: int,
    candidates: Sequence[ReviewCandidate],
    total_records: int,
) -> dict[str, Any]:
    """Slice the globally ordered queue and build the response contract."""

    start = (page - 1) * page_size
    page_candidates = candidates[start : start + page_size]
    total_pages = (
        (total_records + page_size - 1) // page_size if total_records else 0
    )

    return {
        "data": [
            {
                "user_id": candidate.user_id,
                "updated_time": format_timestamp(candidate.updated_time),
                "volunteer_review": REVIEW_ACTION,
            }
            for candidate in page_candidates
        ],
        "pagination": {
            "current_page": page,
            "page_size": page_size,
            "total_records": total_records,
            "total_pages": total_pages,
        },
    }


def process_request(
    payload: Mapping[str, Any],
    regions: Sequence[ConfiguredRegion] | None = None,
    connection_factory: Callable[[ConfiguredRegion], Any] | None = None,
) -> dict[str, Any]:
    """Validate, query, globally paginate, and return a success payload."""

    page, page_size = validate_pagination(payload)
    candidates, total_records = query_regions(
        fetch_limit=page * page_size,
        regions=regions,
        connection_factory=connection_factory,
    )
    return build_success_payload(
        page=page,
        page_size=page_size,
        candidates=candidates,
        total_records=total_records,
    )


def lambda_handler(event: Mapping[str, Any] | None, context: Any) -> dict[str, Any]:
    """Handle a Steward Dashboard volunteer-review request."""

    del context

    try:
        if is_options_request(event):
            return build_response(200, {})
        payload = parse_payload(event)
        return build_response(200, process_request(payload))
    except RequestValidationError as exc:
        return build_response(400, {"error": str(exc)})
    except Exception as exc:
        LOGGER.error(
            "Volunteer review request failed (%s).",
            type(exc).__name__,
        )
        return build_response(
            500,
            {"error": "Unable to retrieve volunteer review requests."},
        )
