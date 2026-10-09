import json
import os
import sys
import pandas as pd
import pytest

# Allow this test file to import from lambda_functions/
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

LAMBDA_DIR = os.path.join(
    PROJECT_ROOT,
    "lambda_functions"
)

sys.path.insert(0, LAMBDA_DIR)


# Tell the Lambda code to use local CSV files.
os.environ["USE_MOCK_DATA"] = "true"
os.environ["MOCK_DATA_DIR"] = os.path.join(
    PROJECT_ROOT,
    "sql"
)

from rating_type_analytics import lambda_handler


def run_test(name, event):
    print("\n" + "=" * 70)
    print(name)
    print("=" * 70)

    response = lambda_handler(event, None)

    print(json.dumps(response, indent=2))

    return response


def assert_status(response, expected_status):
    assert response["statusCode"] == expected_status, (
        f"Expected status {expected_status}, "
        f"got {response['statusCode']}"
    )


def get_body(response):
    return json.loads(response["body"])


def assert_exact_keys(actual, expected):
    assert set(actual.keys()) == set(expected), (
        f"Expected keys {expected}, "
        f"got {list(actual.keys())}"
    )


def assert_chart_shape(chart):
    assert set(chart.keys()) == {
        "rating_distribution",
        "organization_mix_trend"
    }

    assert set(
        chart["organization_mix_trend"].keys()
    ) == {
        "non_profit",
        "for_profit"
    }


def assert_cumulative(series):
    counts = [
        item["count"]
        for item in series
    ]

    assert counts == sorted(counts), (
        f"Counts are not cumulative/non-decreasing: "
        f"{counts}"
    )


# No Custom parameters

response = run_test(
    "No Custom parameters",
    {}
)

assert_status(response, 200)

body = get_body(response)

assert_exact_keys(
    body,
    ["7D", "30D", "1Y", "All", "Custom"]
)

for bucket in ["7D", "30D", "1Y", "All", "Custom"]:
    assert_chart_shape(body[bucket])

assert body["Custom"]["rating_distribution"] == []

assert body["Custom"][
    "organization_mix_trend"
]["non_profit"] == []

assert body["Custom"][
    "organization_mix_trend"
]["for_profit"] == []


# Country filter

response = run_test(
    "Country filter",
    {
        "country": "USA"
    }
)

assert_status(response, 200)

country_body = get_body(response)

assert_exact_keys(
    country_body,
    ["7D", "30D", "1Y", "All", "Custom"]
)

for bucket in ["7D", "30D", "1Y", "All", "Custom"]:
    assert_chart_shape(country_body[bucket])


# Rating Custom only

response = run_test(
    "Rating Custom only",
    {
        "rating_start_date": "2025-01-01",
        "rating_end_date": "2025-12-31"
    }
)

assert_status(response, 200)

body = get_body(response)

assert_exact_keys(
    body,
    ["Custom"]
)

custom = body["Custom"]

assert custom["rating_distribution"]

assert custom[
    "organization_mix_trend"
]["non_profit"] == []

assert custom[
    "organization_mix_trend"
]["for_profit"] == []


# Type Custom only

response = run_test(
    "Type Custom only",
    {
        "type_start_date": "2025-01-01",
        "type_end_date": "2025-12-31"
    }
)

assert_status(response, 200)

body = get_body(response)

assert_exact_keys(
    body,
    ["Custom"]
)

custom = body["Custom"]

assert custom["rating_distribution"] == []

assert (
    custom["organization_mix_trend"]["non_profit"]
    or
    custom["organization_mix_trend"]["for_profit"]
)


# Both Custom ranges

response = run_test(
    "Both Custom ranges",
    {
        "rating_start_date": "2025-01-01",
        "rating_end_date": "2025-12-31",
        "type_start_date": "2024-01-01",
        "type_end_date": "2025-12-31"
    }
)

assert_status(response, 200)

body = get_body(response)

assert_exact_keys(
    body,
    ["Custom"]
)

custom = body["Custom"]

assert custom["rating_distribution"]

assert (
    custom["organization_mix_trend"]["non_profit"]
    or
    custom["organization_mix_trend"]["for_profit"]
)


# Missing rating date

response = run_test(
    "Missing rating end date",
    {
        "rating_start_date": "2025-01-01"
    }
)

assert_status(response, 400)


# Invalid rating date

response = run_test(
    "Invalid rating date",
    {
        "rating_start_date": "2025-99-01",
        "rating_end_date": "2025-12-31"
    }
)

assert_status(response, 400)


# Rating start after end

response = run_test(
    "Rating start after end",
    {
        "rating_start_date": "2026-01-01",
        "rating_end_date": "2025-01-01"
    }
)

assert_status(response, 400)


# Missing type date

response = run_test(
    "Missing type start date",
    {
        "type_end_date": "2025-12-31"
    }
)

assert_status(response, 400)


# Invalid type date

response = run_test(
    "Invalid type date",
    {
        "type_start_date": "not-a-date",
        "type_end_date": "2025-12-31"
    }
)

assert_status(response, 400)


# Type start after end

response = run_test(
    "Type start after end",
    {
        "type_start_date": "2026-01-01",
        "type_end_date": "2025-01-01"
    }
)

assert_status(response, 400)


# Check cumulative counts

response = run_test(
    "Cumulative organization counts",
    {}
)

assert_status(response, 200)

body = get_body(response)

for bucket_name in ["7D", "30D", "1Y", "All"]:

    trend = body[bucket_name][
        "organization_mix_trend"
    ]

    assert_cumulative(
        trend["non_profit"]
    )

    assert_cumulative(
        trend["for_profit"]
    )

