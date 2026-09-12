from __future__ import annotations

import json
from collections import Counter
from datetime import date
from typing import Any

from schema import (
    ORGANIZATION_SIZES,
    ORGANIZATION_TYPES,
    SKILL_LEVELS,
    TABLE_COLUMNS,
)
from utils import (
    haversine_distance_km,
    parse_geography_point,
    parse_timestamp,
)


class ValidationError(ValueError):
    pass


def _assert(
    condition: bool,
    message: str,
) -> None:
    if not condition:
        raise ValidationError(message)


def validate_columns(
    data: dict[str, list[dict[str, Any]]],
) -> None:
    for table_name, expected_columns in TABLE_COLUMNS.items():
        rows = data.get(table_name)

        _assert(
            rows is not None,
            f"Missing table: {table_name}",
        )

        for row_number, row in enumerate(rows, start=1):
            actual_columns = list(row.keys())

            _assert(
                actual_columns == expected_columns,
                (
                    f"{table_name} row {row_number} has invalid "
                    f"columns.\nExpected: {expected_columns}\n"
                    f"Actual:   {actual_columns}"
                ),
            )


def _validate_unique_column(
    rows: list[dict[str, Any]],
    column: str,
    table_name: str,
) -> None:
    values = [
        row[column]
        for row in rows
    ]

    duplicates = [
        value
        for value, count in Counter(values).items()
        if count > 1
    ]

    _assert(
        not duplicates,
        (
            f"{table_name}.{column} contains duplicate values: "
            f"{duplicates[:10]}"
        ),
    )


def validate_primary_keys(
    data: dict[str, list[dict[str, Any]]],
) -> None:
    single_primary_keys = {
        "countries": "country_id",
        "states": "state_id",
        "cities": "city_id",
        "users": "user_id",
        "volunteer_details": "user_id",
        "volunteer_locations": "user_id",
        "user_locations": "user_id",
        "help_categories": "cat_id",
        "organizations": "org_id",
    }

    for table_name, primary_key in single_primary_keys.items():
        _validate_unique_column(
            data[table_name],
            primary_key,
            table_name,
        )

    skill_keys = [
        (
            row["user_id"],
            row["cat_id"],
        )
        for row in data["user_skills"]
    ]

    _assert(
        len(skill_keys) == len(set(skill_keys)),
        "user_skills contains duplicate (user_id, cat_id) keys",
    )


def validate_foreign_keys(
    data: dict[str, list[dict[str, Any]]],
) -> None:
    country_ids = {
        row["country_id"]
        for row in data["countries"]
    }

    state_ids = {
        row["state_id"]
        for row in data["states"]
    }

    user_ids = {
        row["user_id"]
        for row in data["users"]
    }

    volunteer_user_ids = {
        row["user_id"]
        for row in data["volunteer_details"]
    }

    category_ids = {
        row["cat_id"]
        for row in data["help_categories"]
    }

    for row in data["states"]:
        _assert(
            row["country_id"] in country_ids,
            (
                f"states.country_id has orphan value: "
                f"{row['country_id']}"
            ),
        )

    for row in data["cities"]:
        _assert(
            row["state_id"] in state_ids,
            (
                f"cities.state_id has orphan value: "
                f"{row['state_id']}"
            ),
        )

    for row in data["users"]:
        if row["country_id"] is not None:
            _assert(
                row["country_id"] in country_ids,
                (
                    f"users.country_id has orphan value: "
                    f"{row['country_id']}"
                ),
            )

        if row["state_id"] is not None:
            _assert(
                row["state_id"] in state_ids,
                (
                    f"users.state_id has orphan value: "
                    f"{row['state_id']}"
                ),
            )

    for row in data["volunteer_details"]:
        _assert(
            row["user_id"] in user_ids,
            (
                "volunteer_details contains orphan user_id: "
                f"{row['user_id']}"
            ),
        )

    for row in data["user_skills"]:
        _assert(
            row["user_id"] in user_ids,
            (
                "user_skills contains orphan user_id: "
                f"{row['user_id']}"
            ),
        )

        _assert(
            row["cat_id"] in category_ids,
            (
                "user_skills contains orphan cat_id: "
                f"{row['cat_id']}"
            ),
        )

    for row in data["organizations"]:
        if row["state_id"] is not None:
            _assert(
                row["state_id"] in state_ids,
                (
                    "organizations contains orphan state_id: "
                    f"{row['state_id']}"
                ),
            )

    for row in data["user_locations"]:
        _assert(
            row["user_id"] in user_ids,
            (
                "user_locations contains orphan user_id: "
                f"{row['user_id']}"
            ),
        )

    for row in data["volunteer_locations"]:
        _assert(
            row["user_id"] in volunteer_user_ids,
            (
                "volunteer_locations.user_id must reference "
                "volunteer_details.user_id: "
                f"{row['user_id']}"
            ),
        )


