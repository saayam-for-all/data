"""AWS Lambda API for the Steward Dashboard volunteer review queue.

The handler reads pending volunteer applications from the Virginia and Ireland
databases, merges the regional results, and returns one globally ordered page.
Database credentials remain in AWS Systems Manager Parameter Store; the
parameter names are supplied through environment variables at deployment time.
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
MAX_RESULT_WINDOW = 1_000
REVIEW_STATUS = "IN_REVIEW"
VOLUNTEER_REVIEW_ACTION = "Review"
CONNECT_TIMEOUT_SECONDS = 5
STATEMENT_TIMEOUT_MILLISECONDS = 10_000

RESPONSE_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}

_SCHEMA_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class RequestValidationError(ValueError):
    """Raised when an incoming request does not satisfy the API contract."""


class ConfigurationError(RuntimeError):
    """Raised when required runtime configuration is missing or malformed."""


@dataclass(frozen=True)
class RegionConfig:
    """Deployment configuration for one regional database."""

    name: str
    schema: str
    parameter_environment_variable: str
    rank: int


@dataclass(frozen=True)
class ReviewCandidate:
    """Internal representation of one pending volunteer application."""

    user_id: str
    updated_time: datetime | None
    region_rank: int


REGIONS = (
    RegionConfig(
        name="Virginia",
        schema="virginia_dev_saayam_rdbms",
        parameter_environment_variable="VIRGINIA_DB_SSM_PARAMETER",
        rank=0,
    ),
    RegionConfig(
        name="Ireland",
        schema="ireland_dev_saayam_rdbms",
        parameter_environment_variable="IRELAND_DB_SSM_PARAMETER",
        rank=1,
    ),
)


def build_response(status_code: int, body: Mapping[str, Any]) -> dict[str, Any]:
    """Build an API Gateway-compatible JSON response."""

    return {
        "statusCode": status_code,
        "headers": dict(RESPONSE_HEADERS),
        "body": json.dumps(body, separators=(",", ":")),
    }


def parse_event_body(event: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return the request payload from a direct or API Gateway invocation."""

    if event is None:
        return {}
    if not isinstance(event, Mapping):
        raise RequestValidationError("Request must be a JSON object.")

    if "body" not in event:
        return dict(event)

    body = event.get("body")
    if body is None or body == "":
        return {}
    if isinstance(body, Mapping):
        return dict(body)
    if not isinstance(body, str):
        raise RequestValidationError("Request body must be a JSON object.")

    try:
        parsed_body = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RequestValidationError("Request body contains invalid JSON.") from exc

    if not isinstance(parsed_body, Mapping):
        raise RequestValidationError("Request body must be a JSON object.")
    return dict(parsed_body)


def is_options_request(event: Mapping[str, Any] | None) -> bool:
    """Return whether an API Gateway v1 or v2 event is a CORS preflight."""

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


def validate_pagination(payload: Mapping[str, Any]) -> tuple[int, int]:
    """Validate and return the requested page and page size."""

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
    if page * page_size > MAX_RESULT_WINDOW:
        raise RequestValidationError(
            f"page multiplied by page_size must not exceed {MAX_RESULT_WINDOW}."
        )

    return page, page_size


def create_ssm_client() -> Any:
    """Create an SSM client without importing the AWS SDK at module import."""

    import boto3  # Imported lazily for local, dependency-free unit tests.

    return boto3.client("ssm")


def _read_required_value(
    config: Mapping[str, Any], aliases: Sequence[str]
) -> Any:
    """Read one required database setting using known SSM key aliases."""

    for alias in aliases:
        value = config.get(alias)
        if value is not None and value != "":
            return value
    raise ConfigurationError("Database configuration is incomplete.")


