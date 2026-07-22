import json
import psycopg2
import pandas as pd
from datetime import datetime, timedelta
import os
import boto3

VIRGINIA_TABLE_ORGANIZATIONS = "virginia_dev_saayam_rdbms.organizations"
VIRGINIA_TABLE_STATE = "virginia_dev_saayam_rdbms.state"

IRELAND_TABLE_ORGANIZATIONS = "ireland_dev_saayam_rdbms.organizations"
IRELAND_TABLE_STATE = "ireland_dev_saayam_rdbms.state"


def parse_event_body(event):
    if not event:
        return {}
    body = event.get("body")
    if body is None:
        return event
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    if isinstance(body, dict):
        return body
    return {}


def build_date_filter(time_filter, start_date=None, end_date=None, column="o.created_at"):
    if time_filter == "7D":
        return f"AND {column} >= CURRENT_DATE - INTERVAL '7 days'"
    elif time_filter == "30D":
        return f"AND {column} >= CURRENT_DATE - INTERVAL '30 days'"
    elif time_filter == "1Y":
        return f"AND {column} >= CURRENT_DATE - INTERVAL '1 year'"
    elif time_filter == "ALL":
        return ""
    elif time_filter == "CUSTOM":
        if start_date and end_date:
            return f"AND {column} BETWEEN '{start_date}' AND '{end_date}'"
    return ""


def get_group_by_expr(group_by):
    if group_by == "daily":
        return "TO_CHAR(DATE_TRUNC('day', o.created_at), 'YYYY-MM-DD')"
    elif group_by == "weekly":
        return "TO_CHAR(DATE_TRUNC('week', o.created_at), 'YYYY-MM-DD')"
    elif group_by == "monthly":
        return "TO_CHAR(DATE_TRUNC('month', o.created_at), 'YYYY-MM')"
    elif group_by == "yearly":
        return "TO_CHAR(DATE_TRUNC('year', o.created_at), 'YYYY')"
    return "TO_CHAR(DATE_TRUNC('month', o.created_at), 'YYYY-MM')"


def build_optional_filters(filters):
    clauses = []
    params = []
    if filters.get("org_type"):
        clauses.append("AND o.org_type = %s")
        params.append(filters["org_type"])
    if filters.get("org_size"):
        clauses.append("AND o.org_size = %s")
        params.append(filters["org_size"])
    if filters.get("state_id"):
        clauses.append("AND o.state_id = %s")
        params.append(filters["state_id"])
    if filters.get("city_name"):
        clauses.append("AND LOWER(o.city_name) = LOWER(%s)")
        params.append(filters["city_name"])
    if filters.get("org_rating"):
        clauses.append("AND o.org_rating = %s")
        params.append(filters["org_rating"])
    if filters.get("is_collaborator") is not None:
        clauses.append("AND o.is_collaborator = %s")
        params.append(filters["is_collaborator"])
    if filters.get("is_contributor") is not None:
        clauses.append("AND o.is_contributor = %s")
        params.append(filters["is_contributor"])
    return " ".join(clauses), params


