from distance_utils import build_distance_result
from geocoding_utils import (
    build_organization_address,
    geocode_address_cached,
)


def enrich_organizations_with_distance(
    organizations,
    beneficiary_coordinates,
    geocoding_provider=None,
):
    """
    Add beneficiary-to-organization distance information.

    Does not modify the original organization records.
    Geocoding is optional and requires an approved provider.
    """
    results = []

    for organization in organizations:
        enriched = organization.copy()

        address = build_organization_address(organization)

        organization_coordinates = geocode_address_cached(
            address,
            provider=geocoding_provider,
        )

        distance_result = build_distance_result(
            beneficiary_coordinates,
            organization_coordinates,
        )

        enriched.update(distance_result)
        results.append(enriched)

    return results

def sort_organizations_by_distance(organizations):
    """
    Sort nearest to farthest.
    Organizations without a valid distance appear last.
    Does not modify the original list.
    """
    import math

    def sort_key(organization):
        distance = organization.get("distance")

        if (
            isinstance(distance, bool)
            or not isinstance(distance, (int, float))
            or not math.isfinite(distance)
            or distance < 0
        ):
            return (1, float("inf"))

        return (0, distance)

    return sorted(organizations, key=sort_key)