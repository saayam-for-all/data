import json

from lambda_functions.rating_type_analytics import lambda_handler


def call_api(body=None):
    """Call the Lambda handler and parse its JSON body."""
    if body is None:
        event = {}
    else:
        event = {
            "body": json.dumps(body)
        }

    response = lambda_handler(event, None)

    return (
        response["statusCode"],
        json.loads(response["body"]),
    )


def assert_bucket_structure(bucket):
    """Verify the exact structure required inside each bucket."""
    assert set(bucket.keys()) == {
        "rating_distribution",
        "organization_mix_trend",
    }

    assert set(
        bucket["organization_mix_trend"].keys()
    ) == {
        "non_profit",
        "for_profit",
    }


def assert_non_decreasing(series):
    """Verify cumulative counts never decrease."""
    counts = [
        item["count"]
        for item in series
    ]

    assert counts == sorted(counts), (
        f"Counts are not non-decreasing: {counts}"
    )


def test_no_body():
    status, body = call_api()

    assert status == 200

    assert list(body.keys()) == [
        "7D",
        "30D",
        "1Y",
        "All",
        "Custom",
    ]

    assert len(body) == 5

    for bucket_name in [
        "7D",
        "30D",
        "1Y",
        "All",
        "Custom",
    ]:
        assert_bucket_structure(
            body[bucket_name]
        )

    assert body["Custom"] == {
        "rating_distribution": [],
        "organization_mix_trend": {
            "non_profit": [],
            "for_profit": [],
        },
    }


def test_country_filter():
    status, body = call_api(
        {
            "country": "USA",
        }
    )

    assert status == 200

    assert list(body.keys()) == [
        "7D",
        "30D",
        "1Y",
        "All",
        "Custom",
    ]

    for bucket in body.values():
        assert_bucket_structure(bucket)


def test_rating_custom_only():
    status, body = call_api(
        {
            "rating_start_date": "2026-01-01",
            "rating_end_date": "2026-06-30",
        }
    )

    assert status == 200
    assert list(body.keys()) == ["Custom"]
    assert len(body) == 1

    custom = body["Custom"]

    assert_bucket_structure(custom)

    assert custom[
        "organization_mix_trend"
    ] == {
        "non_profit": [],
        "for_profit": [],
    }

    ratings = [
        item["rating"]
        for item in custom["rating_distribution"]
    ]

    # Ratings should be sorted and should not be
    # zero-filled with missing categories.
    assert ratings == sorted(ratings)

    assert all(
        rating in {1, 2, 3, 4, 5}
        for rating in ratings
    )


def test_type_custom_only():
    status, body = call_api(
        {
            "type_start_date": "2025-01-01",
            "type_end_date": "2025-12-31",
        }
    )

    assert status == 200
    assert list(body.keys()) == ["Custom"]
    assert len(body) == 1

    custom = body["Custom"]

    assert_bucket_structure(custom)

    assert custom[
        "rating_distribution"
    ] == []

    trend = custom[
        "organization_mix_trend"
    ]

    assert_non_decreasing(
        trend["non_profit"]
    )

    assert_non_decreasing(
        trend["for_profit"]
    )


def test_both_custom_ranges():
    status, body = call_api(
        {
            "rating_start_date": "2026-01-01",
            "rating_end_date": "2026-06-30",
            "type_start_date": "2025-01-01",
            "type_end_date": "2025-12-31",
        }
    )

    assert status == 200
    assert list(body.keys()) == ["Custom"]
    assert len(body) == 1

    custom = body["Custom"]

    assert_bucket_structure(custom)

    # With our local test data, both requested
    # ranges should contain organizations.
    assert len(
        custom["rating_distribution"]
    ) > 0

    trend = custom[
        "organization_mix_trend"
    ]

    assert (
        len(trend["non_profit"]) > 0
        or len(trend["for_profit"]) > 0
    )

    assert_non_decreasing(
        trend["non_profit"]
    )

    assert_non_decreasing(
        trend["for_profit"]
    )


def test_fixed_bucket_cumulative_counts():
    status, body = call_api()

    assert status == 200

    for bucket_name in [
        "7D",
        "30D",
        "1Y",
        "All",
    ]:
        trend = body[
            bucket_name
        ]["organization_mix_trend"]

        assert_non_decreasing(
            trend["non_profit"]
        )

        assert_non_decreasing(
            trend["for_profit"]
        )


def test_period_formats():
    status, body = call_api()

    assert status == 200

    # Daily buckets: YYYY-MM-DD
    for bucket_name in ["7D", "30D"]:
        trend = body[
            bucket_name
        ]["organization_mix_trend"]

        for org_type in [
            "non_profit",
            "for_profit",
        ]:
            for item in trend[org_type]:
                assert (
                    len(item["period"]) == 10
                )

    # Monthly buckets: YYYY-MM
    for bucket_name in ["1Y", "All"]:
        trend = body[
            bucket_name
        ]["organization_mix_trend"]

        for org_type in [
            "non_profit",
            "for_profit",
        ]:
            for item in trend[org_type]:
                assert (
                    len(item["period"]) == 7
                )


def test_missing_rating_end_date():
    status, body = call_api(
        {
            "rating_start_date": "2026-01-01",
        }
    )

    assert status == 400
    assert "error" in body


def test_missing_type_start_date():
    status, body = call_api(
        {
            "type_end_date": "2025-12-31",
        }
    )

    assert status == 400
    assert "error" in body


