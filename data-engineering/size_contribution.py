import json
import pandas as pd


# ============================================================
# LOAD CSV FILES
# ============================================================

organizations = pd.read_csv("data/organizations.csv")
states = pd.read_csv("data/states.csv")
countries = pd.read_csv("data/countries.csv")

organizations["created_at"] = pd.to_datetime(
    organizations["created_at"],
    errors="coerce"
)

# If is_contributor is missing, create it
if "is_contributor" not in organizations.columns:
    organizations["is_contributor"] = False


# ============================================================
# JOIN ORGANIZATIONS -> STATES -> COUNTRIES
# ============================================================

org_with_state = organizations.merge(
    states,
    on="state_id",
    how="inner"
)

org_with_country = org_with_state.merge(
    countries,
    on="country_id",
    how="inner"
)


# ============================================================
# CALCULATE CHARTS
# ============================================================

def calculate_charts(data):

    # --------------------------------------------------------
    # Organizations By Size
    # --------------------------------------------------------

    size_counts = data.groupby("org_size").size()

    organizations_by_size = [
        {
            "size": size,
            "count": int(count)
        }
        for size, count in size_counts.items()
    ]

    # --------------------------------------------------------
    # Collaborator vs Contributor
    # --------------------------------------------------------

    total_organizations = len(data)

    if total_organizations == 0:

        collaborator_vs_contributor = []

    else:

        collaborator_count = (
            data["is_collaborator"]
            .fillna(False)
            .sum()
        )

        contributor_count = (
            data["is_contributor"]
            .fillna(False)
            .sum()
        )

        collaborator_percentage = (
            collaborator_count
            / total_organizations
            * 100
        )

        contributor_percentage = (
            contributor_count
            / total_organizations
            * 100
        )

        collaborator_vs_contributor = [
            {
                "type": "Collaborator",
                "count": int(collaborator_count),
                "percentage": float(
                    round(
                        collaborator_percentage,
                        1
                    )
                )
            },
            {
                "type": "Contributor",
                "count": int(contributor_count),
                "percentage": float(
                    round(
                        contributor_percentage,
                        1
                    )
                )
            }
        ]

    return {
        "organizations_by_size":
            organizations_by_size,

        "collaborator_vs_contributor":
            collaborator_vs_contributor
    }


# ============================================================
# APPLY COUNTRY / ORGANIZATION TYPE FILTERS
# ============================================================

def apply_filters(
    data,
    country=None,
    organization_type=None
):

    result = data.copy()

    # Country filter
    if country and country != "ALL":

        result = result[
            result["country_code"] == country
        ]

    # Organization type filter
    if (
        organization_type
        and organization_type != "ALL"
    ):

        result = result[
            result["org_type"] == organization_type
        ]

    return result


# ============================================================
# DATE FILTER
# ============================================================

def filter_by_date(
    data,
    start_date,
    end_date
):

    return data[
        (data["created_at"] >= start_date)
        &
        (data["created_at"] <= end_date)
    ]


# ============================================================
# HANDLER
# ============================================================

