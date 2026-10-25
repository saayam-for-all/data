import csv
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
import pytest
import steward_volunteer_review_api as api


# Test data

TEST_DATA_FILE = (
    Path(__file__).resolve().parent
    / "test_data"
    / "steward_volunteer_review_test.csv"
)


def load_test_data():
    """
    Load local test data used to simulate the users and
    volunteers information needed by the Review Volunteers API.
    """

    if not TEST_DATA_FILE.exists():
        raise FileNotFoundError(
            f"Test data file not found: {TEST_DATA_FILE}"
        )

    with open(
        TEST_DATA_FILE,
        "r",
        newline="",
        encoding="utf-8"
    ) as file:
        return list(csv.DictReader(file))


# Fake cursor

class FakeCursor:
    """
    Lightweight local cursor used for testing the production
    helper functions without connecting to PostgreSQL.

    The CSV represents the local test dataset.

    This allows us to test:
        - UNDER_REVIEW filtering
        - sorting
        - total record count
        - pagination
        - returned fields
    """

    def __init__(self, rows):
        self.rows = rows
        self.result = []
        self.executed_query = None
        self.executed_params = None

    def execute(self, query, params=None):
        self.executed_query = query
        self.executed_params = params

        # ----------------------------------------------------
        # Total record query
        # ----------------------------------------------------
        if "COUNT(DISTINCT" in query:
            review_status = params[0]

            matching_users = {
                row["user_id"]
                for row in self.rows
                if row["application_status"] == review_status
            }

            self.result = [(len(matching_users),)]
            return

        # ----------------------------------------------------
        # Review records query
        # ----------------------------------------------------
        if "ORDER BY" in query and "LIMIT" in query:
            review_status = params[0]
            page_size = int(params[1])
            offset = int(params[2])

            filtered_rows = [
                row
                for row in self.rows
                if row["application_status"] == review_status
            ]

            # Sort by latest updated time descending.
            # user_id ascending is the secondary sort exactly
            # as used by the production query.
            filtered_rows.sort(
                key=lambda row: (
                    datetime.strptime(
                        row["last_updated_at"],
                        "%Y-%m-%d %H:%M:%S"
                    ),
                    row["user_id"]
                ),
                reverse=True
            )

            filtered_rows.sort(
                key=lambda row: row["user_id"]
            )

            filtered_rows.sort(
                key=lambda row: datetime.strptime(
                    row["last_updated_at"],
                    "%Y-%m-%d %H:%M:%S"
                ),
                reverse=True
            )

            paginated_rows = filtered_rows[
                offset:offset + page_size
            ]

            self.result = [
                (
                    row["user_id"],
                    datetime.strptime(
                        row["last_updated_at"],
                        "%Y-%m-%d %H:%M:%S"
                    )
                )
                for row in paginated_rows
            ]

            return

        raise AssertionError(
            "Unexpected SQL query in FakeCursor"
        )

    def fetchone(self):
        if not self.result:
            return None

        return self.result[0]

    def fetchall(self):
        return self.result

    def close(self):
        pass



# Basic test-data validation

def test_test_data_file_exists():
    assert TEST_DATA_FILE.exists()


def test_test_data_contains_required_columns():
    rows = load_test_data()

    assert rows

    required_columns = {
        "user_id",
        "application_status",
        "last_updated_at"
    }

    assert required_columns.issubset(rows[0].keys())


def test_test_data_contains_review_records():
    rows = load_test_data()

    review_rows = [
        row
        for row in rows
        if row["application_status"] == "UNDER_REVIEW"
    ]

    assert review_rows



def test_parse_event_body_with_direct_event():
    event = {
        "page": 2,
        "page_size": 10
    }

    result = api.parse_event_body(event)

    assert result == event


def test_parse_event_body_with_json_string():
    event = {
        "body": json.dumps({
            "page": 2,
            "page_size": 10
        })
    }

    result = api.parse_event_body(event)

    assert result == {
        "page": 2,
        "page_size": 10
    }


def test_parse_event_body_with_dictionary_body():
    event = {
        "body": {
            "page": 2,
            "page_size": 10
        }
    }

    result = api.parse_event_body(event)

    assert result == {
        "page": 2,
        "page_size": 10
    }


def test_parse_event_body_with_invalid_json():
    event = {
        "body": "not valid json"
    }

    result = api.parse_event_body(event)

    assert result == {}


# Pagination validation

def test_default_pagination():
    page, page_size = api.get_pagination_parameters({})

    assert page == 1
    assert page_size == 5