def get_organization_overview(cursor, org_table, state_table, date_filter, group_by, optional_filter, optional_params):
    try:
        group_expr = get_group_by_expr(group_by)

        base_where = f"WHERE 1=1 {date_filter} {optional_filter}"

        query_summary = f"""
        SELECT
            COUNT(*) AS total_organizations,
            COUNT(*) FILTER (WHERE o.org_type = 'non_profit') AS non_profit_organizations,
            COUNT(*) FILTER (WHERE o.org_type = 'for_profit') AS for_profit_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator = TRUE) AS collaborator_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator = FALSE OR o.is_collaborator IS NULL) AS non_collaborator_organizations,
            COUNT(*) FILTER (WHERE o.is_contributor = TRUE) AS contributor_organizations,
            COUNT(*) FILTER (WHERE o.is_contributor = FALSE OR o.is_contributor IS NULL) AS non_contributor_organizations
        FROM {org_table} o
        {base_where}
        """
        cursor.execute(query_summary, optional_params)
        row = cursor.fetchone()
        summary = {
            "total_organizations": int(row[0]),
            "non_profit_organizations": int(row[1]),
            "for_profit_organizations": int(row[2]),
            "collaborator_organizations": int(row[3]),
            "non_collaborator_organizations": int(row[4]),
            "contributor_organizations": int(row[5]),
            "non_contributor_organizations": int(row[6])
        }

        query_trend = f"""
        SELECT {group_expr} AS period, COUNT(*) AS count
        FROM {org_table} o
        {base_where}
        GROUP BY 1 ORDER BY 1 ASC
        """
        cursor.execute(query_trend, optional_params)
        activity_trend = [{"period": r[0], "count": int(r[1])} for r in cursor.fetchall()]

        query_type = f"""
        SELECT COALESCE(o.org_type::TEXT, 'unknown') AS org_type, COUNT(*) AS count
        FROM {org_table} o
        {base_where}
        GROUP BY 1 ORDER BY count DESC
        """
        cursor.execute(query_type, optional_params)
        by_type = [{"org_type": r[0], "count": int(r[1])} for r in cursor.fetchall()]

        query_size = f"""
        SELECT COALESCE(o.org_size::TEXT, 'unknown') AS org_size, COUNT(*) AS count
        FROM {org_table} o
        {base_where}
        GROUP BY 1 ORDER BY count DESC
        """
        cursor.execute(query_size, optional_params)
        by_size = [{"org_size": r[0], "count": int(r[1])} for r in cursor.fetchall()]

        query_location = f"""
        SELECT COALESCE(s.state_name, 'Unknown') AS state, o.city_name AS city, COUNT(*) AS count
        FROM {org_table} o
        LEFT JOIN {state_table} s ON o.state_id = s.state_id
        {base_where}
        GROUP BY 1, 2 ORDER BY count DESC
        """
        cursor.execute(query_location, optional_params)
        by_location = [{"state": r[0], "city": r[1], "count": int(r[2])} for r in cursor.fetchall()]

        query_collab = f"""
        SELECT
            COUNT(*) FILTER (WHERE o.is_collaborator = TRUE) AS collaborator,
            COUNT(*) FILTER (WHERE o.is_collaborator = FALSE OR o.is_collaborator IS NULL) AS non_collaborator
        FROM {org_table} o
        {base_where}
        """
        cursor.execute(query_collab, optional_params)
        collab_row = cursor.fetchone()
        collaborator_distribution = [
            {"type": "collaborator", "count": int(collab_row[0])},
            {"type": "non_collaborator", "count": int(collab_row[1])}
        ]

        query_contrib = f"""
        SELECT
            COUNT(*) FILTER (WHERE o.is_contributor = TRUE) AS contributor,
            COUNT(*) FILTER (WHERE o.is_contributor = FALSE OR o.is_contributor IS NULL) AS non_contributor
        FROM {org_table} o
        {base_where}
        """
        cursor.execute(query_contrib, optional_params)
        contrib_row = cursor.fetchone()
        contributor_distribution = [
            {"type": "contributor", "count": int(contrib_row[0])},
            {"type": "non_contributor", "count": int(contrib_row[1])}
        ]

        return {
            "summary": summary,
            "organization_activity_trend": activity_trend,
            "organizations_by_type": by_type,
            "organizations_by_size": by_size,
            "organizations_by_location": by_location,
            "collaborator_distribution": collaborator_distribution,
            "contributor_distribution": contributor_distribution
        }

    except Exception as e:
        print("Error in get_organization_overview:", str(e))
        return {
            "summary": {},
            "organization_activity_trend": [],
            "organizations_by_type": [],
            "organizations_by_size": [],
            "organizations_by_location": [],
            "collaborator_distribution": [],
            "contributor_distribution": []
        }


