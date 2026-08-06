import json

import psycopg2
from psycopg2.extras import RealDictCursor
from aws_lambda_powertools.utilities import parameters

SCHEMA_NAME = "virginia_dev_saayam_rdbms"


SLA = {
    "target_days": 10,
    "target_hours": 240,
    "warning_days": 8.33,
    "warning_hours": 200
}


def get_default_response():
    return {
        "organization_overview": {
            "summary": {
                "total_organizations": 0,
                "non_profit_organizations": 0,
                "for_profit_organizations": 0,
                "collaborator_organizations": 0,
                "non_collaborator_organizations": 0,
                "contributor_organizations": 0,
                "non_contributor_organizations": 0
            },
            "organization_activity_trend": [],
            "organizations_by_type": [],
            "organizations_by_size": [],
            "organizations_by_location": [],
            "collaborator_distribution": [],
            "contributor_distribution": []
        },
    
        "organization_performance": {
            "summary": {
        "average_rating": 0,
        "rated_organizations": 0,
        "unrated_organizations": 0,
        "five_star_organizations": 0
        },
        "rating_distribution": [],
        "top_rated_organizations": [],
        "top_collaborator_organizations": [],
        "top_contributor_organizations": [],
        "ratings_by_organization_type": [],
        "ratings_by_organization_size": []
    }
    }

def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body, default=str)
    }


def get_db_connection():
    creds = json.loads(parameters.get_parameter(
        "/dev/saayam/db/Virginia/Analytics/user",
        decrypt=True,
        max_age=3600
    ))

    db_name = creds["DATABASE NAME"]

    return psycopg2.connect(
        host=creds["HOST"],
        database=db_name,
        user=creds["USERNAME"],
        password=creds["PASSWORD"],
        port=creds["PORT"],
        sslmode="require"
    )

def fetch_organizations_by_type(cursor):
    query = f"""
        SELECT
            org_type,
            COUNT(org_id) AS count
        FROM {SCHEMA_NAME}.organizations
        GROUP BY org_type
        ORDER BY org_type;
    """

    cursor.execute(query)
    rows = cursor.fetchall()

    return [
        {
            "organization_type": row["org_type"],
            "count": int(row["count"])
        }
        for row in rows
    ]


def fetch_total_organizations(cursor):
    query = f"""
        SELECT COUNT(org_id) AS total_organizations
        FROM {SCHEMA_NAME}.organizations;
    """

    cursor.execute(query)
    row = cursor.fetchone()

    return int(row["total_organizations"]) if row and row["total_organizations"] is not None else 0


def fetch_organizations_by_size(cursor):
    query = f"""
        SELECT
            org_size,
            COUNT(org_id) AS count
        FROM {SCHEMA_NAME}.organizations
        GROUP BY org_size
        ORDER BY org_size;
    """

    cursor.execute(query)
    rows = cursor.fetchall()

    return [
        {
            "organization_size": row["org_size"],
            "count": int(row["count"])
        }
        for row in rows
    ]

def fetch_collaborator_distribution(cursor):
    query = f"""
        SELECT
            is_collaborator,
            COUNT(org_id) AS count
        FROM {SCHEMA_NAME}.organizations
        GROUP BY is_collaborator;
    """

    cursor.execute(query)
    rows = cursor.fetchall()

    return [
        {
            "organization_type": (
                "Collaborator"
                if row["is_collaborator"]
                else "Non-Collaborator"
            ),
            "count": int(row["count"])
        }
        for row in rows
    ]

def fetch_organizations_by_location(cursor):
    query = f"""
        SELECT
            s.state_name,
            o.city_name,
            COUNT(o.org_id) AS count
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s
            ON o.state_id = s.state_id
        GROUP BY s.state_name, o.city_name
        ORDER BY s.state_name, o.city_name;
    """

    cursor.execute(query)
    rows = cursor.fetchall()

    states = {}
    cities = {}

    for row in rows:
        if row["state_name"]:
            states[row["state_name"]] = (
                states.get(row["state_name"], 0) + int(row["count"])
            )

        if row["city_name"]:
            cities[row["city_name"]] = (
                cities.get(row["city_name"], 0) + int(row["count"])
            )

    return {
        "by_state": [
            {"state": state, "count": count}
            for state, count in states.items()
        ],
        "by_city": [
            {"city": city, "count": count}
            for city, count in cities.items()
        ]
    }