def test_valid_pagination():
    page, page_size = api.get_pagination_parameters({
        "page": 3,
        "page_size": 10
    })

    assert page == 3
    assert page_size == 10


def test_pagination_values_are_converted_to_integers():
    page, page_size = api.get_pagination_parameters({
        "page": "2",
        "page_size": "10"
    })

    assert page == 2
    assert page_size == 10


@pytest.mark.parametrize(
    "request_body",
    [
        {"page": 0, "page_size": 5},
        {"page": -1, "page_size": 5},
        {"page": 1, "page_size": 0},
        {"page": 1, "page_size": -5},
        {"page": 1, "page_size": 101},
    ]
)
def test_invalid_pagination(request_body):
    with pytest.raises(ValueError):
        api.get_pagination_parameters(request_body)


def test_non_integer_pagination():
    with pytest.raises(ValueError):
        api.get_pagination_parameters({
            "page": "abc",
            "page_size": 5
        })


def test_get_total_review_records():
    rows = load_test_data()

    cursor = FakeCursor(rows)

    total = api.get_total_review_records(cursor)

    expected = len({
        row["user_id"]
        for row in rows
        if row["application_status"] == "UNDER_REVIEW"
    })

    assert total == expected


def test_get_total_review_records_uses_review_status_parameter():
    rows = load_test_data()

    cursor = FakeCursor(rows)

    api.get_total_review_records(cursor)

    assert cursor.executed_params == (
        api.REVIEW_STATUS,
    )

    assert api.REVIEW_STATUS == "UNDER_REVIEW"


def test_get_review_records_returns_only_under_review():
    rows = load_test_data()

    cursor = FakeCursor(rows)

    results = api.get_review_records(
        cursor=cursor,
        page_size=100,
        offset=0
    )

    assert results

    for record in results:
        source_row = next(
            row
            for row in rows
            if row["user_id"] == record["user_id"]
        )

        assert (
            source_row["application_status"]
            == "UNDER_REVIEW"
        )


def test_get_review_records_returns_required_fields():
    rows = load_test_data()

    cursor = FakeCursor(rows)

    results = api.get_review_records(
        cursor=cursor,
        page_size=5,
        offset=0
    )

    assert results

    for record in results:
        assert set(record.keys()) == {
            "user_id",
            "updated_time",
            "volunteer_review"
        }

        assert record["volunteer_review"] == "Review"


def test_get_review_records_sorted_by_latest_update():
    rows = load_test_data()

    cursor = FakeCursor(rows)

    results = api.get_review_records(
        cursor=cursor,
        page_size=100,
        offset=0
    )

    timestamps = [
        datetime.strptime(
            record["updated_time"],
            "%Y-%m-%dT%H:%M:%SZ"
        )
        for record in results
    ]

    assert timestamps == sorted(
        timestamps,
        reverse=True
    )


def test_get_review_records_pagination_first_page():
    rows = load_test_data()

    cursor = FakeCursor(rows)

    page_size = 2

    results = api.get_review_records(
        cursor=cursor,
        page_size=page_size,
        offset=0
    )

    assert len(results) == page_size


def test_get_review_records_pagination_second_page():
    rows = load_test_data()

    cursor = FakeCursor(rows)

    page_size = 2

    first_page = api.get_review_records(
        cursor=cursor,
        page_size=page_size,
        offset=0
    )

    second_page = api.get_review_records(
        cursor=cursor,
        page_size=page_size,
        offset=page_size
    )

    first_ids = {
        record["user_id"]
        for record in first_page
    }

    second_ids = {
        record["user_id"]
        for record in second_page
    }

    assert first_ids.isdisjoint(second_ids)


def test_get_review_records_empty_results():
    rows = load_test_data()

    non_review_rows = [
        row
        for row in rows
        if row["application_status"] != "UNDER_REVIEW"
    ]

    cursor = FakeCursor(non_review_rows)

    results = api.get_review_records(
        cursor=cursor,
        page_size=5,
        offset=0
    )

    assert results == []


def test_get_review_records_offset_beyond_data():
    rows = load_test_data()

    cursor = FakeCursor(rows)

    results = api.get_review_records(
        cursor=cursor,
        page_size=5,
        offset=10000
    )

    assert results == []


# Timestamp formatting

def test_format_updated_time_datetime():
    value = datetime(
        2026,
        5,
        12,
        7,
        15,
        0
    )

    result = api.format_updated_time(value)

    assert result == "2026-05-12T07:15:00Z"


def test_format_updated_time_string():
    result = api.format_updated_time(
        "2026-05-12 07:15:00"
    )

    assert result == "2026-05-12T07:15:00Z"