def get_organization_performance(cursor, org_table, date_filter, optional_filter, optional_params):
    try:
        base_where = f"WHERE 1=1 {date_filter} {optional_filter}"

        query_summary = f"""
        SELECT
            ROUND(AVG(o.org_rating)::NUMERIC, 2) AS average_rating,
            COUNT(*) FILTER (WHERE o.org_rating IS NOT NULL) AS rated_organizations,
            COUNT(*) FILTER (WHERE o.org_rating IS NULL) AS unrated_organizations,
            COUNT(*) FILTER (WHERE o.org_rating = 5) AS five_star_organizations
        FROM {org_table} o
        {base_where}
        """
        cursor.execute(query_summary, optional_params)
        row = cursor.fetchone()
        summary = {
            "average_rating": float(row[0]) if row[0] else 0,
            "rated_organizations": int(row[1]),
            "unrated_organizations": int(row[2]),
            "five_star_organizations": int(row[3])
        }

        query_rating_dist = f"""
        SELECT o.org_rating, COUNT(*) AS count
        FROM {org_table} o
        {base_where} AND o.org_rating IS NOT NULL
        GROUP BY 1 ORDER BY 1 ASC
        """
        cursor.execute(query_rating_dist, optional_params)
        rating_distribution = [{"rating": int(r[0]), "count": int(r[1])} for r in cursor.fetchall()]

        query_top_rated = f"""
        SELECT o.org_id, o.org_name, o.org_rating, o.org_type::TEXT, o.org_size::TEXT
        FROM {org_table} o
        {base_where} AND o.org_rating IS NOT NULL
        ORDER BY o.org_rating DESC, o.org_name ASC
        LIMIT 10
        """
        cursor.execute(query_top_rated, optional_params)
        top_rated = [
            {"org_id": r[0], "org_name": r[1], "rating": int(r[2]), "org_type": r[3], "org_size": r[4]}
            for r in cursor.fetchall()
        ]

        query_top_collab = f"""
        SELECT o.org_id, o.org_name, o.org_rating, o.org_type::TEXT
        FROM {org_table} o
        {base_where} AND o.is_collaborator = TRUE
        ORDER BY COALESCE(o.org_rating, 0) DESC, o.org_name ASC
        LIMIT 10
        """
        cursor.execute(query_top_collab, optional_params)
        top_collaborators = [
            {"org_id": r[0], "org_name": r[1], "rating": int(r[2]) if r[2] else None, "org_type": r[3]}
            for r in cursor.fetchall()
        ]

        query_top_contrib = f"""
        SELECT o.org_id, o.org_name, o.org_rating, o.org_type::TEXT
        FROM {org_table} o
        {base_where} AND o.is_contributor = TRUE
        ORDER BY COALESCE(o.org_rating, 0) DESC, o.org_name ASC
        LIMIT 10
        """
        cursor.execute(query_top_contrib, optional_params)
        top_contributors = [
            {"org_id": r[0], "org_name": r[1], "rating": int(r[2]) if r[2] else None, "org_type": r[3]}
            for r in cursor.fetchall()
        ]

        query_rating_type = f"""
        SELECT o.org_type::TEXT, o.org_rating, COUNT(*) AS count
        FROM {org_table} o
        {base_where} AND o.org_rating IS NOT NULL
        GROUP BY 1, 2 ORDER BY 1, 2
        """
        cursor.execute(query_rating_type, optional_params)
        ratings_by_type = [
            {"org_type": r[0], "rating": int(r[1]), "count": int(r[2])}
            for r in cursor.fetchall()
        ]

        query_rating_size = f"""
        SELECT o.org_size::TEXT, o.org_rating, COUNT(*) AS count
        FROM {org_table} o
        {base_where} AND o.org_rating IS NOT NULL
        GROUP BY 1, 2 ORDER BY 1, 2
        """
        cursor.execute(query_rating_size, optional_params)
        ratings_by_size = [
            {"org_size": r[0], "rating": int(r[1]), "count": int(r[2])}
            for r in cursor.fetchall()
        ]

        return {
            "summary": summary,
            "rating_distribution": rating_distribution,
            "top_rated_organizations": top_rated,
            "top_collaborator_organizations": top_collaborators,
            "top_contributor_organizations": top_contributors,
            "ratings_by_organization_type": ratings_by_type,
            "ratings_by_organization_size": ratings_by_size
        }

    except Exception as e:
        print("Error in get_organization_performance:", str(e))
        return {
            "summary": {},
            "rating_distribution": [],
            "top_rated_organizations": [],
            "top_collaborator_organizations": [],
            "top_contributor_organizations": [],
            "ratings_by_organization_type": [],
            "ratings_by_organization_size": []
        }