def test_bad_rating_date_format():
    status, body = call_api(
        {
            "rating_start_date": "01/01/2026",
            "rating_end_date": "06/30/2026",
        }
    )

    assert status == 400
    assert "error" in body


def test_bad_type_date_format():
    status, body = call_api(
        {
            "type_start_date": "January 1 2025",
            "type_end_date": "December 31 2025",
        }
    )

    assert status == 400
    assert "error" in body


def test_rating_start_after_end():
    status, body = call_api(
        {
            "rating_start_date": "2026-12-31",
            "rating_end_date": "2026-01-01",
        }
    )

    assert status == 400
    assert "error" in body


def test_type_start_after_end():
    status, body = call_api(
        {
            "type_start_date": "2026-12-31",
            "type_end_date": "2026-01-01",
        }
    )

    assert status == 400
    assert "error" in body


def test_empty_custom_range():
    status, body = call_api(
        {
            "rating_start_date": "2020-01-01",
            "rating_end_date": "2020-12-31",
            "type_start_date": "2020-01-01",
            "type_end_date": "2020-12-31",
        }
    )

    assert status == 200

    assert body == {
        "Custom": {
            "rating_distribution": [],
            "organization_mix_trend": {
                "non_profit": [],
                "for_profit": [],
            },
        }
    }


def test_sparse_periods():
    status, body = call_api()

    assert status == 200

    for bucket_name in [
        "7D",
        "30D",
        "1Y",
        "All",
    ]:
        trend = body[
            bucket_name
        ]["organization_mix_trend"]

        for org_type in [
            "non_profit",
            "for_profit",
        ]:
            periods = [
                item["period"]
                for item in trend[org_type]
            ]

            assert len(periods) == len(
                set(periods)
            )

def test_empty_organizations_dataframe():
    """Empty organization data must not crash chart builders."""
    import pandas as pd

    from lambda_functions.rating_type_analytics import (
        build_rating_distribution,
        build_organization_mix_trend,
    )

    organizations = pd.DataFrame(
        columns=[
            "org_id",
            "org_rating",
            "org_type",
            "state_id",
            "created_at",
        ]
    )

    organizations["created_at"] = pd.to_datetime(
        organizations["created_at"]
    )

    date_range = (
        pd.Timestamp("2026-01-01"),
        pd.Timestamp("2026-12-31"),
    )

    rating_result = build_rating_distribution(
        organizations,
        date_range,
    )

    trend_result = build_organization_mix_trend(
        organizations,
        date_range,
        "day",
    )

    assert rating_result == []

    assert trend_result == {
        "non_profit": [],
        "for_profit": [],
    }


def test_one_row_organizations_dataframe():
    """A one-row organization dataset must work correctly."""
    import pandas as pd

    from lambda_functions.rating_type_analytics import (
        build_rating_distribution,
        build_organization_mix_trend,
    )

    organizations = pd.DataFrame(
        [
            {
                "org_id": "test-org-1",
                "org_rating": 5,
                "org_type": "non_profit",
                "state_id": "test-state-1",
                "created_at": pd.Timestamp(
                    "2026-06-15"
                ),
            }
        ]
    )

    date_range = (
        pd.Timestamp("2026-01-01"),
        pd.Timestamp("2026-12-31"),
    )

    rating_result = build_rating_distribution(
        organizations,
        date_range,
    )

    assert rating_result == [
        {
            "rating": 5,
            "count": 1,
        }
    ]

    trend_result = build_organization_mix_trend(
        organizations,
        date_range,
        "day",
    )

    assert trend_result == {
        "non_profit": [
            {
                "period": "2026-06-15",
                "count": 1,
            }
        ],
        "for_profit": [],
    }

TESTS = [
    ("No body", test_no_body),
    ("Country filter", test_country_filter),
    ("Rating Custom only", test_rating_custom_only),
    ("Type Custom only", test_type_custom_only),
    ("Both Custom ranges", test_both_custom_ranges),
    (
        "Fixed cumulative counts",
        test_fixed_bucket_cumulative_counts,
    ),
    ("Period formats", test_period_formats),
    ("Sparse periods", test_sparse_periods),
    (
        "Missing rating end date",
        test_missing_rating_end_date,
    ),
    (
        "Missing type start date",
        test_missing_type_start_date,
    ),
    (
        "Bad rating date format",
        test_bad_rating_date_format,
    ),
    (
        "Bad type date format",
        test_bad_type_date_format,
    ),
    (
        "Rating start after end",
        test_rating_start_after_end,
    ),
    (
        "Type start after end",
        test_type_start_after_end,
    ),
    (
        "Empty Custom range",
        test_empty_custom_range,
    ),
        (
        "Empty organizations DataFrame",
        test_empty_organizations_dataframe,
    ),
    (
        "One-row organizations DataFrame",
        test_one_row_organizations_dataframe,
    ),
]


if __name__ == "__main__":
    failures = 0

    print(
        "\nRating & Type Analytics "
        "Acceptance Verification\n"
    )

    for name, test_function in TESTS:
        try:
            test_function()
            print(f"PASS: {name}")

        except AssertionError as exc:
            failures += 1
            print(
                f"FAIL: {name}"
                + (
                    f" - {exc}"
                    if str(exc)
                    else ""
                )
            )

        except Exception as exc:
            failures += 1
            print(
                f"ERROR: {name} - "
                f"{type(exc).__name__}: {exc}"
            )

    print(
        f"\nCompleted {len(TESTS)} tests. "
        f"Failures: {failures}"
    )

    if failures:
        raise SystemExit(1)

    print(
        "All acceptance verification "
        "tests passed."
    )