def handler(event, context):

    if event is None:
        event = {}

    # --------------------------------------------------------
    # READ BODY
    # --------------------------------------------------------

    body = event.get("body")

    if body is None or body == "":

        params = {}

    elif isinstance(body, str):

        try:
            params = json.loads(body)

        except json.JSONDecodeError:

            return {
                "statusCode": 400,
                "body": json.dumps({
                    "error": "Invalid JSON body"
                })
            }

    elif isinstance(body, dict):

        params = body

    else:

        params = {}

    # --------------------------------------------------------
    # READ FILTERS
    # --------------------------------------------------------

    country = params.get("country")

    organization_type = params.get(
        "organization_type"
    )

    # --------------------------------------------------------
    # READ SIZE DATE RANGE
    # --------------------------------------------------------

    size_start_date = params.get(
        "size_start_date"
    )

    size_end_date = params.get(
        "size_end_date"
    )

    # --------------------------------------------------------
    # READ CONTRIBUTION DATE RANGE
    # --------------------------------------------------------

    contribution_start_date = params.get(
        "contribution_start_date"
    )

    contribution_end_date = params.get(
        "contribution_end_date"
    )

    # ========================================================
    # VALIDATE SIZE DATE PAIR
    # ========================================================

    if (
        size_start_date
        and not size_end_date
    ) or (
        size_end_date
        and not size_start_date
    ):

        return {
            "statusCode": 400,
            "body": json.dumps({
                "error": (
                    "Both size_start_date and "
                    "size_end_date are required"
                )
            })
        }

    # ========================================================
    # VALIDATE CONTRIBUTION DATE PAIR
    # ========================================================

    if (
        contribution_start_date
        and not contribution_end_date
    ) or (
        contribution_end_date
        and not contribution_start_date
    ):

        return {
            "statusCode": 400,
            "body": json.dumps({
                "error": (
                    "Both contribution_start_date "
                    "and contribution_end_date "
                    "are required"
                )
            })
        }

    # ========================================================
    # CONVERT AND VALIDATE DATES
    # ========================================================

    try:

        # ----------------------------------------------------
        # Size dates
        # ----------------------------------------------------

        if size_start_date:

            size_start = pd.to_datetime(
                size_start_date
            )

            size_end = pd.to_datetime(
                size_end_date
            )

            if size_start > size_end:

                return {
                    "statusCode": 400,
                    "body": json.dumps({
                        "error": (
                            "size_start_date cannot "
                            "be after size_end_date"
                        )
                    })
                }

        else:

            size_start = None
            size_end = None

        # ----------------------------------------------------
        # Contribution dates
        # ----------------------------------------------------

        if contribution_start_date:

            contribution_start = pd.to_datetime(
                contribution_start_date
            )

            contribution_end = pd.to_datetime(
                contribution_end_date
            )

            if contribution_start > contribution_end:

                return {
                    "statusCode": 400,
                    "body": json.dumps({
                        "error": (
                            "contribution_start_date "
                            "cannot be after "
                            "contribution_end_date"
                        )
                    })
                }

        else:

            contribution_start = None
            contribution_end = None

    except Exception:

        return {
            "statusCode": 400,
            "body": json.dumps({
                "error": "Invalid date format"
            })
        }

    # ========================================================
    # CUSTOM RESPONSE
    # ========================================================

    has_custom_dates = (
        size_start is not None
        or contribution_start is not None
    )

    if has_custom_dates:

        custom_response = {
            "organizations_by_size": [],
            "collaborator_vs_contributor": []
        }

        # ----------------------------------------------------
        # SIZE CUSTOM RANGE
        # ----------------------------------------------------

        if size_start is not None:

            size_data = filter_by_date(
                org_with_country,
                size_start,
                size_end
            )

            size_data = apply_filters(
                size_data,
                country,
                organization_type
            )

            size_chart = calculate_charts(
                size_data
            )

            custom_response[
                "organizations_by_size"
            ] = size_chart[
                "organizations_by_size"
            ]

        # ----------------------------------------------------
        # CONTRIBUTION CUSTOM RANGE
        # ----------------------------------------------------

        if contribution_start is not None:

            contribution_data = filter_by_date(
                org_with_country,
                contribution_start,
                contribution_end
            )

            contribution_data = apply_filters(
                contribution_data,
                country,
                organization_type
            )

            contribution_chart = calculate_charts(
                contribution_data
            )

            custom_response[
                "collaborator_vs_contributor"
            ] = contribution_chart[
                "collaborator_vs_contributor"
            ]

        return {
            "statusCode": 200,
            "body": json.dumps({
                "Custom": custom_response
            })
        }

    # ========================================================
    # NORMAL 7D / 30D / 1Y / ALL
    # ========================================================

    today = pd.Timestamp.now()

    seven_days_ago = (
        today - pd.Timedelta(days=7)
    )

    thirty_days_ago = (
        today - pd.Timedelta(days=30)
    )

    one_year_ago = (
        today - pd.Timedelta(days=365)
    )

    filtered_data = apply_filters(
        org_with_country,
        country,
        organization_type
    )

    # ========================================================
    # 7D
    # ========================================================

    data_7d = filter_by_date(
        filtered_data,
        seven_days_ago,
        today
    )

    chart_7d = calculate_charts(
        data_7d
    )

    # ========================================================
    # 30D
    # ========================================================

    data_30d = filter_by_date(
        filtered_data,
        thirty_days_ago,
        today
    )

    chart_30d = calculate_charts(
        data_30d
    )

    # ========================================================
    # 1Y
    # ========================================================

    data_1y = filter_by_date(
        filtered_data,
        one_year_ago,
        today
    )

    chart_1y = calculate_charts(
        data_1y
    )

    # ========================================================
    # ALL
    # ========================================================

    chart_all = calculate_charts(
        filtered_data
    )

    # ========================================================
    # FINAL RESPONSE
    # ========================================================

    response = {
        "7D": chart_7d,
        "30D": chart_30d,
        "1Y": chart_1y,
        "All": chart_all,
        "Custom": {
            "organizations_by_size": [],
            "collaborator_vs_contributor": []
        }
    }

    return {
        "statusCode": 200,
        "body": json.dumps(response)
    }


# ============================================================
# LOCAL TESTING
# ============================================================

