import pandas as pd
from organization_distance_service import (
    enrich_organizations_with_distance,
    sort_organizations_by_distance,
)
from location_utils import resolve_beneficiary_location, get_request_details
from geocoding_utils import geocode_address_cached

def get_beneficiary_coordinates(cursor, schema, request_id, beneficiary_id=None):
    """Resolve the beneficiary's location for a request."""

    request = get_request_details(cursor, schema, request_id)

    if request is None:
        return None

    return resolve_beneficiary_location(
        cursor,
        schema,
        request,
        beneficiary_id=beneficiary_id,
    )

def add_organization_distances(
    organizations,
    beneficiary_coordinates,
    geocoding_provider=None,
    sort_by_distance=False,
):
    enriched = enrich_organizations_with_distance(
        organizations,
        beneficiary_coordinates,
        geocoding_provider=geocoding_provider,
    )

    if sort_by_distance:
        return sort_organizations_by_distance(enriched)

    return enriched
    

def resolve_coordinates(location_result, geocoding_provider=None):
    """Convert a resolved beneficiary location into coordinates."""

    if not location_result:
        return None

    coordinates = location_result.get("coordinates")

    if coordinates is not None:
        return coordinates

    address = location_result.get("address")

    if not address:
        return None

    return geocode_address_cached(
        address,
        provider=geocoding_provider,
    )

def enrich_request_organizations(
    cursor,
    schema,
    request_id,
    organizations,
    beneficiary_id=None,
    geocoding_provider=None,
):
    """Calculate organization distances for a beneficiary request."""

    location_result = get_beneficiary_coordinates(
        cursor,
        schema,
        request_id,
        beneficiary_id=beneficiary_id,
    )

    beneficiary_coordinates = resolve_coordinates(
        location_result,
        geocoding_provider=geocoding_provider,
    )

    return add_organization_distances(
        organizations,
        beneficiary_coordinates,
        geocoding_provider=geocoding_provider,
    )

def enrich_organization_dataframe(
    organizations_df,
    beneficiary_coordinates,
    geocoding_provider=None,
):
    """Add distances to a DataFrame without changing the original."""

    if not isinstance(organizations_df, pd.DataFrame):
        raise TypeError("organizations_df must be a pandas DataFrame")

    organizations = organizations_df.to_dict(orient="records")

    enriched = add_organization_distances(
        organizations,
        beneficiary_coordinates,
        geocoding_provider=geocoding_provider,
    )

    return pd.DataFrame(enriched, columns=[
        *organizations_df.columns,
        "distance",
        "distance_unit",
        "distance_method",
        "distance_status",
    ])

ORGANIZATION_OUTPUT_COLUMNS = [
    "name",
    "location",
    "contact",
    "email",
    "web_url",
    "mission",
    "source",
    "db_or_ai",
]

DISTANCE_OUTPUT_COLUMNS = [
    "distance",
    "distance_unit",
    "distance_method",
    "distance_status",
]

def merge_organizations_with_distances(
    db_organizations,
    genai_organizations,
    beneficiary_coordinates,
    geocoding_provider=None,
):
    """Merge organizations and add distances without modifying inputs."""

    db = db_organizations.copy().rename(columns={
        "org_name": "name",
        "city_name": "location",
        "phone": "contact",
    })

    ai = genai_organizations.copy().rename(columns={
        "organization_name": "name",
    })

    db["db_or_ai"] = "db"
    ai["db_or_ai"] = "ai"

    # Calculate distances before removing address fields.
    combined = pd.concat([db, ai], ignore_index=True)

    # Restore city_name for database address construction.
    if "city_name" not in combined.columns:
        combined["city_name"] = None

    db_mask = combined["db_or_ai"] == "db"
    combined.loc[db_mask, "city_name"] = combined.loc[db_mask, "location"]

    enriched = enrich_organization_dataframe(
        combined,
        beneficiary_coordinates,
        geocoding_provider=geocoding_provider,
    )

    output_columns = ORGANIZATION_OUTPUT_COLUMNS + DISTANCE_OUTPUT_COLUMNS

    extra_columns = [
    column
    for column in enriched.columns
    if column not in output_columns
]

    return enriched.reindex(
    columns=output_columns + extra_columns
)
    

def aggregate_request_organizations_with_distances(
    cursor,
    schema,
    request_id,
    db_organizations,
    genai_organizations,
    beneficiary_id=None,
    geocoding_provider=None,
    sort_by_distance=False,
):
    """
    Combine organizations and calculate beneficiary-to-organization
    distances. Optionally sort nearest first.
    """
    try:
        location_result = get_beneficiary_coordinates(
            cursor,
            schema,
            request_id,
            beneficiary_id=beneficiary_id,
        )
        beneficiary_coordinates = resolve_coordinates(
            location_result,
            geocoding_provider=geocoding_provider,
        )
    except Exception:
        beneficiary_coordinates = None

    result = merge_organizations_with_distances(
        db_organizations,
        genai_organizations,
        beneficiary_coordinates,
        geocoding_provider=geocoding_provider,
    )

    if sort_by_distance:
        sorted_records = sort_organizations_by_distance(
            result.to_dict(orient="records")
        )
        return pd.DataFrame(sorted_records, columns=result.columns)

    return result