def test_format_updated_time_none():
    assert api.format_updated_time(None) is None


# Lambda pagination calculation

@pytest.mark.parametrize(
    "total_records,page_size,expected_pages",
    [
        (0, 5, 0),
        (1, 5, 1),
        (5, 5, 1),
        (6, 5, 2),
        (10, 5, 2),
        (11, 5, 3),
        (20, 5, 4),
        (21, 5, 5),
    ]
)
def test_total_pages_calculation(
    total_records,
    page_size,
    expected_pages
):
    import math

    if total_records == 0:
        total_pages = 0
    else:
        total_pages = math.ceil(
            total_records / page_size
        )

    assert total_pages == expected_pages


# Lambda handler with mocked database

def test_lambda_handler_success():
    rows = load_test_data()

    fake_cursor = FakeCursor(rows)
    fake_connection = Mock()

    with patch(
        "steward_volunteer_review_api.get_db_config",
        return_value={
            "host": "test",
            "port": 5432,
            "dbname": "test",
            "user": "test",
            "password": "test"
        }
    ), patch(
        "steward_volunteer_review_api.psycopg2.connect",
        return_value=fake_connection
    ):

        fake_connection.cursor.return_value = fake_cursor

        response = api.lambda_handler(
            {
                "page": 1,
                "page_size": 5
            },
            None
        )

    assert response["statusCode"] == 200

    body = json.loads(response["body"])

    assert "data" in body
    assert "pagination" in body

    assert body["pagination"]["current_page"] == 1
    assert body["pagination"]["page_size"] == 5

    assert isinstance(body["data"], list)

    for record in body["data"]:
        assert set(record.keys()) == {
            "user_id",
            "updated_time",
            "volunteer_review"
        }

        assert record["volunteer_review"] == "Review"


def test_lambda_handler_empty_results():
    rows = load_test_data()

    non_review_rows = [
        row
        for row in rows
        if row["application_status"] != "UNDER_REVIEW"
    ]

    fake_cursor = FakeCursor(non_review_rows)
    fake_connection = Mock()

    with patch(
        "steward_volunteer_review_api.get_db_config",
        return_value={
            "host": "test",
            "port": 5432,
            "dbname": "test",
            "user": "test",
            "password": "test"
        }
    ), patch(
        "steward_volunteer_review_api.psycopg2.connect",
        return_value=fake_connection
    ):

        fake_connection.cursor.return_value = fake_cursor

        response = api.lambda_handler(
            {
                "page": 1,
                "page_size": 5
            },
            None
        )

    assert response["statusCode"] == 200

    body = json.loads(response["body"])

    assert body["data"] == []
    assert body["pagination"]["total_records"] == 0
    assert body["pagination"]["total_pages"] == 0


# Lambda validation errors

def test_lambda_handler_invalid_page():
    response = api.lambda_handler(
        {
            "page": 0,
            "page_size": 5
        },
        None
    )

    assert response["statusCode"] == 400

    body = json.loads(response["body"])

    assert body["data"] == []


def test_lambda_handler_invalid_page_size():
    response = api.lambda_handler(
        {
            "page": 1,
            "page_size": 101
        },
        None
    )

    assert response["statusCode"] == 400

    body = json.loads(response["body"])

    assert body["data"] == []



# Database error handling

def test_lambda_handler_database_error():
    with patch(
        "steward_volunteer_review_api.get_db_config",
        return_value={
            "host": "test",
            "port": 5432,
            "dbname": "test",
            "user": "test",
            "password": "test"
        }
    ), patch(
        "steward_volunteer_review_api.psycopg2.connect",
        side_effect=Exception("Database connection failed")
    ):

        response = api.lambda_handler(
            {
                "page": 1,
                "page_size": 5
            },
            None
        )

    assert response["statusCode"] == 500

    body = json.loads(response["body"])

    assert body["data"] == []

    assert "Database connection failed" not in response["body"]


# CORS preflight

def test_lambda_handler_options():
    response = api.lambda_handler(
        {
            "httpMethod": "OPTIONS"
        },
        None
    )

    assert response["statusCode"] == 200
    assert response["body"] == "{}"

def test_review_query_uses_volunteers_table():
    rows = load_test_data()
    cursor = FakeCursor(rows)

    api.get_review_records(
        cursor=cursor,
        page_size=5,
        offset=0
    )

    assert "volunteer_applications" in cursor.executed_query
    assert cursor.executed_params[0] == api.REVIEW_STATUS