def merge_overview(overview_v, overview_i):
    merged_summary = {}
    for key in overview_v.get("summary", {}):
        merged_summary[key] = overview_v["summary"].get(key, 0) + overview_i["summary"].get(key, 0)

    return {
        "summary": merged_summary,
        "organization_activity_trend": merge_period_list(
            overview_v.get("organization_activity_trend", []),
            overview_i.get("organization_activity_trend", [])
        ),
        "organizations_by_type": merge_keyed_list(
            overview_v.get("organizations_by_type", []),
            overview_i.get("organizations_by_type", []),
            "org_type"
        ),
        "organizations_by_size": merge_keyed_list(
            overview_v.get("organizations_by_size", []),
            overview_i.get("organizations_by_size", []),
            "org_size"
        ),
        "organizations_by_location": (
            overview_v.get("organizations_by_location", [])
            + overview_i.get("organizations_by_location", [])
        ),
        "collaborator_distribution": merge_keyed_list(
            overview_v.get("collaborator_distribution", []),
            overview_i.get("collaborator_distribution", []),
            "type"
        ),
        "contributor_distribution": merge_keyed_list(
            overview_v.get("contributor_distribution", []),
            overview_i.get("contributor_distribution", []),
            "type"
        )
    }


def merge_performance(perf_v, perf_i):
    summary_v = perf_v.get("summary", {})
    summary_i = perf_i.get("summary", {})
    rated_v = summary_v.get("rated_organizations", 0)
    rated_i = summary_i.get("rated_organizations", 0)
    total_rated = rated_v + rated_i
    avg_v = summary_v.get("average_rating", 0)
    avg_i = summary_i.get("average_rating", 0)
    merged_avg = round(
        (avg_v * rated_v + avg_i * rated_i) / total_rated, 2
    ) if total_rated > 0 else 0

    merged_summary = {
        "average_rating": merged_avg,
        "rated_organizations": total_rated,
        "unrated_organizations": summary_v.get("unrated_organizations", 0) + summary_i.get("unrated_organizations", 0),
        "five_star_organizations": summary_v.get("five_star_organizations", 0) + summary_i.get("five_star_organizations", 0)
    }

    return {
        "summary": merged_summary,
        "rating_distribution": merge_keyed_list(
            perf_v.get("rating_distribution", []),
            perf_i.get("rating_distribution", []),
            "rating"
        ),
        "top_rated_organizations": (
            perf_v.get("top_rated_organizations", [])
            + perf_i.get("top_rated_organizations", [])
        ),
        "top_collaborator_organizations": (
            perf_v.get("top_collaborator_organizations", [])
            + perf_i.get("top_collaborator_organizations", [])
        ),
        "top_contributor_organizations": (
            perf_v.get("top_contributor_organizations", [])
            + perf_i.get("top_contributor_organizations", [])
        ),
        "ratings_by_organization_type": merge_composite_list(
            perf_v.get("ratings_by_organization_type", []),
            perf_i.get("ratings_by_organization_type", []),
            ["org_type", "rating"]
        ),
        "ratings_by_organization_size": merge_composite_list(
            perf_v.get("ratings_by_organization_size", []),
            perf_i.get("ratings_by_organization_size", []),
            ["org_size", "rating"]
        )
    }


def merge_period_list(list1, list2):
    merged = {}
    for row in list1 + list2:
        period = row["period"]
        merged[period] = merged.get(period, 0) + row["count"]
    return [{"period": p, "count": merged[p]} for p in sorted(merged.keys())]


def merge_keyed_list(list1, list2, key_field):
    merged = {}
    for row in list1 + list2:
        k = row[key_field]
        merged[k] = merged.get(k, 0) + row["count"]
    return [{key_field: k, "count": merged[k]} for k in sorted(merged.keys())]


def merge_composite_list(list1, list2, key_fields):
    merged = {}
    for row in list1 + list2:
        k = tuple(row[f] for f in key_fields)
        merged[k] = merged.get(k, 0) + row["count"]
    result = []
    for k in sorted(merged.keys()):
        entry = {key_fields[i]: k[i] for i in range(len(key_fields))}
        entry["count"] = merged[k]
        result.append(entry)
    return result


