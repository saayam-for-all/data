import boto3
import json
from aws_lambda_powertools.utilities import parameters
import pandas as pd
import pg8000
import math


GEN_AI_LAMBDA = "More_Org_GenAI_Py_v3126"

# --- All cached at module level, initialized once on cold start ---
lambda_client = boto3.client('lambda')

_creds = json.loads(parameters.get_parameter(
    '/dev/saayam/db/Virginia/Analytics/user',
    decrypt=True,
    max_age=3600
))
_db_name = _creds['DATABASE NAME']
_db_conn = pg8000.connect(
    host=_creds['HOST'],
    user=_creds['USERNAME'],
    password=_creds['PASSWORD'],
    database=_db_name,
    port=_creds['PORT'],
    ssl_context=True
)
# -----------------------------------------------------------------

def get_orgs_from_db(location, category):
    try:
        df = pd.read_sql(
            f"SELECT * FROM {_db_name}.organizations WHERE mission = '{category}' AND city_name = '{location}'",
            _db_conn
        )
        df["db_or_ai"] = "db"
        return df
    except pg8000.DatabaseError as e:
        raise Exception(f'Database error: {str(e)}')
    except Exception as e:
        raise Exception(f'Error fetching from DB: {str(e)}')


def get_ai_orgs(subject, description, location):
    try:
        response = lambda_client.invoke(
            FunctionName=GEN_AI_LAMBDA,
            InvocationType='RequestResponse',
            Payload=json.dumps({
                "subject": subject,
                "description": description,
                "location": location
            })
        )
        payload = json.loads(response['Payload'].read())
        if payload.get('statusCode') != 200:
            raise Exception(f'GenAI Lambda returned error: {payload}')
        orgs = pd.DataFrame(payload['body']['organizations'])
        orgs["db_or_ai"] = "ai"
        return orgs
    except boto3.exceptions.Boto3Error as e:
        raise Exception(f'Failed to invoke GenAI Lambda: {str(e)}')
    except (KeyError, TypeError) as e:
        raise Exception(f'Unexpected response structure from GenAI Lambda: {str(e)}')
    except Exception as e:
        raise Exception(f'Error fetching AI orgs: {str(e)}')



def merge_organizations(db_organizations, genAI_organizations):
    """Merge DB and GenAI organizations while preserving location data."""
    try:
        db_organizations = db_organizations.rename(columns={
            "org_name": "name",
            "city_name": "location",
            "phone": "contact"
        }).copy()

        genAI_organizations = genAI_organizations.rename(columns={
            "organization_name": "name"
        }).copy()

        base_columns = [
            "name", "location", "contact", "email",
            "web_url", "mission", "source", "db_or_ai"
        ]

        # Retain existing response fields first, then all additional
        # fields, including coordinates and address information.
        all_columns = list(dict.fromkeys(
            base_columns
            + list(db_organizations.columns)
            + list(genAI_organizations.columns)
        ))

        db_organizations = db_organizations.reindex(columns=all_columns)
        genAI_organizations = genAI_organizations.reindex(columns=all_columns)


        merged = pd.concat(
            [db_organizations, genAI_organizations],
            ignore_index=True
        )

        # Convert pandas missing values to Python None.
        # Preserve dictionaries such as organization coordinates.
        merged = merged.astype(object).where(pd.notna(merged), None)

        return merged


    except Exception as e:
        raise Exception(f"Error merging organizations: {str(e)}")

def calculate_distance_miles(lat1, lon1, lat2, lon2):
    """Calculate straight-line distance in miles using Haversine."""
    if any(v is None for v in (lat1, lon1, lat2, lon2)):
        return None

    try:
        lat1, lon1, lat2, lon2 = map(
            float, (lat1, lon1, lat2, lon2)
        )

        if not all(math.isfinite(v) for v in (lat1, lon1, lat2, lon2)):
            return None

        if not (-90 <= lat1 <= 90 and -90 <= lat2 <= 90):
            return None

        if not (-180 <= lon1 <= 180 and -180 <= lon2 <= 180):
            return None

        radius_miles = 3958.7613

        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)

        a = (
            math.sin(delta_lat / 2) ** 2
            + math.cos(lat1_rad)
            * math.cos(lat2_rad)
            * math.sin(delta_lon / 2) ** 2
        )

        c = 2 * math.asin(math.sqrt(min(1.0, max(0.0, a))))

        return round(radius_miles * c, 1)

    except (TypeError, ValueError, OverflowError):
        return None

def parse_coordinates(value):
    """Return (latitude, longitude) or None for invalid coordinates."""
    if value is None:
        return None

    try:
        if isinstance(value, str):
            value = value.strip()

            if not value:
                return None

            if value.startswith("{") or value.startswith("["):
                value = json.loads(value)
            else:
                parts = value.split(",")
                if len(parts) != 2:
                    return None
                value = parts

        if isinstance(value, dict):
            latitude = value.get("latitude", value.get("lat"))
            longitude = value.get("longitude", value.get("lng", value.get("lon")))
        elif isinstance(value, (list, tuple)) and len(value) == 2:
            latitude, longitude = value
        else:
            return None

        if latitude is None or longitude is None:
            return None

        latitude = float(latitude)
        longitude = float(longitude)

        if not (math.isfinite(latitude) and math.isfinite(longitude)):
            return None

        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return None

        return latitude, longitude

    except (ValueError, TypeError, json.JSONDecodeError):
        return None

def add_distances_to_organizations(organizations, beneficiary_location):
    """Add distance metadata without removing organizations."""
    beneficiary_coords = parse_coordinates(beneficiary_location)

    enriched = []

    for organization in organizations:
        org = organization.copy()

        org_coords = parse_coordinates(
            org.get("coordinates")
        )

        org["distance"] = None
        org["distance_unit"] = "miles"
        org["distance_method"] = "straight_line"

        if beneficiary_coords is None:
            org["distance_status"] = "unknown_location"

        elif org_coords is None:
            org["distance_status"] = "not_found"

        else:
            try:
                org["distance"] = calculate_distance_miles(
                    beneficiary_coords[0],
                    beneficiary_coords[1],
                    org_coords[0],
                    org_coords[1]
                )
                org["distance_status"] = "ok"
            except (TypeError, ValueError, OverflowError):
                org["distance_status"] = "error"

        enriched.append(org)

    return enriched
def resolve_beneficiary_coordinates(body):
    """
    Resolve beneficiary coordinates from a trusted request payload.
    """
    if not isinstance(body, dict):
        return None

    return parse_coordinates(
        body.get("beneficiary_coordinates")
    )
