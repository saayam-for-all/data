import json
from datetime import date, timedelta

from organization_analytics import lambda_handler


def run_case(name, payload, expected_status=200):
    """Run one API request and print the result."""
    result = lambda_handler({"body": json.dumps(payload)}, None)
    status_code = result["statusCode"]
    response_body = json.loads(result["body"])

    print(f"\n{'=' * 70}")
    print(name)
    print(f"Request: {json.dumps(payload)}")
    print(f"Status code: {status_code}")

    if status_code != expected_status:
        raise AssertionError(
            f"{name}: expected {expected_status}, received {status_code}"
        )

    print(json.dumps(response_body, indent=2, default=str))
    return response_body

def test_missing_contributor_column():
    """Verify the API works when is_contributor is absent."""
    import os
    import psycopg2

    connection = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "saayam_analytics"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD", ""),
    )

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE virginia_dev_saayam_rdbms.organizations
                DROP COLUMN is_contributor
                """
            )
            connection.commit()

        overview = run_case(
            "11. Overview — database without is_contributor",
            {"time_filter": "ALL"},
        )
        summary = overview["organization_overview"]["summary"]
        assert summary["contributor_organizations"] is None
        assert summary["non_contributor_organizations"] is None
        assert overview["organization_overview"]["contributor_distribution"] == []

        performance = run_case(
            "12. Performance — database without is_contributor",
            {"dashboard_type": "performance", "time_filter": "ALL"},
        )
        assert (
            performance["organization_performance"][
                "top_contributor_organizations"
            ]
            == []
        )

        run_case(
            "13. Contributor filter without database column",
            {"time_filter": "ALL", "is_contributor": True},
            expected_status=400,
        )
    finally:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE virginia_dev_saayam_rdbms.organizations
                ADD COLUMN IF NOT EXISTS is_contributor BOOLEAN
                """
            )
        connection.commit()
        connection.close()
def main():
    """Run local Organization Analytics API test cases."""
    overview = run_case(
        "1. Overview dashboard — default filters",
        {},
    )
    assert (
        overview["organization_overview"]["summary"]["total_organizations"]
        == 8
    )

    run_case(
        "2. Overview dashboard — all organizations",
        {
            "dashboard_type": "overview",
            "time_filter": "ALL",
            "group_by": "monthly",
        },
    )

    run_case(
        "3. Overview dashboard — type, state, and size filters",
        {
            "dashboard_type": "overview",
            "time_filter": "ALL",
            "org_type": "non_profit",
            "org_size": "large",
            "state_id": "CA",
        },
    )

    run_case(
        "4. Overview dashboard — case-insensitive city filter",
        {
            "dashboard_type": "overview",
            "time_filter": "ALL",
            "city_name": "chicago",
        },
    )

    run_case(
        "5. Overview dashboard — collaborator and contributor filters",
        {
            "dashboard_type": "overview",
            "time_filter": "ALL",
            "is_collaborator": False,
            "is_contributor": True,
        },
    )

    run_case(
        "6. Overview dashboard — custom date range",
        {
            "dashboard_type": "overview",
            "time_filter": "CUSTOM",
            "start_date": str(date.today() - timedelta(days=30)),
            "end_date": str(date.today()),
            "group_by": "weekly",
        },
    )

    run_case(
        "7. Performance dashboard — all organizations",
        {
            "dashboard_type": "performance",
            "time_filter": "ALL",
        },
    )

    run_case(
        "8. Performance dashboard — five-star organizations",
        {
            "dashboard_type": "performance",
            "time_filter": "ALL",
            "org_rating": 5,
        },
    )

    run_case(
        "9. Invalid dashboard type",
        {
            "dashboard_type": "invalid",
        },
        expected_status=400,
    )

    run_case(
        "10. Invalid organization rating",
        {
            "org_rating": 6,
        },
        expected_status=400,
    )
    test_missing_contributor_column()

if __name__ == "__main__":
    main()