def fetch_organization_registration_trend(cursor):
    query = f"""
        SELECT
            DATE(created_at) AS registration_date,
            COUNT(org_id) AS count
        FROM {SCHEMA_NAME}.organizations
        GROUP BY DATE(created_at)
        ORDER BY registration_date;
    """

    cursor.execute(query)
    rows = cursor.fetchall()

    return [
        {
            "date": str(row["registration_date"]),
            "count": int(row["count"])
        }
        for row in rows
    ]

def fetch_average_rating(cursor):
    query = f"""
        SELECT
            ROUND(AVG(org_rating), 2) AS average_rating,
            COUNT(org_rating) AS rated_organizations,
            COUNT(*) FILTER (WHERE org_rating IS NULL) AS unrated_organizations,
            COUNT(*) FILTER (WHERE org_rating = 5) AS five_star_organizations
        FROM {SCHEMA_NAME}.organizations;
    """

    cursor.execute(query)
    row = cursor.fetchone()

    return {
        "average_rating": float(row["average_rating"] or 0),
        "rated_organizations": row["rated_organizations"],
        "unrated_organizations": row["unrated_organizations"],
        "five_star_organizations": row["five_star_organizations"]
    }

def fetch_rating_distribution(cursor):
    query = f"""
        SELECT
            org_rating,
            COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations
        WHERE org_rating IS NOT NULL
        GROUP BY org_rating
        ORDER BY org_rating DESC;
    """

    cursor.execute(query)
    rows = cursor.fetchall()

    return [
        {
            "rating": int(row["org_rating"]),
            "count": int(row["count"])
        }
        for row in rows
    ]

def fetch_top_rated_organizations(cursor):
    query = f"""
        SELECT
            org_id,
            org_name,
            org_rating
        FROM {SCHEMA_NAME}.organizations
        WHERE org_rating IS NOT NULL
        ORDER BY org_rating DESC, org_name ASC
        LIMIT 10;
    """

    cursor.execute(query)
    rows = cursor.fetchall()

    return [
        {
            "org_id": row["org_id"],
            "org_name": row["org_name"],
            "rating": int(row["org_rating"])
        }
        for row in rows
    ]

def fetch_unrated_organizations(cursor):
    query = f"""
        SELECT
            org_id,
            org_name
        FROM {SCHEMA_NAME}.organizations
        WHERE org_rating IS NULL
        ORDER BY org_name;
    """

    cursor.execute(query)
    rows = cursor.fetchall()

    return [
        {
            "org_id": row["org_id"],
            "org_name": row["org_name"]
        }
        for row in rows
    ]

def fetch_top_collaborator_organizations(cursor):
    query = f"""
        SELECT
            org_id,
            org_name,
            org_rating
        FROM {SCHEMA_NAME}.organizations
        WHERE is_collaborator = TRUE
        ORDER BY org_rating DESC NULLS LAST, org_name
        LIMIT 10;
    """

    cursor.execute(query)
    rows = cursor.fetchall()

    return [
        {
            "org_id": row["org_id"],
            "org_name": row["org_name"],
            "rating": row["org_rating"]
        }
        for row in rows
    ]

def fetch_ratings_by_organization_type(cursor):
    query = f"""
        SELECT
            org_type,
            ROUND(AVG(org_rating), 2) AS average_rating,
            COUNT(org_id) AS organization_count
        FROM {SCHEMA_NAME}.organizations
        WHERE org_rating IS NOT NULL
        GROUP BY org_type
        ORDER BY org_type;
    """

    cursor.execute(query)
    rows = cursor.fetchall()

    return [
        {
            "organization_type": row["org_type"],
            "average_rating": float(row["average_rating"]),
            "organization_count": int(row["organization_count"])
        }
        for row in rows
    ]

def fetch_ratings_by_organization_size(cursor):
    query = f"""
        SELECT
            org_size,
            ROUND(AVG(org_rating), 2) AS average_rating,
            COUNT(org_id) AS organization_count
        FROM {SCHEMA_NAME}.organizations
        WHERE org_rating IS NOT NULL
        GROUP BY org_size
        ORDER BY org_size;
    """

    cursor.execute(query)
    rows = cursor.fetchall()

    return [
        {
            "organization_size": row["org_size"],
            "average_rating": float(row["average_rating"]),
            "organization_count": int(row["organization_count"])
        }
        for row in rows
    ]

