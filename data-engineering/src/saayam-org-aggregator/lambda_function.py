"""saayam-org-aggregator Lambda — Request Details → Organizations (#433).

Fetches DB + GenAI organizations for a request, then attaches beneficiary-based
straight-line distance fields for the frontend Distance column.
"""

from __future__ import annotations

import json
import logging

import pandas as pd

from helpers import (
    add_organization_distances,
    finalize_organization_records,
    get_ai_orgs,
    get_beneficiary_location,
    get_orgs_from_db,
    get_req_info,
    merge_organizations,
    resolve_beneficiary_coordinates,
    sort_organizations_by_distance,
)

logger = logging.getLogger(__name__)


def lambda_handler(event, context):
    try:
        raw_body = event.get("body")
        body = json.loads(raw_body) if isinstance(raw_body, str) else event

        request_id = body.get("request_id")
        beneficiary_id = body.get("beneficiary_id")

        print("request_id:", request_id)
        print("beneficiary_id:", beneficiary_id)

        if not request_id or not beneficiary_id:
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {
                        "error": (
                            "Missing required fields: "
                            "request_id, beneficiary_id"
                        )
                    }
                ),
            }

        # Search location strings for DB city filter / GenAI prompt only.
        # Distance never uses a default country fallback.
        search_location, beneficiary_city = get_beneficiary_location(
            beneficiary_id
        )

        print(
            "beneficiary location, city:",
            search_location,
            beneficiary_city,
        )

        if not search_location:
            search_location = "United States"

        if not beneficiary_city:
            beneficiary_city = ""

        req_info = get_req_info(request_id, beneficiary_id)

        print("request info:", req_info)

        subject = req_info.get("subject", "")
        description = req_info.get("description", "")
        category = req_info.get("category", "")

        if not category:
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {
                        "error": (
                            f"Request {request_id} "
                            "has no category assigned"
                        )
                    }
                ),
            }

        try:
            db_organizations = get_orgs_from_db(beneficiary_city, category)
        except Exception:
            logger.exception("Database organization lookup failed")
            db_organizations = pd.DataFrame()

        try:
            genai_organizations = get_ai_orgs(
                subject,
                description,
                search_location,
                category,
            )
        except Exception:
            logger.exception("GenAI organization lookup failed")
            genai_organizations = pd.DataFrame()

        combined_list = merge_organizations(
            db_organizations,
            genai_organizations,
        )

        try:
            beneficiary_coords = resolve_beneficiary_coordinates(
                request_id, beneficiary_id
            )
            combined_list = add_organization_distances(
                combined_list, beneficiary_coords
            )
            combined_list = sort_organizations_by_distance(combined_list)
        except Exception:
            logger.exception("Unable to add organization distances")
            combined_list["distance"] = None
            combined_list["distance_unit"] = "miles"
            combined_list["distance_method"] = "straight_line"
            combined_list["distance_status"] = "error"

        combined_list = finalize_organization_records(combined_list)
        organizations = combined_list.to_dict(orient="records")

        print("organization count:", len(organizations))

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(organizations),
        }

    except json.JSONDecodeError as e:
        return {
            "statusCode": 400,
            "body": json.dumps(
                {"error": f"Invalid JSON in request body: {str(e)}"}
            ),
        }

    except Exception as e:
        print("saayam-org-aggregator error:", str(e))

        return {
            "statusCode": 500,
            "body": json.dumps(
                {"error": f"Internal server error: {str(e)}"}
            ),
        }
