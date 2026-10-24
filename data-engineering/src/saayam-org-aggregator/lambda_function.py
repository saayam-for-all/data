import json

from distance import (
    GeocodeSession,
    STATUS_ERROR,
    add_distances,
    build_geocoder,
    get_cache,
    resolve_beneficiary_point,
    sort_by_distance,
    without_distance,
)
from helpers import (
    get_req_info,
    get_ai_orgs,
    get_orgs_from_db,
    merge_organizations,
    get_beneficiary_location,
    get_beneficiary_location_candidates,
    load_city_coordinates,
)

# Built once per container so the cities lookup and coordinate cache are reused
# across warm invocations. Provider is chosen by GEOCODER_PROVIDER.
_GEOCODER = None


def _get_geocoder():
    global _GEOCODER
    if _GEOCODER is None:
        _GEOCODER = build_geocoder({"cities_loader": load_city_coordinates})
    return _GEOCODER


def add_organization_distances(organizations, request_id, beneficiary_id, sort_by=None):
    """Attach distance fields to every organization (issue #433).

    Distance is measured from the beneficiary/request location only. Any
    failure here returns the organizations with distance = null instead of
    failing the request.
    """
    try:
        session = GeocodeSession(_get_geocoder())
        candidates = get_beneficiary_location_candidates(request_id, beneficiary_id)
        beneficiary_point, beneficiary_status = resolve_beneficiary_point(
            candidates, session
        )

        print(
            "distance origin:",
            beneficiary_point.source if beneficiary_point else None,
            beneficiary_status,
        )

        organizations = add_distances(
            organizations, beneficiary_point, beneficiary_status, session
        )

        cache = get_cache()
        print(
            "geocode cache hits/misses:", cache.hits, cache.misses,
            "external calls:", session.external_calls,
        )
    except Exception as e:  # noqa: BLE001
        print("distance calculation failed:", str(e))
        organizations = without_distance(organizations, STATUS_ERROR)

    if sort_by == "distance":
        organizations = sort_by_distance(organizations)

    return organizations


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

        beneficiary_location, beneficiary_city = get_beneficiary_location(
            beneficiary_id
        )

        print(
            "beneficiary location, city:",
            beneficiary_location,
            beneficiary_city,
        )

        # Search scope for GenAI only. Distance never uses this default;
        # it comes from add_organization_distances below.
        if not beneficiary_location:
            beneficiary_location = "United States"

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

        db_organizations = get_orgs_from_db(
            beneficiary_city,
            category,
        )

        # A GenAI failure must not hide the database organizations.
        try:
            genai_organizations = get_ai_orgs(
                subject,
                description,
                beneficiary_location,
                category,
            )
        except Exception as e:  # noqa: BLE001
            print("GenAI organizations unavailable, continuing with DB results:", str(e))
            genai_organizations = None

        combined_list = merge_organizations(
            db_organizations,
            genai_organizations,
        )

        organizations = combined_list.to_dict(orient="records")

        organizations = add_organization_distances(
            organizations,
            request_id,
            beneficiary_id,
            sort_by=body.get("sort_by"),
        )

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
                {
                    "error": (
                        f"Invalid JSON in request body: {str(e)}"
                    )
                }
            ),
        }

    except Exception as e:
        print("saayam-org-aggregator error:", str(e))

        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "error": (
                        f"Internal server error: {str(e)}"
                    )
                }
            ),
        }