def lambda_handler(event, context):
    conn_V = None
    cursor_V = None
    conn_I = None
    cursor_I = None

    safe_response = {
        "organization_overview": {
            "summary": {},
            "organization_activity_trend": [],
            "organizations_by_type": [],
            "organizations_by_size": [],
            "organizations_by_location": [],
            "collaborator_distribution": [],
            "contributor_distribution": []
        },
        "organization_performance": {
            "summary": {},
            "rating_distribution": [],
            "top_rated_organizations": [],
            "top_collaborator_organizations": [],
            "top_contributor_organizations": [],
            "ratings_by_organization_type": [],
            "ratings_by_organization_size": []
        }
    }

    try:
        VIRGINIA_DB_CONFIG = get_db_config("Virginia")
        IRELAND_DB_CONFIG = get_db_config("Ireland")
        conn_V = psycopg2.connect(**VIRGINIA_DB_CONFIG)
        cursor_V = conn_V.cursor()
        print("Virginia database connected successfully.")
        conn_I = psycopg2.connect(**IRELAND_DB_CONFIG)
        cursor_I = conn_I.cursor()
        print("Ireland database connected successfully.")

        request_body = parse_event_body(event)
        time_filter = request_body.get("time_filter", "ALL")
        start_date = request_body.get("start_date", None)
        end_date = request_body.get("end_date", None)
        group_by = request_body.get("group_by", "monthly")

        filters = {
            "org_type": request_body.get("org_type"),
            "org_size": request_body.get("org_size"),
            "state_id": request_body.get("state_id"),
            "city_name": request_body.get("city_name"),
            "org_rating": request_body.get("org_rating"),
            "is_collaborator": request_body.get("is_collaborator"),
            "is_contributor": request_body.get("is_contributor"),
        }

        date_filter = build_date_filter(time_filter, start_date, end_date)
        optional_filter, optional_params = build_optional_filters(filters)

        overview_v = get_organization_overview(
            cursor_V, VIRGINIA_TABLE_ORGANIZATIONS, VIRGINIA_TABLE_STATE,
            date_filter, group_by, optional_filter, optional_params
        )
        overview_i = get_organization_overview(
            cursor_I, IRELAND_TABLE_ORGANIZATIONS, IRELAND_TABLE_STATE,
            date_filter, group_by, optional_filter, optional_params
        )

        performance_v = get_organization_performance(
            cursor_V, VIRGINIA_TABLE_ORGANIZATIONS,
            date_filter, optional_filter, optional_params
        )
        performance_i = get_organization_performance(
            cursor_I, IRELAND_TABLE_ORGANIZATIONS,
            date_filter, optional_filter, optional_params
        )

        response_data = {
            "organization_overview": merge_overview(overview_v, overview_i),
            "organization_performance": merge_performance(performance_v, performance_i)
        }

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,Authorization",
                "Access-Control-Allow-Methods": "GET,POST,OPTIONS"
            },
            "body": json.dumps(response_data)
        }

    except Exception as e:
        print("ERROR:", str(e))
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,Authorization",
                "Access-Control-Allow-Methods": "GET,POST,OPTIONS"
            },
            "body": json.dumps(safe_response)
        }
    finally:
        if cursor_V:
            cursor_V.close()
        if conn_V:
            conn_V.close()
        print("Virginia Database connection closed")
        if cursor_I:
            cursor_I.close()
        if conn_I:
            conn_I.close()
        print("Ireland Database connection closed")


def get_db_config(db):
    ssm = boto3.client("ssm", region_name="us-east-1")

    if db == "Virginia":
        parameter_name = "/dev/saayam/db/Virginia/Analytics/user"
    elif db == "Ireland":
        parameter_name = "/dev/saayam/db/Ireland/Analytics/user"
    else:
        raise ValueError("Database must be either Virginia or Ireland")

    response = ssm.get_parameter(
        Name=parameter_name,
        WithDecryption=True
    )

    config = response["Parameter"]["Value"]
    config_list = [line.strip() for line in config.splitlines()]

    host = config_list[1].split()[1][1:-2]
    port = int(config_list[5].split()[1][:-1])
    dbname = config_list[4].split()[2][1:-2]
    user = config_list[2].split()[1][1:-2]
    password = config_list[3].split()[1][1:-2]

    return {
        "host": host,
        "port": port,
        "dbname": dbname,
        "user": user,
        "password": password
    }


def apply_date_filter_local(df, time_filter, start_date=None, end_date=None):
    today = pd.Timestamp.now().normalize()
    if time_filter == "7D":
        return df[df["created_at"] >= today - pd.Timedelta(days=7)]
    elif time_filter == "30D":
        return df[df["created_at"] >= today - pd.Timedelta(days=30)]
    elif time_filter == "1Y":
        return df[df["created_at"] >= today - pd.DateOffset(years=1)]
    elif time_filter == "ALL":
        return df
    elif time_filter == "CUSTOM":
        if start_date and end_date:
            return df[
                (df["created_at"] >= pd.Timestamp(start_date))
                & (df["created_at"] <= pd.Timestamp(end_date))
            ]
    return df