def get_database_config(
    region: RegionConfig, ssm_client: Any | None = None
) -> dict[str, Any]:
    """Load and validate one region's database configuration from SSM."""

    parameter_name = os.environ.get(region.parameter_environment_variable)
    if not parameter_name:
        raise ConfigurationError("Required database configuration is missing.")

    client = ssm_client if ssm_client is not None else create_ssm_client()
    try:
        response = client.get_parameter(
            Name=parameter_name,
            WithDecryption=True,
        )
        raw_config = response["Parameter"]["Value"]
        parsed_config = json.loads(raw_config)
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("Database configuration is malformed.") from exc

    if not isinstance(parsed_config, Mapping):
        raise ConfigurationError("Database configuration is malformed.")

    host = _read_required_value(parsed_config, ("HOST", "host"))
    port_value = _read_required_value(parsed_config, ("PORT", "port"))
    database = _read_required_value(
        parsed_config,
        ("DATABASE NAME", "DATABASE", "DBNAME", "database", "dbname"),
    )
    user = _read_required_value(parsed_config, ("USERNAME", "USER", "username", "user"))
    password = _read_required_value(parsed_config, ("PASSWORD", "password"))

    try:
        port = int(port_value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError("Database configuration is malformed.") from exc
    if not 1 <= port <= 65_535:
        raise ConfigurationError("Database configuration is malformed.")

    return {
        "host": str(host),
        "port": port,
        "dbname": str(database),
        "user": str(user),
        "password": str(password),
    }


def open_database_connection(
    region: RegionConfig, ssm_client: Any | None = None
) -> Any:
    """Open a bounded, read-only PostgreSQL connection for one region."""

    database_config = get_database_config(region, ssm_client)

    import psycopg2  # Imported lazily for local, dependency-free unit tests.

    connection = psycopg2.connect(
        **database_config,
        sslmode="require",
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
        options=f"-c statement_timeout={STATEMENT_TIMEOUT_MILLISECONDS}",
    )
    try:
        configure_database_connection(connection)
    except Exception:
        connection.close()
        raise
    return connection


def configure_database_connection(connection: Any) -> None:
    """Make an opened PostgreSQL connection read-only and autocommitting."""

    connection.set_session(readonly=True, autocommit=True)


def build_review_query(schema: str) -> str:
    """Build the review-queue query for one validated schema name."""

    if not _SCHEMA_NAME_PATTERN.fullmatch(schema):
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


def fetch_region_candidates(
    connection: Any,
    region: RegionConfig,
    fetch_limit: int,
) -> tuple[list[ReviewCandidate], int]:
    """Fetch a bounded candidate window and regional total from PostgreSQL."""

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

    regional_total = int(rows[0][2])
    candidates = [
        ReviewCandidate(
            user_id=str(row[0]),
            updated_time=normalize_datetime(row[1]),
            region_rank=region.rank,
        )
        for row in rows
    ]
    return candidates, regional_total


def normalize_datetime(value: datetime | None) -> datetime | None:
    """Normalize a database timestamp to an aware UTC datetime."""

    if value is None:
        return None
    if not isinstance(value, datetime):
        raise ValueError("Database returned an invalid timestamp.")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _candidate_sort_key(candidate: ReviewCandidate) -> tuple[Any, ...]:
    """Return the deterministic global ordering key for a candidate."""

    if candidate.updated_time is None:
        return (1, 0.0, candidate.user_id, candidate.region_rank)
    return (
        0,
        -candidate.updated_time.timestamp(),
        candidate.user_id,
        candidate.region_rank,
    )


def format_timestamp(value: datetime | None) -> str | None:
    """Serialize a normalized timestamp using the API's UTC-Z format."""

    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def query_regions(
    fetch_limit: int,
    connection_factory: Callable[[RegionConfig], Any] | None = None,
) -> tuple[list[ReviewCandidate], int]:
    """Query every configured region and return merged candidates and total."""

    factory = connection_factory
    if factory is None:
        ssm_client = create_ssm_client()
        factory = lambda region: open_database_connection(region, ssm_client)

    combined_candidates: list[ReviewCandidate] = []
    total_records = 0

    for region in REGIONS:
        connection = None
        try:
            connection = factory(region)
            regional_candidates, regional_total = fetch_region_candidates(
                connection,
                region,
                fetch_limit,
            )
            combined_candidates.extend(regional_candidates)
            total_records += regional_total
        finally:
            if connection is not None:
                connection.close()

    combined_candidates.sort(key=_candidate_sort_key)
    return combined_candidates, total_records


def build_success_payload(
    page: int,
    page_size: int,
    candidates: Sequence[ReviewCandidate],
    total_records: int,
) -> dict[str, Any]:
    """Build the paginated response body for globally sorted candidates."""

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
                "volunteer_review": VOLUNTEER_REVIEW_ACTION,
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
    connection_factory: Callable[[RegionConfig], Any] | None = None,
) -> dict[str, Any]:
    """Validate, query, globally paginate, and build a successful payload."""

    page, page_size = validate_pagination(payload)
    fetch_limit = page * page_size
    candidates, total_records = query_regions(fetch_limit, connection_factory)
    return build_success_payload(
        page=page,
        page_size=page_size,
        candidates=candidates,
        total_records=total_records,
    )


def lambda_handler(event: Mapping[str, Any] | None, context: Any) -> dict[str, Any]:
    """Handle a Steward Dashboard volunteer-review API request."""

    del context  # The handler is deterministic and does not require Lambda context.

    try:
        if is_options_request(event):
            return build_response(200, {})
        payload = parse_event_body(event)
        response_payload = process_request(payload)
        return build_response(200, response_payload)
    except RequestValidationError as exc:
        return build_response(400, {"error": str(exc)})
    except Exception as exc:  # The public response must not expose internals.
        LOGGER.error(
            "Volunteer review request failed (%s).",
            type(exc).__name__,
        )
        return build_response(
            500,
            {"error": "Unable to retrieve volunteer review requests."},
        )
