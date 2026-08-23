import json
import psycopg2
from psycopg2.extras import RealDictCursor

SCHEMA_NAME = "virginia_dev_saayam_rdbms"


# ==========================================================
# Response Structure
# ==========================================================

def get_default_response():
    return {
        "summary": {
            "total_organizations": 0,
            "total_collaborators": 0,
            "total_contributors": 0,
            "average_org_rating": 0
        },

        "growth_trend": [],

        "organizations_by_location": [],

        "organizations_by_size": [],

        "collaborator_vs_contributor": [],

        "rating_distribution": [],

        "organization_type_distribution": []
    }



# ==========================================================
# API Response Wrapper
# ==========================================================

def build_response(status_code, body):

    return {

        "statusCode": status_code,

        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },

        "body": json.dumps(body, default=str)

    }



# ==========================================================
# Database Connection
# ==========================================================

def get_db_connection():

    return psycopg2.connect(

        host="localhost",

        database="Saayam",

        user="postgres",

        password="Saayam8Tec*",

        port="5432"

    )


# ==========================================================
# Filter Builder
# ==========================================================

def build_filters(filters):

    conditions = []
    params = []

    # -----------------------------
    # Organization Type
    # -----------------------------
    organization_type = filters.get("organization_type")

    if organization_type and organization_type.upper() != "ALL":

        organization_type_map = {
            "non_profit": "Non-Profit",
            "for_profit": "For-profit"
        }

        normalized_org_type = organization_type_map.get(
            organization_type.lower()
        )

        if normalized_org_type:

            conditions.append(
                "o.org_type = %s"
            )

            params.append(
                normalized_org_type
            )

    # -----------------------------
    # Region
    # -----------------------------
    region = filters.get("region")

    if region and region.upper() != "ALL":

        conditions.append(
            "o.state_id = (SELECT s.state_id FROM virginia_dev_saayam_rdbms.state s WHERE s.state_name = %s)"
        )

        params.append(region)

    # -----------------------------
    # Organization Size
    # -----------------------------
    if filters.get("org_size"):

        conditions.append(
            "o.org_size = %s"
        )

        params.append(
            filters["org_size"]
        )

    # -----------------------------
    # State ID
    # -----------------------------
    if filters.get("state_id"):

        conditions.append(
            "o.state_id = %s"
        )

        params.append(
            filters["state_id"]
        )

    # -----------------------------
    # City
    # -----------------------------
    if filters.get("city_name"):

        conditions.append(
            "o.city_name = %s"
        )

        params.append(
            filters["city_name"]
        )

    # -----------------------------
    # Organization Rating
    # -----------------------------
    if filters.get("org_rating") is not None:

        conditions.append(
            "o.org_rating = %s"
        )

        params.append(
            filters["org_rating"]
        )

    # -----------------------------
    # Collaborator
    # -----------------------------
    if filters.get("is_collaborator") is not None:

        conditions.append(
            "o.is_collaborator = %s"
        )

        params.append(
            filters["is_collaborator"]
        )

    # -----------------------------
    # Contributor
    # -----------------------------
    if filters.get("is_contributor") is not None:

        conditions.append(
            "o.is_contributor = %s"
        )

        params.append(
            filters["is_contributor"]
        )

    # -----------------------------
    # Time Filter
    # -----------------------------
    time_filter = filters.get(
        "time_filter",
        "ALL"
    ).upper()

    if time_filter == "7D":

        conditions.append(
            "o.created_at >= CURRENT_DATE - INTERVAL '7 days'"
        )

    elif time_filter == "30D":

        conditions.append(
            "o.created_at >= CURRENT_DATE - INTERVAL '30 days'"
        )

    elif time_filter == "1Y":

        conditions.append(
            "o.created_at >= CURRENT_DATE - INTERVAL '1 year'"
        )

    elif time_filter == "CUSTOM":

        if not filters.get("start_date") or not filters.get("end_date"):

            raise ValueError(
                "start_date and end_date are required when time_filter is CUSTOM"
            )

        conditions.append(
            "o.created_at >= %s AND o.created_at < (%s::date + INTERVAL '1 day')"
        )

        params.extend(
            [
                filters["start_date"],
                filters["end_date"]
            ]
        )

    return conditions, params

# ==========================================================
# Overview Analytics
# ==========================================================


def fetch_organization_summary(cursor, filters):

    conditions, params = build_filters(filters)

    where_clause = ""

    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    query = f"""
        SELECT
            COUNT(*) AS total_organizations,

            COUNT(*) FILTER (
                WHERE o.is_collaborator = TRUE
            ) AS total_collaborators,

            COUNT(*) FILTER (
                WHERE o.is_contributor = TRUE
            ) AS total_contributors,

            AVG(o.org_rating) AS average_org_rating

        FROM {SCHEMA_NAME}.organizations o

        {where_clause};
    """

    cursor.execute(query, params)

    result = cursor.fetchone()

    return {
        "total_organizations": int(
            result["total_organizations"]
        ),

        "total_collaborators": int(
            result["total_collaborators"]
        ),

        "total_contributors": int(
            result["total_contributors"]
        ),

        "average_org_rating": (
            float(result["average_org_rating"])
            if result["average_org_rating"] is not None
            else 0
        )
    }