def apply_optional_filters_local(df, filters):
    if filters.get("org_type"):
        df = df[df["org_type"] == filters["org_type"]]
    if filters.get("org_size"):
        df = df[df["org_size"] == filters["org_size"]]
    if filters.get("state_id"):
        df = df[df["state_id"] == filters["state_id"]]
    if filters.get("city_name"):
        df = df[df["city_name"].str.lower() == filters["city_name"].lower()]
    if filters.get("org_rating"):
        df = df[df["org_rating"] == filters["org_rating"]]
    if filters.get("is_collaborator") is not None:
        df = df[df["is_collaborator"] == filters["is_collaborator"]]
    if filters.get("is_contributor") is not None:
        df = df[df["is_contributor"] == filters["is_contributor"]]
    return df


def get_overview_local(df, state_df, group_by):
    summary = {
        "total_organizations": len(df),
        "non_profit_organizations": int((df["org_type"] == "non_profit").sum()),
        "for_profit_organizations": int((df["org_type"] == "for_profit").sum()),
        "collaborator_organizations": int((df["is_collaborator"] == True).sum()),
        "non_collaborator_organizations": int((df["is_collaborator"] != True).sum()),
        "contributor_organizations": int((df["is_contributor"] == True).sum()),
        "non_contributor_organizations": int((df["is_contributor"] != True).sum()),
    }

    if group_by == "daily":
        df["period"] = df["created_at"].dt.strftime("%Y-%m-%d")
    elif group_by == "weekly":
        df["period"] = df["created_at"].dt.to_period("W").apply(lambda x: x.start_time.strftime("%Y-%m-%d"))
    elif group_by == "monthly":
        df["period"] = df["created_at"].dt.strftime("%Y-%m")
    elif group_by == "yearly":
        df["period"] = df["created_at"].dt.strftime("%Y")
    else:
        df["period"] = df["created_at"].dt.strftime("%Y-%m")

    trend = df.groupby("period").size().reset_index(name="count").sort_values("period")
    activity_trend = [{"period": r["period"], "count": int(r["count"])} for _, r in trend.iterrows()]

    by_type = df.groupby("org_type").size().reset_index(name="count").sort_values("count", ascending=False)
    organizations_by_type = [{"org_type": r["org_type"], "count": int(r["count"])} for _, r in by_type.iterrows()]

    by_size = df.groupby("org_size").size().reset_index(name="count").sort_values("count", ascending=False)
    organizations_by_size = [{"org_size": r["org_size"], "count": int(r["count"])} for _, r in by_size.iterrows()]

    merged_loc = df.merge(state_df[["state_id", "state_name"]], on="state_id", how="left")
    merged_loc["state_name"] = merged_loc["state_name"].fillna("Unknown")
    by_loc = merged_loc.groupby(["state_name", "city_name"]).size().reset_index(name="count").sort_values("count", ascending=False)
    organizations_by_location = [
        {"state": r["state_name"], "city": r["city_name"], "count": int(r["count"])}
        for _, r in by_loc.iterrows()
    ]

    collab_count = int((df["is_collaborator"] == True).sum())
    non_collab_count = int((df["is_collaborator"] != True).sum())
    collaborator_distribution = [
        {"type": "collaborator", "count": collab_count},
        {"type": "non_collaborator", "count": non_collab_count}
    ]

    contrib_count = int((df["is_contributor"] == True).sum())
    non_contrib_count = int((df["is_contributor"] != True).sum())
    contributor_distribution = [
        {"type": "contributor", "count": contrib_count},
        {"type": "non_contributor", "count": non_contrib_count}
    ]

    return {
        "summary": summary,
        "organization_activity_trend": activity_trend,
        "organizations_by_type": organizations_by_type,
        "organizations_by_size": organizations_by_size,
        "organizations_by_location": organizations_by_location,
        "collaborator_distribution": collaborator_distribution,
        "contributor_distribution": contributor_distribution
    }


