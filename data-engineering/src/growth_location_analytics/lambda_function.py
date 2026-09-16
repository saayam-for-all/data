"""Lambda entry point for Growth & Location Analytics."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

if __package__:
    from .date_ranges import (
        ALL_BUCKETS,
        FIXED_BUCKETS,
        AnalyticsDateRanges,
        DateRangeError,
        DateWindow,
        resolve_date_ranges,
    )
    from .growth import calculate_organization_growth
    from .loader import LocalDataTables, load_local_data
    from .location import calculate_country_distribution
else:
    # The repository's Lambda workflow copies this directory's contents to the
    # ZIP root, where AWS imports ``lambda_function`` as a top-level module.
    from date_ranges import (  # type: ignore[no-redef]
        ALL_BUCKETS,
        FIXED_BUCKETS,
        AnalyticsDateRanges,
        DateRangeError,
        DateWindow,
        resolve_date_ranges,
    )
    from growth import calculate_organization_growth  # type: ignore[no-redef]
    from loader import LocalDataTables, load_local_data  # type: ignore[no-redef]
    from location import calculate_country_distribution  # type: ignore[no-redef]


LOGGER = logging.getLogger(__name__)

_DATE_FIELDS = (
    "start_date",
    "end_date",
    "location_start_date",
    "location_end_date",
)
_JSON_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}


class RequestBodyError(ValueError):
    """Raised when a Lambda event does not contain a supported JSON object."""


def lambda_handler(event: object, context: object) -> dict[str, Any]:
    """Return all fixed analytics buckets and independently optional Custom data.

    Two event forms are supported: a direct JSON-object event and an API Gateway
    proxy event whose ``body`` is a JSON string. A missing or null proxy body is
    an empty request. The Lambda context is accepted for the AWS entry-point
    contract but is not used.
    """

    del context
    try:
        request = _parse_request(event)
        reference_time = _current_utc_time()
        ranges = resolve_date_ranges(
            **{field: request.get(field) for field in _DATE_FIELDS},
            reference_time=reference_time,
        )

        # Request validation deliberately precedes local file access.
        tables = load_local_data()
        payload = assemble_analytics(tables, ranges)
        return _response(200, payload)
    except (RequestBodyError, DateRangeError) as exc:
        return _response(400, {"error": str(exc)})
    except Exception:
        # Data/configuration and calculation failures are server failures. Keep
        # diagnostic detail in logs without exposing rows, paths, or tracebacks
        # to the caller.
        LOGGER.exception("Growth & Location Analytics request failed")
        return _response(500, {"error": "Internal server error"})


def assemble_analytics(
    tables: LocalDataTables,
    ranges: AnalyticsDateRanges,
) -> dict[str, Any]:
    """Assemble the exact five-bucket analytics payload from prepared inputs."""

    result: dict[str, Any] = {}
    for bucket in FIXED_BUCKETS:
        window = ranges.fixed[bucket]
        result[bucket] = _assemble_bucket(tables, bucket, window, window)

    result["Custom"] = _assemble_bucket(
        tables,
        "Custom",
        ranges.growth_custom,
        ranges.location_custom,
    )

    # Guard the public contract if the canonical bucket constants ever change.
    if tuple(result) != ALL_BUCKETS:
        raise RuntimeError("Unexpected analytics bucket configuration")
    return result


def _assemble_bucket(
    tables: LocalDataTables,
    bucket: str,
    growth_window: DateWindow | None,
    location_window: DateWindow | None,
) -> dict[str, Any]:
    """Build one bucket without filtering or mutating the shared source tables."""

    return {
        "growth_trend": calculate_organization_growth(
            tables.organizations,
            bucket,
            growth_window,
        ),
        "organizations_by_location": calculate_country_distribution(
            tables.organizations,
            tables.states,
            tables.countries,
            location_window,
        ),
    }


def _parse_request(event: object) -> dict[str, Any]:
    """Extract a request object from direct and API Gateway Lambda events."""

    if not isinstance(event, Mapping):
        raise RequestBodyError("Request event must be a JSON object")

    if "body" not in event:
        return dict(event)

    raw_body = event["body"]
    if raw_body is None:
        return {}
    if not isinstance(raw_body, str):
        raise RequestBodyError("Request body must be a JSON object encoded as a string")

    try:
        decoded = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise RequestBodyError("Request body must contain valid JSON") from exc

    if not isinstance(decoded, dict):
        raise RequestBodyError("Request body must decode to a JSON object")
    return decoded


def _response(status_code: int, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Build a JSON-safe API Gateway proxy response without double encoding."""

    return {
        "statusCode": status_code,
        "headers": dict(_JSON_HEADERS),
        "body": json.dumps(payload, allow_nan=False),
    }


def _current_utc_time() -> datetime:
    """Read the invocation reference time once; isolated for deterministic tests."""

    return datetime.now(timezone.utc)


def _local_sample_events() -> tuple[tuple[str, dict[str, str]], ...]:
    """Build reproducible sample requests from dates present in the local CSVs.

    The local runner derives its dates from the configured organizations data so
    the Custom examples remain meaningful when the local fixture changes. An
    empty, header-only organizations file uses a stable fallback date; every
    response is still produced by :func:`lambda_handler` and the normal loader.
    """

    organizations = load_local_data().organizations
    if organizations.empty:
        first_date = last_date = "1970-01-01"
    else:
        active_dates = organizations["created_at"].dt.date.sort_values()
        first_date = active_dates.iloc[0].isoformat()
        last_date = active_dates.iloc[-1].isoformat()

    return (
        ("No body / {}", {}),
        (
            "Growth Custom range only",
            {"start_date": first_date, "end_date": last_date},
        ),
        (
            "Location Custom range only",
            {
                "location_start_date": first_date,
                "location_end_date": last_date,
            },
        ),
        (
            "Both independent Custom ranges",
            {
                "start_date": first_date,
                "end_date": first_date,
                "location_start_date": last_date,
                "location_end_date": last_date,
            },
        ),
    )


def _run_local_samples() -> None:
    """Invoke and print the real handler for the four issue-required examples."""

    for label, event in _local_sample_events():
        response = lambda_handler(event, None)
        print(f"=== {label} ===")
        print("Request:")
        print(json.dumps(event, indent=2))
        print("Response:")
        print(json.dumps(response, indent=2))


if __name__ == "__main__":
    _run_local_samples()
