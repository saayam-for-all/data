"""Existing saayam-org-aggregator API, enriched with beneficiary-based distance."""

import json
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal

from distance import GeocodeService, add_distances
from helpers import (
    connect_database, get_ai_orgs, get_orgs_from_db, merge_organizations,
    get_request_context, resolve_beneficiary_location,
)


LOGGER = logging.getLogger(__name__)


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Decimal):
        return float(value) if value.is_finite() else None
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return str(value)


def _response(code, body):
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
        "body": json.dumps(_json_safe(body), allow_nan=False),
    }


def _parse_event(event):
    if not isinstance(event, dict):
        raise ValueError("Request must be a JSON object")
    body = event.get("body", event)
    if body is None:
        body = event
    if isinstance(body, str):
        body = json.loads(body)
    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object")
    return body


def lambda_handler(event, context):
    try:
        body = _parse_event(event)
    except (ValueError, json.JSONDecodeError) as exc:
        return _response(400, {"error": str(exc)})

    request_id = body.get("request_id") or body.get("req_id")
    if request_id is None and (not body.get("location") or not body.get("category")):
        return _response(400, {"error": "request_id or location and category are required"})

    connection = None
    try:
        connection = connect_database()
        geocoder = GeocodeService()
        beneficiary_id = body.get("beneficiary_id")
        if request_id is not None:
            context = get_request_context(connection, request_id, beneficiary_id)
            if context is None:
                return _response(404, {"error": "Request or beneficiary not found"})
            beneficiary_id = context["beneficiary_id"]
            location = context["location"]
            category = context["category"]
            subject = context["subject"]
            description = context["description"]
        else:
            location = body["location"]
            category = body["category"]
            subject = body.get("subject")
            description = body.get("description")
        if not category:
            return _response(422, {"error": "Request category is unavailable"})
        try:
            beneficiary = resolve_beneficiary_location(
                connection, request_id, beneficiary_id, geocoder, return_status=True,
            )
        except Exception:
            LOGGER.exception("Beneficiary location lookup failed")
            beneficiary = {"coordinates": None, "status": "error"}

        with ThreadPoolExecutor(max_workers=2) as executor:
            db_future = executor.submit(get_orgs_from_db, connection, location, category)
            ai_future = executor.submit(
                get_ai_orgs, subject, description, location, category,
            )
            try:
                db_rows = db_future.result()
            except Exception:
                LOGGER.exception("Database organization lookup failed")
                db_rows = []
            try:
                ai_rows = ai_future.result()
            except Exception:
                LOGGER.exception("GenAI organization lookup failed")
                ai_rows = []

        organizations = merge_organizations(db_rows, ai_rows)
        organizations = add_distances(organizations, beneficiary, geocoder)
        if body.get("sort_by") == "distance":
            organizations.sort(key=lambda row: (
                row["distance"] is None,
                row["distance"] if row["distance"] is not None else float("inf"),
            ))
        return _response(200, organizations)
    except Exception:
        LOGGER.exception("Organization aggregation failed")
        return _response(500, {"error": "Unable to retrieve organizations"})
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                LOGGER.warning("Could not close organization database connection")
