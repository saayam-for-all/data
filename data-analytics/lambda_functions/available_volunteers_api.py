import json
import logging
import math
import os

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Default matching distance radius in kilometers for In-Person requests
DEFAULT_MATCHING_RADIUS_KM = 50.0


def get_db_connection():
    """Establish local PostgreSQL database connection."""
    try:
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            database=os.environ.get("DB_NAME", "saayam_db"),
            user=os.environ.get("DB_USER", "postgres"),
            password=os.environ.get("DB_PASSWORD", "postgres"),
            port=os.environ.get("DB_PORT", "5432"),
        )
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {str(e)}")
        raise e


def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate the great-circle distance between two points on Earth in kilometers."""
    if None in (lat1, lon1, lat2, lon2):
        return float("inf")

    R = 6371.0  # Earth's radius in kilometers
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(
        math.radians(lat2)
    ) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def fetch_available_volunteers(cursor, request_id):
    """Retrieve skill-matched, location-matched, and active available volunteers."""
    # 1. Fetch help request metadata
    req_query = """
        SELECT 
            r.req_id,
            r.req_cat_id,
            r.req_type_id,
            LOWER(COALESCE(rt.type_name, '')) AS type_name,
            r.req_loc,
            r.latitude AS req_lat,
            r.longitude AS req_lon
        FROM request r
        LEFT JOIN request_type rt ON r.req_type_id = rt.id
        WHERE r.req_id = %s;
    """
    cursor.execute(req_query, (request_id,))
    request_data = cursor.fetchone()

    if not request_data:
        return {"error": "Request not found", "status_code": 404}

    req_cat_id = request_data["req_cat_id"]
    is_in_person = "in person" in request_data["type_name"] or "in-person" in request_data["type_name"]
    req_lat = float(request_data["req_lat"]) if request_data.get("req_lat") is not None else None
    req_lon = float(request_data["req_lon"]) if request_data.get("req_lon") is not None else None

    # 2. Retrieve skill-matched, active volunteers with latest geolocation
    volunteers_query = """
        WITH latest_geo AS (
            SELECT DISTINCT ON (user_id) 
                user_id, latitude, longitude, updated_at
            FROM volunteer_geolocation
            ORDER BY user_id, updated_at DESC
        )
        SELECT 
            u.id AS user_id,
            COALESCE(u.full_name, u.first_name, 'Volunteer') AS name,
            COALESCE(us_status.status_name, v.status, 'Active') AS status,
            ARRAY_AGG(DISTINCT hc.category_name) AS skills,
            g.latitude AS vol_lat,
            g.longitude AS vol_lon
        FROM users u
        JOIN volunteer_details v ON u.id = v.user_id
        LEFT JOIN user_status us_status ON u.status_id = us_status.id
        JOIN user_skills usk ON u.id = usk.user_id
        JOIN help_category hc ON usk.skill_id = hc.id OR usk.category_id = hc.id
        LEFT JOIN latest_geo g ON u.id = g.user_id
        WHERE hc.id = %s
          AND LOWER(COALESCE(us_status.status_name, v.status, 'active')) = 'active'
        GROUP BY u.id, u.full_name, u.first_name, us_status.status_name, v.status, g.latitude, g.longitude;
    """
    cursor.execute(volunteers_query, (req_cat_id,))
    candidates = cursor.fetchall() or []

    available_volunteers = []

    for vol in candidates:
        # Format skills safely
        skills_list = vol["skills"] if isinstance(vol["skills"], list) else [str(vol["skills"])]
        skills_list = [s for s in skills_list if s]

        # 3. Location filtering for In-Person requests
        if is_in_person:
            vol_lat = float(vol["vol_lat"]) if vol.get("vol_lat") is not None else None
            vol_lon = float(vol["vol_lon"]) if vol.get("vol_lon") is not None else None

            if req_lat is not None and req_lon is not None and vol_lat is not None and vol_lon is not None:
                dist = haversine_distance(req_lat, req_lon, vol_lat, vol_lon)
                if dist > DEFAULT_MATCHING_RADIUS_KM:
                    continue  # Exclude volunteers outside the proximity threshold
            else:
                # Exclude if location missing for mandatory in-person matching
                continue

        available_volunteers.append({
            "volunteerId": str(vol["user_id"]),
            "name": vol["name"],
            "skills": skills_list,
            "status": vol["status"]
        })

    return {
        "status_code": 200,
        "payload": {
            "requestId": request_id,
            "availableVolunteers": available_volunteers
        }
    }


def lambda_handler(event, context):
    """Main Lambda Handler for Available Volunteers Microservice API."""
    try:
        payload = {}
        if event.get("body"):
            payload = json.loads(event["body"]) if isinstance(event["body"], str) else event["body"]
        else:
            payload = event

        request_id = payload.get("request_id")
        if not request_id:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "request_id is required"})
            }

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        result = fetch_available_volunteers(cursor, request_id)

        cursor.close()
        conn.close()

        if result.get("status_code") == 404:
            return {
                "statusCode": 404,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": result["error"]})
            }

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(result["payload"])
        }

    except psycopg2.Error as db_err:
        logger.error(f"Database Query Error: {str(db_err)}")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error_code": "DE 1001", "message": "Database execution error."})
        }
    except Exception as e:
        logger.error(f"Internal Server Error: {str(e)}")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error_code": "DE 1000", "message": "Internal server execution error."})
        }