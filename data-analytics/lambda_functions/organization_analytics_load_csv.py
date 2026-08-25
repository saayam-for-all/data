"""Load the checked-in state and organization extracts into local PostgreSQL."""

import csv
import os
from pathlib import Path

from organization_analytics import get_db_connection


DATA_DIRECTORY = Path(__file__).resolve().parents[1] / "sql"
STATE_CSV = DATA_DIRECTORY / "state.csv"
ORGANIZATIONS_CSV = DATA_DIRECTORY / "organizations.csv"


def parse_boolean(value):
    """Convert a CSV boolean value to a Python boolean or None."""
    if value is None or not value.strip():
        return None
    return value.strip().lower() == "true"


def empty_to_none(value):
    """Convert empty CSV cells to None."""
    return value if value not in (None, "") else None


def require_local_test_mode():
    """Prevent this data loader from running without an explicit local opt-in."""
    enabled = os.environ.get("ORG_ANALYTICS_LOCAL_TEST", "").lower()
    if enabled not in {"1", "true", "yes"}:
        raise RuntimeError(
            "Set ORG_ANALYTICS_LOCAL_TEST=true before loading local test data."
        )


def load_states(cursor):
    """Upsert all rows from state.csv and return the number processed."""
    with STATE_CSV.open(encoding="utf-8-sig", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))
    cursor.executemany(
        """
        INSERT INTO virginia_dev_saayam_rdbms.state (
            state_id, country_id, state_name, state_code, last_update_date
        ) VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (state_id) DO UPDATE SET
            country_id = EXCLUDED.country_id,
            state_name = EXCLUDED.state_name,
            state_code = EXCLUDED.state_code,
            last_update_date = EXCLUDED.last_update_date;
        """,
        [
            (
                row["state_id"],
                empty_to_none(row["country_id"]),
                row["state_name"],
                empty_to_none(row["state_code"]),
                empty_to_none(row["last_update_date"]),
            )
            for row in rows
        ],
    )
    return len(rows)


def load_organizations(cursor):
    """Upsert all rows from organizations.csv and return the number processed."""
    with ORGANIZATIONS_CSV.open(encoding="utf-8-sig", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))
    cursor.executemany(
        """
        INSERT INTO virginia_dev_saayam_rdbms.organizations (
            org_id, org_name, street, city_name, state_id, zip_code, mission,
            web_url, phone, email, org_type, org_size, org_rating,
            is_collaborator, is_contributor, created_at, last_updated_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s
        )
        ON CONFLICT (org_id) DO UPDATE SET
            org_name = EXCLUDED.org_name,
            street = EXCLUDED.street,
            city_name = EXCLUDED.city_name,
            state_id = EXCLUDED.state_id,
            zip_code = EXCLUDED.zip_code,
            mission = EXCLUDED.mission,
            web_url = EXCLUDED.web_url,
            phone = EXCLUDED.phone,
            email = EXCLUDED.email,
            org_type = EXCLUDED.org_type,
            org_size = EXCLUDED.org_size,
            org_rating = EXCLUDED.org_rating,
            is_collaborator = EXCLUDED.is_collaborator,
            is_contributor = EXCLUDED.is_contributor,
            created_at = EXCLUDED.created_at,
            last_updated_at = EXCLUDED.last_updated_at;
        """,
        [
            (
                row["org_id"],
                row["org_name"],
                empty_to_none(row["street"]),
                empty_to_none(row["city_name"]),
                empty_to_none(row["state_id"]),
                empty_to_none(row["zip_code"]),
                empty_to_none(row["mission"]),
                empty_to_none(row["web_url"]),
                empty_to_none(row["phone"]),
                empty_to_none(row["email"]),
                empty_to_none(row["org_type"]),
                empty_to_none(row["org_size"]),
                empty_to_none(row["org_rating"]),
                parse_boolean(row["is_collaborator"]),
                parse_boolean(row["is_contributor"]),
                empty_to_none(row["created_at"]),
                empty_to_none(row["last_updated_at"]),
            )
            for row in rows
        ],
    )
    return len(rows)


def main():
    """Load both source extracts in one local transaction."""
    require_local_test_mode()
    connection = get_db_connection()
    connection.autocommit = False
    try:
        with connection.cursor() as cursor:
            state_count = load_states(cursor)
            organization_count = load_organizations(cursor)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    print(f"Loaded {state_count} states and {organization_count} organizations.")


if __name__ == "__main__":
    main()

