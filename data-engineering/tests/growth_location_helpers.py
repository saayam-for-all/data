"""Shared CSV setup and UTC windows for the issue #336 tests."""

from pathlib import Path

import pandas as pd

from growth_location_analytics.date_ranges import DateWindow

ORGANIZATION_COLUMNS = [
    "org_id",
    "state_id",
    "city_name",
    "is_collaborator",
    "created_at",
]


def write_csvs(
    directory: Path,
    organizations: list[dict[str, object]],
    states: list[tuple[str, str, str]],
    countries: list[tuple[str, str]],
) -> None:
    """Write the three fixed test schemas, including headers for empty inputs."""

    pd.DataFrame(organizations, columns=ORGANIZATION_COLUMNS).to_csv(
        directory / "organizations.csv", index=False
    )
    pd.DataFrame(states, columns=["state_id", "state_name", "country_id"]).to_csv(
        directory / "states.csv", index=False
    )
    pd.DataFrame(countries, columns=["country_id", "country_code"]).to_csv(
        directory / "countries.csv", index=False
    )


def utc_window(start: str, end_exclusive: str) -> DateWindow:
    """Build explicit UTC boundaries without using the production date resolver."""

    return DateWindow(
        start=pd.Timestamp(start, tz="UTC").to_pydatetime(),
        end_exclusive=pd.Timestamp(end_exclusive, tz="UTC").to_pydatetime(),
    )