def get_performance_local(df):
    rated = df[df["org_rating"].notna()]
    avg_rating = round(float(rated["org_rating"].mean()), 2) if len(rated) > 0 else 0

    summary = {
        "average_rating": avg_rating,
        "rated_organizations": len(rated),
        "unrated_organizations": int(df["org_rating"].isna().sum()),
        "five_star_organizations": int((df["org_rating"] == 5).sum())
    }

    rating_dist = rated.groupby("org_rating").size().reset_index(name="count").sort_values("org_rating")
    rating_distribution = [{"rating": int(r["org_rating"]), "count": int(r["count"])} for _, r in rating_dist.iterrows()]

    top_rated_df = rated.sort_values(["org_rating", "org_name"], ascending=[False, True]).head(10)
    top_rated = [
        {"org_id": r["org_id"], "org_name": r["org_name"], "rating": int(r["org_rating"]),
         "org_type": r["org_type"], "org_size": r["org_size"]}
        for _, r in top_rated_df.iterrows()
    ]

    collab_df = df[df["is_collaborator"] == True].copy()
    collab_df["rating_sort"] = collab_df["org_rating"].fillna(0)
    top_collab_df = collab_df.sort_values(["rating_sort", "org_name"], ascending=[False, True]).head(10)
    top_collaborators = [
        {"org_id": r["org_id"], "org_name": r["org_name"],
         "rating": int(r["org_rating"]) if pd.notna(r["org_rating"]) else None,
         "org_type": r["org_type"]}
        for _, r in top_collab_df.iterrows()
    ]

    contrib_df = df[df["is_contributor"] == True].copy()
    contrib_df["rating_sort"] = contrib_df["org_rating"].fillna(0)
    top_contrib_df = contrib_df.sort_values(["rating_sort", "org_name"], ascending=[False, True]).head(10)
    top_contributors = [
        {"org_id": r["org_id"], "org_name": r["org_name"],
         "rating": int(r["org_rating"]) if pd.notna(r["org_rating"]) else None,
         "org_type": r["org_type"]}
        for _, r in top_contrib_df.iterrows()
    ]

    rt = rated.groupby(["org_type", "org_rating"]).size().reset_index(name="count").sort_values(["org_type", "org_rating"])
    ratings_by_type = [
        {"org_type": r["org_type"], "rating": int(r["org_rating"]), "count": int(r["count"])}
        for _, r in rt.iterrows()
    ]

    rs = rated.groupby(["org_size", "org_rating"]).size().reset_index(name="count").sort_values(["org_size", "org_rating"])
    ratings_by_size = [
        {"org_size": r["org_size"], "rating": int(r["org_rating"]), "count": int(r["count"])}
        for _, r in rs.iterrows()
    ]

    return {
        "summary": summary,
        "rating_distribution": rating_distribution,
        "top_rated_organizations": top_rated,
        "top_collaborator_organizations": top_collaborators,
        "top_contributor_organizations": top_contributors,
        "ratings_by_organization_type": ratings_by_type,
        "ratings_by_organization_size": ratings_by_size
    }


def run_local():
    sql_dir = os.path.join(os.path.dirname(__file__), "..", "sql")

    org_df = pd.read_csv(os.path.join(sql_dir, "organizations.csv"))
    state_df = pd.read_csv(os.path.join(sql_dir, "state.csv"))

    org_df["created_at"] = pd.to_datetime(org_df["created_at"])
    org_df["last_updated_at"] = pd.to_datetime(org_df["last_updated_at"])
    org_df["org_rating"] = pd.to_numeric(org_df["org_rating"], errors="coerce")
    org_df["is_collaborator"] = org_df["is_collaborator"].map({"TRUE": True, "FALSE": False, True: True, False: False})
    org_df["is_contributor"] = org_df["is_contributor"].map({"TRUE": True, "FALSE": False, True: True, False: False})

    test_cases = [
        {"time_filter": "7D", "group_by": "daily"},
        {"time_filter": "30D", "group_by": "daily"},
        {"time_filter": "1Y", "group_by": "monthly"},
        {"time_filter": "ALL", "group_by": "monthly"},
        {
            "time_filter": "CUSTOM",
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
            "group_by": "monthly"
        },
    ]

    for test in test_cases:
        time_filter = test.get("time_filter", "ALL")
        start_date = test.get("start_date")
        end_date = test.get("end_date")
        group_by = test.get("group_by", "monthly")

        filtered = apply_date_filter_local(org_df.copy(), time_filter, start_date, end_date)
        filtered = apply_optional_filters_local(filtered, {})

        overview = get_overview_local(filtered.copy(), state_df, group_by)
        performance = get_performance_local(filtered.copy())

        response = {
            "organization_overview": overview,
            "organization_performance": performance
        }

        print(f"\n=== Test: time_filter={time_filter}, group_by={group_by} ===")
        print(json.dumps(response, indent=2))


if __name__ == "__main__":
    run_local()
