import boto3
import json
from aws_lambda_powertools.utilities import parameters
import pandas as pd
import pg8000


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

def get_req_info(request_id, beneficiary_id):
    """Fetch request details needed to recommend and locate organizations."""
    cursor = None

    try:
        cursor = _db_conn.cursor()
        cursor.execute(
            f"""
            SELECT *
            FROM {_db_name}.requests
            WHERE req_id = %s
              AND beneficiary_id = %s
            """,
            (request_id, beneficiary_id),
        )

        row = cursor.fetchone()
        if row is None:
            raise LookupError(
                f"No request found for request_id={request_id}"
            )

        columns = [description[0] for description in cursor.description]
        request_info = dict(zip(columns, row))

        category_id = request_info.get("req_cat_id")
        if category_id is None:
            raise LookupError(
                f"Request {request_id} has no category assigned"
            )

        cursor.execute(
            f"""
            SELECT cat_name
            FROM {_db_name}.help_categories
            WHERE cat_id = %s
            """,
            (category_id,),
        )

        category_row = cursor.fetchone()
        if category_row is None:
            raise LookupError(
                f"No help category found for category_id={category_id}"
            )

        return {
            "category": category_row[0],
            "description": request_info.get("req_desc"),
            "subject": request_info.get("req_subj"),
            "req_loc": request_info.get("req_loc"),
        }

    except pg8000.DatabaseError as exc:
        raise RuntimeError(
            f"Database error while fetching request {request_id}: {exc}"
        ) from exc

    finally:
        if cursor is not None:
            cursor.close()

def get_beneficiary_location(beneficiary_id, request_location=None):
    """Return the best available location for distance calculations."""
    if request_location is not None and str(request_location).strip():
        return request_location

    cursor = None
    try:
        cursor = _db_conn.cursor()

        cursor.execute(
            f"""
            SELECT curr_loc
            FROM {_db_name}.user_locations
            WHERE user_id = %s
            LIMIT 1
            """,
            (beneficiary_id,),
        )
        row = cursor.fetchone()

        if row and row[0] is not None and str(row[0]).strip():
            return row[0]

        cursor.execute(
            f"""
            SELECT addr_ln1, addr_ln2, addr_ln3, city_name, zip_code
            FROM {_db_name}.users
            WHERE user_id = %s
            LIMIT 1
            """,
            (beneficiary_id,),
        )
        row = cursor.fetchone()

        if not row:
            return None

        address_parts = [
            str(value).strip()
            for value in row
            if value is not None and str(value).strip()
        ]
        return ", ".join(address_parts) or None

    except pg8000.DatabaseError as exc:
        raise RuntimeError(
            f"Could not resolve beneficiary location: {exc}"
        ) from exc
    finally:
        if cursor is not None:
            cursor.close()

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
    """Merge organization results while retaining fields needed for distance."""
    output_columns = [
        "name",
        "location",
        "contact",
        "email",
        "web_url",
        "mission",
        "source",
        "db_or_ai",
    ]

    distance_columns = [
        "latitude",
        "longitude",
        "lat",
        "lng",
        "lon",
        "long",
        "coordinates",
        "address",
        "full_address",
        "street",
        "street_address",
        "city",
        "city_name",
        "state",
        "state_name",
        "state_code",
        "zip_code",
        "postal_code",
        "country",
        "country_name",
        "is_online",
        "online_only",
    ]

    db_organizations = db_organizations.copy().rename(
        columns={
            "org_name": "name",
            "city_name": "location",
            "phone": "contact",
        }
    )

    genAI_organizations = genAI_organizations.copy().rename(
        columns={"organization_name": "name"}
    )

    for frame in (db_organizations, genAI_organizations):
        for column in output_columns:
            if column not in frame.columns:
                frame[column] = None

    retained_distance_columns = [
        column
        for column in distance_columns
        if (
            column in db_organizations.columns
            or column in genAI_organizations.columns
        )
    ]

    columns = output_columns + retained_distance_columns

    return pd.concat(
        [
            db_organizations.reindex(columns=columns),
            genAI_organizations.reindex(columns=columns),
        ],
        ignore_index=True,
    )