def validate_geography(
    data: dict[str, list[dict[str, Any]]],
) -> None:
    state_country_lookup = {
        row["state_id"]: row["country_id"]
        for row in data["states"]
    }

    city_lookup = {
        (
            row["state_id"],
            row["city_name"],
        ): row
        for row in data["cities"]
    }

    users_by_id = {
        row["user_id"]: row
        for row in data["users"]
    }

    for user in data["users"]:
        state_id = user["state_id"]

        _assert(
            state_id is not None,
            f"User {user['user_id']} has no state_id",
        )

        _assert(
            state_country_lookup[state_id]
            == user["country_id"],
            (
                f"User {user['user_id']} has inconsistent "
                "state/country relationship"
            ),
        )

        city_key = (
            state_id,
            user["city_name"],
        )

        _assert(
            city_key in city_lookup,
            (
                f"User {user['user_id']} has city "
                f"{user['city_name']} that does not belong "
                f"to state {state_id}"
            ),
        )

    for organization in data["organizations"]:
        city_key = (
            organization["state_id"],
            organization["city_name"],
        )

        _assert(
            city_key in city_lookup,
            (
                f"Organization {organization['org_id']} has "
                "an invalid city/state combination"
            ),
        )

    for table_name in (
        "user_locations",
        "volunteer_locations",
    ):
        for location in data[table_name]:
            user = users_by_id[location["user_id"]]

            city = city_lookup[
                (
                    user["state_id"],
                    user["city_name"],
                )
            ]

            city_latitude = float(city["lattitude"])
            city_longitude = float(city["longitude"])

            for location_column in (
                "prev_loc",
                "curr_loc",
            ):
                latitude, longitude = parse_geography_point(
                    location[location_column]
                )

                _assert(
                    -90 <= latitude <= 90,
                    (
                        f"{table_name}.{location_column} "
                        "contains invalid latitude"
                    ),
                )

                _assert(
                    -180 <= longitude <= 180,
                    (
                        f"{table_name}.{location_column} "
                        "contains invalid longitude"
                    ),
                )

                distance = haversine_distance_km(
                    latitude,
                    longitude,
                    city_latitude,
                    city_longitude,
                )

                _assert(
                    distance <= 30,
                    (
                        f"{table_name} location for "
                        f"{location['user_id']} is {distance:.2f} km "
                        "from the user's assigned city"
                    ),
                )


def validate_timestamps(
    data: dict[str, list[dict[str, Any]]],
) -> None:
    timestamp_columns = {
        "countries": [
            "last_updated_at",
        ],
        "states": [
            "last_updated_at",
        ],
        "cities": [
            "last_updated_at",
        ],
        "users": [
            "last_updated_at",
            "promotion_wizard_last_updated_at",
        ],
        "volunteer_details": [
            "terms_accepted_at",
            "path1_updated_at",
            "path2_updated_at",
            "created_at",
            "last_updated_at",
        ],
        "user_skills": [
            "created_at",
            "last_updated_at",
        ],
        "volunteer_locations": [
            "last_updated_at",
        ],
        "user_locations": [
            "last_updated_at",
        ],
        "help_categories": [
            "last_updated_at",
        ],
        "organizations": [
            "created_at",
            "last_updated_at",
        ],
    }

    for table_name, columns in timestamp_columns.items():
        for row_number, row in enumerate(
            data[table_name],
            start=1,
        ):
            for column in columns:
                value = row[column]

                _assert(
                    value not in (None, ""),
                    (
                        f"{table_name} row {row_number} "
                        f"has empty timestamp {column}"
                    ),
                )

                try:
                    parse_timestamp(value)
                except ValueError as exc:
                    raise ValidationError(
                        (
                            f"Invalid timestamp in "
                            f"{table_name}.{column}: {value}"
                        )
                    ) from exc

    for row in data["volunteer_details"]:
        created_at = parse_timestamp(
            row["created_at"]
        )

        last_updated_at = parse_timestamp(
            row["last_updated_at"]
        )

        _assert(
            created_at <= last_updated_at,
            (
                "volunteer_details created_at is after "
                f"last_updated_at for {row['user_id']}"
            ),
        )

        for column in (
            "terms_accepted_at",
            "path1_updated_at",
            "path2_updated_at",
        ):
            related_timestamp = parse_timestamp(
                row[column]
            )

            _assert(
                created_at <= related_timestamp <= last_updated_at,
                (
                    f"volunteer_details.{column} has "
                    "inconsistent timestamp ordering for "
                    f"{row['user_id']}"
                ),
            )

    for row in data["user_skills"]:
        _assert(
            parse_timestamp(row["created_at"])
            <= parse_timestamp(row["last_updated_at"]),
            (
                "user_skills created_at is after "
                "last_updated_at"
            ),
        )

    for row in data["organizations"]:
        _assert(
            parse_timestamp(row["created_at"])
            <= parse_timestamp(row["last_updated_at"]),
            (
                "organizations created_at is after "
                f"last_updated_at for {row['org_id']}"
            ),
        )


