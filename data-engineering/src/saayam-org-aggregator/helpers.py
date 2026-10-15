import boto3
import json
from aws_lambda_powertools.utilities import parameters
import pandas as pd
import pg8000
from distance import parse_coordinates, geocode_address


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
        query = f"""
            SELECT *
            FROM {_db_name}.organizations
            WHERE mission = %s
              AND city_name = %s
        """

        df = pd.read_sql(
            query,
            _db_conn,
            params=(category, location)
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
    try:
        db_organizations = db_organizations.rename(columns={
            'org_name': 'name',
            'city_name': 'location',
            'phone': 'contact'
        }).copy()

        # Keep address fields internally for distance calculation.
        db_columns = [
            'name', 'location', 'contact', 'email', 'web_url',
            'mission', 'source', 'db_or_ai', 'street',
            'state_id', 'zip_code'
        ]
        for column in db_columns:
            if column not in db_organizations.columns:
                db_organizations[column] = None

        db_organizations = db_organizations[db_columns]

        genAI_organizations = genAI_organizations.rename(columns={
            'organization_name': 'name'
        }).copy()

        # AI organizations may provide different address fields.
        ai_columns = [
            'name', 'location', 'contact', 'email', 'web_url',
            'mission', 'source', 'db_or_ai', 'street',
            'state', 'zip_code'
        ]
        for column in ai_columns:
            if column not in genAI_organizations.columns:
                genAI_organizations[column] = None

        genAI_organizations = genAI_organizations[ai_columns]
        genAI_organizations = genAI_organizations.rename(columns={
            'state': 'state_id'
        })

        return pd.concat(
            [db_organizations, genAI_organizations],
            ignore_index=True
        )

    except Exception as e:
        raise Exception(f'Error merging organizations: {str(e)}')




def get_request_location(request_id):
    """Retrieve the request location and request type."""
    query = """
        SELECT
            req_id,
            req_user_id,
            req_loc,
            req_for_id
        FROM virginia_dev_saayam_rdbms.request
        WHERE req_id = %s
    """

    try:
        cursor = _db_conn.cursor()
        try:
            cursor.execute(query, (request_id,))
            row = cursor.fetchone()
        finally:
            cursor.close()

        if row is None:
            return None

        return {
            "request_id": row[0],
            "user_id": row[1],
            "request_location": row[2],
            "request_for_id": row[3],
        }

    except Exception as e:
        raise Exception(f"Error fetching request location: {str(e)}")





def get_saved_user_coordinates(user_id):
    """Retrieve a user's saved coordinates as latitude and longitude."""
    if not user_id:
        return None

    query = """
        SELECT
            ST_Y(curr_loc::geometry) AS latitude,
            ST_X(curr_loc::geometry) AS longitude
        FROM virginia_dev_saayam_rdbms.user_locations
        WHERE user_id = %s
          AND curr_loc IS NOT NULL
    """

    cursor = _db_conn.cursor()
    try:
        cursor.execute(query, (user_id,))
        row = cursor.fetchone()
    finally:
        cursor.close()

    if row is None:
        return None

    latitude = float(row[0])
    longitude = float(row[1])

    if not (-90 <= latitude <= 90):
        return None

    if not (-180 <= longitude <= 180):
        return None

    return {
        "latitude": latitude,
        "longitude": longitude,
    }






def resolve_beneficiary_coordinates(request_id):
    """Resolve beneficiary coordinates using the best available location."""
    request = get_request_location(request_id)

    if request is None:
        return None

    request_location = request.get("request_location")

    # First priority: coordinates supplied with the request.
    coordinates = parse_coordinates(request_location)
    if coordinates is not None:
        return {
            "coordinates": coordinates,
            "address": None,
            "status": "ok",
        }

    # If the request location is an address or city, try geocoding it.
    if isinstance(request_location, str) and request_location.strip():
        coordinates = geocode_address(request_location)
        if coordinates is not None:
            return {
                "coordinates": coordinates,
                "address": None,
                "status": "ok",
            }

    # Next priority: saved coordinates for SELF requests.
    if request["request_for_id"] == 0:
        coordinates = get_saved_user_coordinates(request["user_id"])

        if coordinates is not None:
            return {
                "coordinates": coordinates,
                "address": None,
                "status": "ok",
            }

        # Last fallback: the user's profile address.
        address = get_user_profile_address(request["user_id"])
        if address:
            return {
                "coordinates": None,
                "address": address,
                "status": "deferred",
            }

    return {
        "coordinates": None,
        "address": None,
        "status": "unknown_location",
    }





def get_user_profile_address(user_id):
    """Build a user's profile address using readable state and country names."""
    if not user_id:
        return None

    query = """
        SELECT
            u.addr_ln1,
            u.addr_ln2,
            u.addr_ln3,
            u.city_name,
            s.state_name,
            u.zip_code,
            c.country_name
        FROM virginia_dev_saayam_rdbms.users AS u
        LEFT JOIN virginia_dev_saayam_rdbms.state AS s
            ON u.state_id = s.state_id
        LEFT JOIN virginia_dev_saayam_rdbms.country AS c
            ON u.country_id = c.country_id
        WHERE u.user_id = %s
    """

    cursor = _db_conn.cursor()
    try:
        cursor.execute(query, (user_id,))
        row = cursor.fetchone()
    finally:
        cursor.close()

    if row is None:
        return None

    address_parts = [
        str(part).strip()
        for part in row
        if part is not None and str(part).strip()
    ]

    return ", ".join(address_parts) if address_parts else None
