import boto3
import json
from aws_lambda_powertools.utilities import parameters
import pandas as pd
import pg8000

from org_distance import (
    DISTANCE_COLUMNS,
    DISTANCE_METHOD,
    DISTANCE_UNIT,
    STATUS_ERROR,
    CoordinateCache,
    beneficiary_from_body,
    configure,
    distance_fields_for_ai_orgs,
    distance_fields_for_db_orgs,
)


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

# Distance (#433): same schema as the org queries; geocode cache reused on warm starts
configure(schema=_db_name)
_geo_cache = CoordinateCache()
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


def get_beneficiary_location(body):
    """Beneficiary/request location (#433) – never the viewer's location. Never raises."""
    return beneficiary_from_body(body, _db_conn, cache=_geo_cache)


def add_distance_columns(orgs_df, beneficiary, db_or_ai):
    """
    Add distance, distance_unit, distance_method, distance_status to each org (#433).
    Distance problems never drop an organization or fail the request.
    """
    records = orgs_df.to_dict(orient='records')
    try:
        if db_or_ai == "db":
            fields = distance_fields_for_db_orgs(records, beneficiary, _db_conn, cache=_geo_cache)
        else:
            fields = distance_fields_for_ai_orgs(records, beneficiary, cache=_geo_cache)
    except Exception:
        fields = [{
            "distance": None,
            "distance_unit": DISTANCE_UNIT,
            "distance_method": DISTANCE_METHOD,
            "distance_status": STATUS_ERROR,
        } for _ in records]

    orgs_df = orgs_df.copy()
    for col in DISTANCE_COLUMNS:
        # dtype=object keeps None as JSON null (a float column would turn it into NaN)
        orgs_df[col] = pd.Series([f[col] for f in fields], index=orgs_df.index, dtype=object)
    return orgs_df


def merge_organizations(db_organizations, genAI_organizations):
    try:
        output_columns = ['name', 'location', 'contact', 'email', 'web_url', 'mission', 'source', "db_or_ai"]
        output_columns += [c for c in DISTANCE_COLUMNS
                           if c in db_organizations.columns and c in genAI_organizations.columns]

        db_organizations = db_organizations.rename(columns={
            'org_name': 'name',
            'city_name': 'location',
            'phone': 'contact'
        })[output_columns]

        genAI_organizations = genAI_organizations.rename(columns={
            'organization_name': 'name'
        })[output_columns]

        return pd.concat([db_organizations, genAI_organizations], ignore_index=True)
    except KeyError as e:
        raise Exception(f'Missing expected column during merge: {str(e)}')
    except Exception as e:
        raise Exception(f'Error merging organizations: {str(e)}')
