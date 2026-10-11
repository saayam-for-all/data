"""Injectable aggregator/consumer contract; importing this module opens no live clients."""

import json
import logging
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from numbers import Real

from address_geocoding import CoordinateCache, GeocodingProvider
from beneficiary_location import LocationRecordSource, resolve_beneficiary_location
from organization_addresses import OrganizationAddressAssembler, from_genai
from organization_distance import distance_fields, enrich_organizations, resolve_distance_origin

logger = logging.getLogger(__name__)


class OrganizationSourcesUnavailable(Exception):
    """Neither source could be retrieved; this is distinct from valid empty results."""


ORG_COLUMNS = (
    "name", "organization_type", "collaborator", "location", "size", "rating",
    "contact", "email", "web_url", "mission", "source",
)
DB_RENAME = {
    "org_name": "name", "org_type": "organization_type", "is_collaborator": "collaborator",
    "org_rating": "rating", "org_size": "size", "phone": "contact", "city_name": "location",
}
AI_RENAME = {
    "organization_name": "name", "org_type": "organization_type", "is_collaborator": "collaborator",
}


@dataclass
class AggregatorDependencies:
    """Explicit local composition; sources accept a request dict and return rows/frames.

    The AI source may also return the helper's statusCode/body.organizations envelope.
    No default provider, live record adapter, or persistent cache is selected here.
    Classification/coordinate callbacks receive raw OrganizationAddress records.
    Optional request_info_reader must verify request/beneficiary association and
    return trusted search details for IDs-only handler inputs.
    """

    records: LocationRecordSource
    provider: GeocodingProvider
    cache: CoordinateCache
    db_source: Callable
    ai_source: Callable
    addresses: OrganizationAddressAssembler = field(default_factory=OrganizationAddressAssembler)
    resolver: Callable = resolve_beneficiary_location
    coordinate_reader: Callable | None = None
    online_reader: Callable | None = None
    request_info_reader: Callable[[str, str], Mapping] | None = None


def _rows(value, *, ai=False):
    """Decode source rows without importing pandas or the live helper."""
    if ai and isinstance(value, Mapping):
        if value.get("statusCode") != 200:
            raise ValueError("AI source unavailable")
        body = value.get("body", {})
        body = json.loads(body) if isinstance(body, str) else body
        value = body["organizations"]
    if value is None:
        return []
    if hasattr(value, "to_dict"):
        # Nullable pandas columns need object dtype before replacing NA with None.
        if hasattr(value, "astype") and hasattr(value, "notna"):
            value = value.astype(object).where(value.notna(), None)
        value = value.to_dict(orient="records")
    if isinstance(value, (str, bytes, Mapping)):
        raise ValueError("Expected organization records")
    rows = []
    for row in value:
        if isinstance(row, Mapping):
            rows.append(row)
        else:
            logger.warning("Skipping malformed organization record")
    return rows


def _normalize(record, source):
    """Preserve fields, using raw aliases only when the consumer field is absent."""
    result = dict(record)
    for raw, final in (DB_RENAME if source == "db" else AI_RENAME).items():
        if final not in result and raw in result:
            result[final] = result[raw]
    if source == "ai":
        result.setdefault("collaborator", False)
    for column in ORG_COLUMNS:
        result.setdefault(column, source if column == "source" else None)
    return result


def aggregate_organizations(body: dict, dependencies: AggregatorDependencies) -> list[dict]:
    """Run tasks 1–3 offline; source and organization failures retain available records."""
    origin = resolve_distance_origin(
        body.get("request_id"), body.get("beneficiary_id"), dependencies.records,
        dependencies.provider, dependencies.cache, resolver=dependencies.resolver,
    )
    output = []
    successful_sources = 0
    for source, fetch in (("db", dependencies.db_source), ("ai", dependencies.ai_source)):
        try:
            rows = _rows(fetch(dict(body)), ai=source == "ai")
        except Exception:
            # Independent sources: especially preserve DB records on GenAI failures.
            logger.warning("Organization source %s unavailable", source)
            continue
        successful_sources += 1
        for row in rows:
            try:
                organization = (
                    dependencies.addresses.from_database(row) if source == "db" else from_genai(row)
                )
                if dependencies.online_reader is not None:
                    organization = replace(
                        organization, online_only=dependencies.online_reader(organization)
                    )
                enriched = enrich_organizations(
                    [organization], origin, dependencies.provider, dependencies.cache,
                    coordinate_reader=dependencies.coordinate_reader,
                )[0]
            except Exception:
                enriched = dict(row)
                enriched.update(distance_fields("error"))
            output.append(_normalize(enriched, source))
    if not successful_sources:
        raise OrganizationSourcesUnavailable()
    return output


def json_safe(value):
    """Normalize numeric values and dates; leave unsupported values for field isolation."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (Real, Decimal)) and not isinstance(value, bool):
        if isinstance(value, int):
            return value
        try:
            number = float(value)
        except (ValueError, OverflowError):
            return None
        return number if math.isfinite(number) else None
    return value


def _json_record(record: dict) -> dict:
    """Keep serializable fields when one field cannot be represented in JSON."""
    result = {}
    for key, value in record.items():
        try:
            normalized = json_safe(value)
            json.dumps(normalized, allow_nan=False)
        except (TypeError, ValueError, OverflowError, RecursionError):
            logger.warning("Organization field unavailable for JSON serialization")
            normalized = None
        result[key] = normalized
    return result


def _request_identity(value: object) -> str:
    """Normalize offline IDs once for both trusted lookup and location resolution."""
    if isinstance(value, str):
        identity = value.strip()
    elif type(value) is int:
        identity = str(value)
    else:
        identity = ""
    if not identity:
        raise ValueError("request_id and beneficiary_id must be nonblank strings or integers")
    return identity


def offline_response(event: dict, dependencies: AggregatorDependencies) -> dict:
    """Serialize an API Gateway or direct request using the helper's list response contract."""
    try:
        if not isinstance(event, dict):
            raise ValueError("Request must be an object")
        raw = event.get("body")
        body = json.loads(raw) if isinstance(raw, str) else (raw if raw is not None else event)
        if not isinstance(body, dict):
            raise ValueError("Request body must be an object")
        body = dict(body)
        for key in ("request_id", "beneficiary_id"):
            body[key] = _request_identity(body.get(key))
        if dependencies.request_info_reader is not None:
            try:
                info = dependencies.request_info_reader(body["request_id"], body["beneficiary_id"])
            except (ValueError, TypeError):
                raise ValueError("Request details or association unavailable") from None
            if not isinstance(info, Mapping):
                raise ValueError("Request details unavailable")
            # Trusted request details take precedence over caller-supplied search text.
            body.update({key: info.get(key) for key in ("category", "subject", "description")})
        if not body.get("category"):
            raise ValueError("category is required")
    except (ValueError, TypeError) as error:
        return {"statusCode": 400, "body": json.dumps({"error": str(error)})}
    except Exception:
        return {"statusCode": 500, "body": json.dumps({"error": "Request details unavailable"})}
    try:
        records = aggregate_organizations(body, dependencies)
    except OrganizationSourcesUnavailable:
        return {
            "statusCode": 502,
            "body": json.dumps({"error": "Organization sources unavailable"}),
        }
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
        "body": json.dumps([_json_record(record) for record in records], allow_nan=False),
    }