def validate_json_fields(
    data: dict[str, list[dict[str, Any]]],
) -> None:
    for row in data["volunteer_details"]:
        try:
            availability_days = json.loads(
                row["availability_days"]
            )

            availability_times = json.loads(
                row["availability_times"]
            )

        except json.JSONDecodeError as exc:
            raise ValidationError(
                (
                    "Invalid JSON in volunteer_details for "
                    f"{row['user_id']}"
                )
            ) from exc

        _assert(
            isinstance(availability_days, list),
            "availability_days must contain a JSON list",
        )

        _assert(
            isinstance(availability_times, list),
            "availability_times must contain a JSON list",
        )


def validate_enums(
    data: dict[str, list[dict[str, Any]]],
) -> None:
    for row in data["user_skills"]:
        _assert(
            row["skill_level"] in SKILL_LEVELS,
            (
                "Invalid user_skills.skill_level: "
                f"{row['skill_level']}"
            ),
        )

    for row in data["organizations"]:
        _assert(
            row["org_type"] in ORGANIZATION_TYPES,
            (
                "Invalid organizations.org_type: "
                f"{row['org_type']}"
            ),
        )

        _assert(
            row["org_size"] in ORGANIZATION_SIZES,
            (
                "Invalid organizations.org_size: "
                f"{row['org_size']}"
            ),
        )

        _assert(
            1 <= row["org_rating"] <= 5,
            (
                "organizations.org_rating must be "
                "between 1 and 5"
            ),
        )


def validate_synthetic_personal_data(
    data: dict[str, list[dict[str, Any]]],
) -> None:
    for index, user in enumerate(
        data["users"],
        start=1,
    ):
        _assert(
            user["first_name"].startswith("Synthetic"),
            (
                "Generated user names must be clearly "
                "synthetic"
            ),
        )

        _assert(
            user["primary_email_address"].endswith(
                "@example.invalid"
            ),
            (
                "Generated user email must use "
                "example.invalid"
            ),
        )

        _assert(
            user["primary_phone_number"].startswith("555"),
            (
                "Generated user phone number must use "
                "the synthetic 555 range"
            ),
        )

        try:
            date.fromisoformat(user["dob"])
        except ValueError as exc:
            raise ValidationError(
                (
                    "Invalid users.dob for "
                    f"{user['user_id']}"
                )
            ) from exc

    for organization in data["organizations"]:
        _assert(
            organization["email"].endswith(
                "@example.invalid"
            ),
            (
                "Generated organization email must "
                "use example.invalid"
            ),
        )

        _assert(
            "example.invalid"
            in organization["web_url"],
            (
                "Generated organization URL must "
                "use example.invalid"
            ),
        )


def validate_required_fields(
    data: dict[str, list[dict[str, Any]]],
) -> None:
    required_fields = {
        "countries": [
            "country_id",
            "country_name",
            "phone_code",
            "country_code",
        ],
        "states": [
            "state_id",
            "country_id",
            "state_name",
        ],
        "cities": [
            "city_id",
            "state_id",
            "city_name",
        ],
        "users": [
            "user_id",
        ],
        "volunteer_details": [
            "user_id",
        ],
        "user_skills": [
            "user_id",
            "cat_id",
        ],
        "volunteer_locations": [
            "user_id",
        ],
        "user_locations": [
            "user_id",
        ],
        "help_categories": [
            "cat_id",
            "cat_name",
            "cat_desc",
        ],
        "organizations": [
            "org_id",
            "org_name",
        ],
    }

    for table_name, columns in required_fields.items():
        for row_number, row in enumerate(
            data[table_name],
            start=1,
        ):
            for column in columns:
                _assert(
                    row[column] not in (None, ""),
                    (
                        f"{table_name} row {row_number} "
                        f"has empty required field {column}"
                    ),
                )


def validate_all(
    data: dict[str, list[dict[str, Any]]],
) -> None:
    validate_columns(data)
    validate_required_fields(data)
    validate_primary_keys(data)
    validate_foreign_keys(data)
    validate_geography(data)
    validate_timestamps(data)
    validate_json_fields(data)
    validate_enums(data)
    validate_synthetic_personal_data(data)