def fetch_ratings_by_organization_type(cursor):
    query = f"""
        SELECT
            org_type,
            ROUND(AVG(org_rating), 2) AS average_rating,
            COUNT(org_id) AS organization_count
        FROM {SCHEMA_NAME}.organizations
        WHERE org_rating IS NOT NULL
        GROUP BY org_type
        ORDER BY org_type;
    """

    cursor.execute(query)
    rows = cursor.fetchall()

    return [
        {
            "organization_type": row["org_type"],
            "average_rating": float(row["average_rating"]),
            "organization_count": int(row["organization_count"])
        }
        for row in rows
    ]

def fetch_ratings_by_organization_size(cursor):
    query = f"""
        SELECT
            org_size,
            ROUND(AVG(org_rating), 2) AS average_rating,
            COUNT(org_id) AS organization_count
        FROM {SCHEMA_NAME}.organizations
        WHERE org_rating IS NOT NULL
        GROUP BY org_size
        ORDER BY org_size;
    """

    cursor.execute(query)
    rows = cursor.fetchall()

    return [
        {
            "organization_size": row["org_size"],
            "average_rating": float(row["average_rating"]),
            "organization_count": int(row["organization_count"])
        }
        for row in rows
    ]

def fetch_rating_distribution(cursor):
    query = f"""
        SELECT
            org_rating,
            COUNT(org_id) AS organization_count
        FROM {SCHEMA_NAME}.organizations
        WHERE org_rating IS NOT NULL
        GROUP BY org_rating
        ORDER BY org_rating;
    """

    cursor.execute(query)
    rows = cursor.fetchall()

    return [
        {
            "rating": int(row["org_rating"]),
            "organization_count": int(row["organization_count"])
        }
        for row in rows
    ]

def fetch_top_rated_organizations(cursor):
    query = f"""
        SELECT
            org_name,
            org_rating,
            org_type,
            org_size
        FROM {SCHEMA_NAME}.organizations
        WHERE org_rating IS NOT NULL
        ORDER BY org_rating DESC, org_name
        LIMIT 10;
    """

    cursor.execute(query)
    rows = cursor.fetchall()

    return [
        {
            "organization_name": row["org_name"],
            "rating": int(row["org_rating"]),
            "organization_type": row["org_type"],
            "organization_size": row["org_size"]
        }
        for row in rows
    ]

def fetch_unrated_organizations(cursor):
    query = f"""
        SELECT
            org_name,
            org_type,
            org_size,
            city_name
        FROM {SCHEMA_NAME}.organizations
        WHERE org_rating IS NULL
        ORDER BY org_name;
    """

    cursor.execute(query)
    rows = cursor.fetchall()

    return [
        {
            "organization_name": row["org_name"],
            "organization_type": row["org_type"],
            "organization_size": row["org_size"],
            "city": row["city_name"]
        }
        for row in rows
    ]

def fetch_top_collaborator_organizations(cursor):
    query = f"""
        SELECT
            org_name,
            org_rating,
            org_type,
            org_size
        FROM {SCHEMA_NAME}.organizations
        WHERE is_collaborator = TRUE
        ORDER BY org_rating DESC NULLS LAST, org_name
        LIMIT 10;
    """

    cursor.execute(query)
    rows = cursor.fetchall()

    return [
        {
            "organization_name": row["org_name"],
            "rating": row["org_rating"],
            "organization_type": row["org_type"],
            "organization_size": row["org_size"]
        }
        for row in rows
    ]