if __name__ == "__main__":

    # ========================================================
    # TEST 1 - NO BODY
    # ========================================================

    print("\n===== TEST 1: NO BODY =====")

    result = handler({}, None)

    print(
        json.dumps(
            json.loads(result["body"]),
            indent=2
        )
    )

    # ========================================================
    # TEST 2 - COUNTRY FILTER
    # ========================================================

    print("\n===== TEST 2: COUNTRY FILTER =====")

    event = {
        "body": json.dumps({
            "country": "USA"
        })
    }

    result = handler(event, None)

    print(
        json.dumps(
            json.loads(result["body"]),
            indent=2
        )
    )

    # ========================================================
    # TEST 3 - ORGANIZATION TYPE
    # ========================================================

    print(
        "\n===== TEST 3: ORGANIZATION TYPE ====="
    )

    event = {
        "body": json.dumps({
            "organization_type": "non_profit"
        })
    }

    result = handler(event, None)

    print(
        json.dumps(
            json.loads(result["body"]),
            indent=2
        )
    )

    # ========================================================
    # TEST 4 - SIZE CUSTOM
    # ========================================================

    print("\n===== TEST 4: SIZE CUSTOM =====")

    event = {
        "body": json.dumps({
            "size_start_date": "2026-09-01",
            "size_end_date": "2026-09-30"
        })
    }

    result = handler(event, None)

    print(
        json.dumps(
            json.loads(result["body"]),
            indent=2
        )
    )

    # ========================================================
    # TEST 5 - CONTRIBUTION CUSTOM
    # ========================================================

    print(
        "\n===== TEST 5: CONTRIBUTION CUSTOM ====="
    )

    event = {
        "body": json.dumps({
            "contribution_start_date": "2026-09-01",
            "contribution_end_date": "2026-09-30"
        })
    }

    result = handler(event, None)

    print(
        json.dumps(
            json.loads(result["body"]),
            indent=2
        )
    )

    # ========================================================
    # TEST 6 - BOTH CUSTOM
    # ========================================================

    print("\n===== TEST 6: BOTH CUSTOM =====")

    event = {
        "body": json.dumps({
            "size_start_date": "2026-09-01",
            "size_end_date": "2026-09-30",
            "contribution_start_date": "2026-09-01",
            "contribution_end_date": "2026-09-30"
        })
    }

    result = handler(event, None)

    print(
        json.dumps(
            json.loads(result["body"]),
            indent=2
        )
    )

    # ========================================================
    # TEST 7 - INCOMPLETE SIZE DATE
    # ========================================================

    print(
        "\n===== TEST 7: INCOMPLETE SIZE DATE ====="
    )

    event = {
        "body": json.dumps({
            "size_start_date": "2026-09-01"
        })
    }

    result = handler(event, None)

    print(result)

    # ========================================================
    # TEST 8 - INVALID DATE
    # ========================================================

    print(
        "\n===== TEST 8: INVALID DATE ====="
    )

    event = {
        "body": json.dumps({
            "size_start_date": "wrong-date",
            "size_end_date": "2026-09-30"
        })
    }

    result = handler(event, None)

    print(result)

    # ========================================================
    # TEST 9 - START DATE AFTER END DATE
    # ========================================================

    print(
        "\n===== TEST 9: START DATE AFTER END DATE ====="
    )

    event = {
        "body": json.dumps({
            "size_start_date": "2026-09-30",
            "size_end_date": "2026-09-01"
        })
    }

    result = handler(event, None)

    print(result)

    # ========================================================
    # TEST 10 - ALL FILTER
    # ========================================================

    print(
        "\n===== TEST 10: ALL FILTER ====="
    )

    event = {
        "body": json.dumps({
            "country": "ALL",
            "organization_type": "ALL"
        })
    }

    result = handler(event, None)

    print(
        json.dumps(
            json.loads(result["body"]),
            indent=2
        )
    )

    # ========================================================
    # TEST 11 - EMPTY DATE RANGE
    # ========================================================

    print(
        "\n===== TEST 11: EMPTY DATE RANGE ====="
    )

    event = {
        "body": json.dumps({
            "size_start_date": "2025-01-01",
            "size_end_date": "2025-01-02"
        })
    }

    result = handler(event, None)

    print(
        json.dumps(
            json.loads(result["body"]),
            indent=2
        )
    )

        # ========================================================
    # TEST 12 - ONE ROW CSV
    # ========================================================

    print("\n===== TEST 12: ONE ROW CSV =====")

    one_row_data = org_with_country.iloc[[0]].copy()

    result = calculate_charts(one_row_data)

    print(
        json.dumps(
            result,
            indent=2
        )
    )

    # ========================================================
    # TEST 13 - MISSING is_contributor COLUMN
    # ========================================================

    print(
        "\n===== TEST 13: MISSING is_contributor ====="
    )

    missing_contributor_data = org_with_country.drop(
        columns=["is_contributor"]
    ).copy()

    # Add it back as False, exactly like the main code does
    if "is_contributor" not in missing_contributor_data.columns:
        missing_contributor_data["is_contributor"] = False

    result = calculate_charts(
        missing_contributor_data
    )

    print(
        json.dumps(
            result,
            indent=2
        )
    )