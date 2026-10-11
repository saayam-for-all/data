"""Explicit read-only mock runner; never imported or selected by the deployed handler."""

import argparse
import json
import math
from pathlib import Path

from address_geocoding import CoordinateRecord, GeocodingRateLimit
from lambda_function import lambda_handler
from local_geocoding import FakeCoordinateCache, FakeGeocodingProvider
from local_location_records import LocalMockLocationRecordSource, _read_csv
from offline_aggregator import AggregatorDependencies
from organization_addresses import OrganizationAddressAssembler
from organization_distance import nearest_first


def read_json(path: str | Path):
    """Read an explicitly selected fixture without changing it."""
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def _geocoding_responses(responses: dict) -> dict:
    """Decode synthetic responses: lat/lon objects, null, or explicit failure labels."""
    decoded = {}
    for address, value in responses.items():
        if isinstance(value, dict):
            decoded[address] = CoordinateRecord(value["latitude"], value["longitude"])
        elif value is None:
            decoded[address] = None
        elif value in ("deferred", "timeout", "error"):
            decoded[address] = {
                "deferred": GeocodingRateLimit(),
                "timeout": TimeoutError(),
                "error": RuntimeError(),
            }[value]
        else:
            raise ValueError("Unsupported synthetic geocoding response")
    return decoded


def _organization_rows(directory: Path) -> list[dict]:
    """Decode known generator CSV types while keeping textual IDs, sizes, and ZIPs.

    Missing or malformed collaborator/rating values remain unavailable, rather
    than becoming truthy strings or fabricated numbers. Files are never modified.
    """
    rows = _read_csv(directory / "organizations.csv", "org_id")
    for row in rows:
        if "is_collaborator" in row:
            value = (row["is_collaborator"] or "").strip().lower()
            row["is_collaborator"] = {"true": True, "false": False}.get(value)
        if "org_rating" in row:
            try:
                rating = float(row["org_rating"])
            except (ValueError, TypeError, OverflowError):
                rating = None
            row["org_rating"] = rating if rating is not None and math.isfinite(rating) else None
    return rows


def build_local_dependencies(
    mock_directory: str | Path,
    *,
    synthetic_requests: list[dict],
    ai_organizations,
    geocoding_responses: dict,
) -> AggregatorDependencies:
    """Compose generator-shaped CSVs and synthetic fixtures with instance-local fakes.

    Organization fixtures retain their rows with known CSV field types decoded,
    without inventing a live search, filtering, pagination, centroid, or sorting
    contract. No generator is executed.
    """
    directory = Path(mock_directory)
    states = _read_csv(directory / "states.csv", "state_id")
    countries = _read_csv(directory / "countries.csv", "country_id")
    organizations = _organization_rows(directory)
    records = LocalMockLocationRecordSource.from_csv_directory(
        directory, synthetic_requests=synthetic_requests
    )
    return AggregatorDependencies(
        records=records,
        provider=FakeGeocodingProvider(_geocoding_responses(geocoding_responses)),
        cache=FakeCoordinateCache(),
        db_source=lambda body: organizations,
        ai_source=lambda body: ai_organizations,
        addresses=OrganizationAddressAssembler(states=states, countries=countries),
        request_info_reader=records.get_request_info,
        online_reader=lambda organization: organization.record.get("online_only") is True,
    )


def run_local(event: dict, dependencies: AggregatorDependencies, *, sort_nearest=False) -> dict:
    """Run the injected handler; sorting is an explicit local preview option."""
    response = lambda_handler(event, None, dependencies=dependencies)
    if sort_nearest and response["statusCode"] == 200:
        response = dict(response)
        response["body"] = json.dumps(nearest_first(json.loads(response["body"])), allow_nan=False)
    return response


def main(argv=None) -> int:
    """Require all input paths and print the existing API response envelope to stdout."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock-directory", required=True)
    parser.add_argument(
        "--requests", required=True, help="JSON object with synthetic requests list"
    )
    parser.add_argument("--ai", required=True, help="Synthetic AI list or statusCode/body envelope")
    parser.add_argument(
        "--geocodes", required=True, help="Synthetic address-to-response JSON object"
    )
    parser.add_argument("--event", required=True, help="Direct request or API Gateway event JSON")
    parser.add_argument(
        "--nearest-first", action="store_true", help="Sort only this local response"
    )
    args = parser.parse_args(argv)
    try:
        dependencies = build_local_dependencies(
            args.mock_directory,
            synthetic_requests=read_json(args.requests)["requests"],
            ai_organizations=read_json(args.ai),
            geocoding_responses=read_json(args.geocodes),
        )
        response = run_local(read_json(args.event), dependencies, sort_nearest=args.nearest_first)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    print(json.dumps(response, allow_nan=False))
    return 0 if response["statusCode"] == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