def lambda_handler(event, context):
    conn = None
    cursor = None
    response_body = get_default_response()

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            response_body["organization_overview"]["summary"]["total_organizations"] = \
            fetch_total_organizations(cursor)
        except Exception as error:
            print(f"Total organizations query failed: {error}")
            response_body["organization_overview"]["summary"]["total_organizations"] = 0

        try:
           response_body["organization_overview"]["organizations_by_type"] = \
           fetch_organizations_by_type(cursor)
        except Exception as error:
            print(f"Organization type query failed: {error}")
            response_body["organization_overview"]["organizations_by_type"] = []

        try:
            response_body["organization_overview"]["organizations_by_size"] = \
            fetch_organizations_by_size(cursor)
        except Exception as error:
            print(f"Organization size query failed: {error}")
            response_body["organization_overview"]["organizations_by_size"] = []

        try:
           response_body["organization_overview"]["collaborator_distribution"] = \
           fetch_collaborator_distribution(cursor)
        except Exception as error:
          print(f"Collaborator distribution query failed: {error}")
          response_body["organization_overview"]["collaborator_distribution"] = []

        try:
          response_body["organization_overview"]["organizations_by_location"] = \
          fetch_organizations_by_location(cursor)
        except Exception as error:
          print(f"Organization location query failed: {error}")
          response_body["organization_overview"]["organizations_by_location"] = []

        try:
          response_body["organization_overview"]["organization_activity_trend"] = \
          fetch_organization_registration_trend(cursor)
        except Exception as error:
          print(f"Organization registration trend query failed: {error}")
          response_body["organization_overview"]["organization_activity_trend"] = []

        try:
          response_body["organization_performance"]["summary"] = \
          fetch_average_rating(cursor)
        except Exception as error:
           print(f"Average rating query failed: {error}")
           response_body["organization_performance"]["summary"] = {
        "average_rating": 0,
        "rated_organizations": 0,
        "unrated_organizations": 0,
        "five_star_organizations": 0
    }
        try:
          response_body["organization_performance"]["rating_distribution"] = \
          fetch_rating_distribution(cursor)
        except Exception as error:
          print(f"Rating distribution query failed: {error}")
          response_body["organization_performance"]["rating_distribution"] = []

        try:
          response_body["organization_performance"]["top_rated_organizations"] = \
          fetch_top_rated_organizations(cursor)
        except Exception as error:
          print(f"Top rated organizations query failed: {error}")
          response_body["organization_performance"]["top_rated_organizations"] = []

        try:
          response_body["organization_performance"]["unrated_organizations"] = \
          fetch_unrated_organizations(cursor)
        except Exception as error:
          print(f"Unrated organizations query failed: {error}")
          response_body["organization_performance"]["unrated_organizations"] = []

        try:
          response_body["organization_performance"]["top_collaborator_organizations"] = \
          fetch_top_collaborator_organizations(cursor)
        except Exception as error:
          print(f"Top collaborator organizations query failed: {error}")
          response_body["organization_performance"]["top_collaborator_organizations"] = []

        # is_contributor column is not yet available in the database
        response_body["organization_performance"]["top_contributor_organizations"] = []

        
        try:
          response_body["organization_performance"]["ratings_by_organization_type"] = \
          fetch_ratings_by_organization_type(cursor)
        except Exception as error:
          print(f"Ratings by organization type query failed: {error}")
          response_body["organization_performance"]["ratings_by_organization_type"] = []

        try:
          response_body["organization_performance"]["ratings_by_organization_size"] = \
          fetch_ratings_by_organization_size(cursor)
        except Exception as error:
          print(f"Ratings by organization size query failed: {error}")
          response_body["organization_performance"]["ratings_by_organization_size"] = []

        try:
          response_body["organization_performance"]["rating_distribution"] = \
          fetch_rating_distribution(cursor)
        except Exception as error:
          print(f"Rating distribution query failed: {error}")
          response_body["organization_performance"]["rating_distribution"] = []

        try:
          response_body["organization_performance"]["top_rated_organizations"] = \
          fetch_top_rated_organizations(cursor)
        except Exception as error:
          print(f"Top rated organizations query failed: {error}")
          response_body["organization_performance"]["top_rated_organizations"] = []

        try:
          response_body["organization_performance"]["unrated_organizations"] = \
          fetch_unrated_organizations(cursor)
        except Exception as error:
          print(f"Unrated organizations query failed: {error}")
          response_body["organization_performance"]["unrated_organizations"] = []

        try:
          response_body["organization_performance"]["top_collaborator_organizations"] = \
          fetch_top_collaborator_organizations(cursor)
        except Exception as error:
          print(f"Top collaborator organizations query failed: {error}")
          response_body["organization_performance"]["top_collaborator_organizations"] = []

        return build_response(200, response_body)

    except Exception as error:
        print(f"DB connection failed: {error}")
        return build_response(500, response_body)

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    result = lambda_handler({}, None)
    print(json.dumps(result, indent=2))