def fetch_growth_trend(cursor, filters):
    conditions, params = build_filters(filters)

    where_clause = ""

    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    group_by = filters.get("group_by", "daily")

    if group_by == "daily":
        period_expression = "DATE(o.created_at)"

    elif group_by == "weekly":
        period_expression = "DATE_TRUNC('week', o.created_at)"

    elif group_by == "monthly":
        period_expression = "DATE_TRUNC('month', o.created_at)"

    elif group_by == "yearly":
        period_expression = "DATE_TRUNC('year', o.created_at)"

    else:
        raise ValueError(
            "Invalid group_by. Supported values: daily, weekly, monthly, yearly"
        )

    query = f"""
        SELECT
            {period_expression} AS period,
            COUNT(*) AS total_organizations,
            COUNT(
                CASE
                    WHEN o.is_collaborator = TRUE
                    THEN 1
                END
            ) AS total_collaborators

        FROM {SCHEMA_NAME}.organizations o

        {where_clause}

        GROUP BY
            {period_expression}

        ORDER BY
            period;
    """

    cursor.execute(query, params)

    rows = cursor.fetchall()

    return [
        {
            "period": row["period"],
            "total_organizations": row["total_organizations"],
            "total_collaborators": row["total_collaborators"]
        }
        for row in rows
    ]



def fetch_organizations_by_size(cursor, filters):

    conditions, params = build_filters(filters)

    where_clause = ""

    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    query = f"""
        SELECT
            o.org_size,
            COUNT(*) AS organization_count

        FROM {SCHEMA_NAME}.organizations o

        {where_clause}

        GROUP BY o.org_size

        ORDER BY organization_count DESC;
    """

    cursor.execute(query, params)

    rows = cursor.fetchall()

    return [
        {
            "org_size": row["org_size"],
            "organization_count": row["organization_count"]
        }
        for row in rows
    ]


def fetch_collaborator_vs_contributor(cursor, filters):

    conditions, params = build_filters(filters)

    where_clause = ""

    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    query = f"""
        SELECT
            COUNT(*) FILTER (
                WHERE o.is_collaborator = TRUE
            ) AS collaborator_count,

            COUNT(*) FILTER (
                WHERE o.is_contributor = TRUE
            ) AS contributor_count

        FROM {SCHEMA_NAME}.organizations o

        {where_clause};
    """

    cursor.execute(query, params)

    row = cursor.fetchone()

    collaborator_count = row["collaborator_count"] or 0
    contributor_count = row["contributor_count"] or 0

    total = collaborator_count + contributor_count

    return [
        {
            "type": "collaborator",
            "organization_count": collaborator_count,
            "percentage": round(
                (collaborator_count / total) * 100, 1
            ) if total else 0
        },
        {
            "type": "contributor",
            "organization_count": contributor_count,
            "percentage": round(
                (contributor_count / total) * 100, 1
            ) if total else 0
        }
    ]



def fetch_organizations_by_location(cursor, filters):

    conditions, params = build_filters(filters)

    where_clause = ""

    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    query = f"""
        SELECT
            s.state_code,
            s.state_name,
            COUNT(*) AS total_organizations

        FROM {SCHEMA_NAME}.organizations o

        LEFT JOIN {SCHEMA_NAME}.state s
            ON o.state_id = s.state_id

        {where_clause}

        GROUP BY
            s.state_code,
            s.state_name

        ORDER BY
            total_organizations DESC,
            s.state_name;
    """

    cursor.execute(query, params)

    rows = cursor.fetchall()

    return [
        {
            "state_code": row["state_code"],
            "state_name": row["state_name"],
            "total_organizations": row["total_organizations"]
        }
        for row in rows
    ]


# ==========================================================
# Performance Analytics
# ==========================================================

def fetch_rating_distribution(cursor, filters):

    conditions, params = build_filters(filters)

    where_clause = ""

    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    query = f"""
        SELECT
            o.org_rating AS rating,
            COUNT(*) AS organization_count

        FROM {SCHEMA_NAME}.organizations o

        {where_clause}

        {"AND" if conditions else "WHERE"} o.org_rating IS NOT NULL

        GROUP BY o.org_rating

        ORDER BY o.org_rating;
    """

    cursor.execute(query, params)

    rows = cursor.fetchall()

    return [
        {
            "rating": int(row["rating"]),
            "organization_count": row["organization_count"]
        }
        for row in rows
    ]



def fetch_organization_type_distribution(cursor, filters):

    conditions, params = build_filters(filters)

    where_clause = ""

    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    group_by = filters.get("group_by", "daily")

    if group_by == "daily":
        period_expression = "DATE(o.created_at)"

    elif group_by == "weekly":
        period_expression = "DATE_TRUNC('week', o.created_at)"

    elif group_by == "monthly":
        period_expression = "DATE_TRUNC('month', o.created_at)"

    elif group_by == "yearly":
        period_expression = "DATE_TRUNC('year', o.created_at)"

    else:
        period_expression = "DATE(o.created_at)"

    query = f"""
        SELECT

            {period_expression} AS period,

            COUNT(*) FILTER (
                WHERE LOWER(TRIM(o.org_type)) = 'for-profit'
            ) AS for_profit,

            COUNT(*) FILTER (
                WHERE LOWER(TRIM(o.org_type)) = 'non-profit'
            ) AS non_profit,

            COUNT(*) AS total

        FROM {SCHEMA_NAME}.organizations o

        {where_clause}

        GROUP BY {period_expression}

        ORDER BY period;
    """

    cursor.execute(query, params)

    rows = cursor.fetchall()

    return [
        {
            "period": (
                row["period"].strftime("%Y-%m-%d")
                if group_by == "daily"
                else (
                    row["period"].strftime("%Y-%m-%d %H:%M:%S")
                    if group_by == "weekly"
                    else (
                        row["period"].strftime("%Y-%m")
                        if group_by == "monthly"
                        else row["period"].strftime("%Y")
                    )
                )
            ),
            "for_profit": int(row["for_profit"] or 0),
            "non_profit": int(row["non_profit"] or 0),
            "total": int(row["total"] or 0)
        }
        for row in rows
    ]


# ==========================================================
# Lambda Handler
# ==========================================================

def lambda_handler(event, context):

    conn = None
    cursor = None

    response_body = get_default_response()

    event = event or {}

    filters = {

    "time_filter": event.get(
        "time_filter",
        "ALL"
    ),

    "start_date": event.get(
        "start_date"
    ),

    "end_date": event.get(
        "end_date"
    ),

    "organization_type": event.get(
        "organization_type"
    ),

    "region": event.get(
        "region"
    ),

    "org_size": event.get(
        "org_size"
    ),

    "state_id": event.get(
        "state_id"
    ),

    "city_name": event.get(
        "city_name"
    ),

    "org_rating": event.get(
        "org_rating"
    ),

    "is_collaborator": event.get(
        "is_collaborator"
    ),

    "is_contributor": event.get(
        "is_contributor"
    ),

    "group_by": event.get(
        "group_by",
        "daily"
    )

}
    

    try:
        conn = get_db_connection()

        cursor = conn.cursor(
            cursor_factory=RealDictCursor
        )


        # -----------------------------
        # Tab 1 - Growth & Location
        # -----------------------------

        try:
            response_body["summary"] = (
                fetch_organization_summary(
                    cursor,
                    filters
                )
            )
        except Exception as error:
            print(f"Summary failed: {error}")

        try:
            response_body["growth_trend"] = (
                fetch_growth_trend(
                    cursor,
                    filters
                )
            )
        except Exception as error:
            print(f"Growth trend failed: {error}")

        try:
            response_body["organizations_by_location"] = (
                fetch_organizations_by_location(
                    cursor,
                    filters
                )
            )
        except Exception as error:
            print(f"Organizations by location failed: {error}")


        # -----------------------------
        # Tab 2 - Size & Contribution
        # -----------------------------

        try:
            response_body["organizations_by_size"] = (
                fetch_organizations_by_size(
                    cursor,
                    filters
                )
            )
        except Exception as error:
            print(f"Organizations by size failed: {error}")

        try:
            response_body["collaborator_vs_contributor"] = (
                fetch_collaborator_vs_contributor(
                    cursor,
                    filters
                )
            )
        except Exception as error:
            print(f"Collaborator vs contributor failed: {error}")


        # -----------------------------
        # Tab 3 - Ratings & Type
        # -----------------------------

        try:
            response_body["rating_distribution"] = (
                fetch_rating_distribution(
                    cursor,
                    filters
                )
            )
        except Exception as error:
            print(f"Rating distribution failed: {error}")

        try:
            response_body["organization_type_distribution"] = (
                fetch_organization_type_distribution(
                    cursor,
                    filters
                )
            )
        except Exception as error:
            print(f"Organization type distribution failed: {error}")

        return build_response(
            200,
            response_body
        )

    except Exception as error:

        print(f"Organization analytics failed: {error}")

        return build_response(
            500,
            response_body
        )

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()

   


   
    
            
    
 