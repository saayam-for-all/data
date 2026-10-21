import boto3
import json
from aws_lambda_powertools.utilities import parameters
import pandas as pd
import pg8000
from distance import (
    CoordinateCache, DbCoordinateStore, add_distances, build_address,
    get_beneficiary_coordinates,
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
_coord_cache = CoordinateCache(DbCoordinateStore(_db_conn, _db_name))
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


ADDRESS_COLUMNS = ['street', 'state_code', 'zip_code', 'address']


def merge_organizations(db_organizations, genAI_organizations):
    try:
        base = ['name', 'location', 'contact', 'email', 'web_url', 'mission', 'source', "db_or_ai"]
        db_organizations = db_organizations.rename(columns={
            'org_name': 'name',
            'city_name': 'location',
            'phone': 'contact'
        })
        genAI_organizations = genAI_organizations.rename(columns={
            'organization_name': 'name'
        })
        # Address columns are optional (used only to compute distance).
        cols = base + ADDRESS_COLUMNS
        db_organizations = db_organizations[base + [c for c in ADDRESS_COLUMNS if c in db_organizations]]
        genAI_organizations = genAI_organizations[base + [c for c in ADDRESS_COLUMNS if c in genAI_organizations]]

        return pd.concat([db_organizations, genAI_organizations], ignore_index=True).reindex(columns=cols)
    except KeyError as e:
        raise Exception(f'Missing expected column during merge: {str(e)}')
    except Exception as e:
        raise Exception(f'Error merging organizations: {str(e)}')


def _org_address(org):
    """Full address for geocoding. GenAI orgs use their own address/location;
    DB orgs use street, city, state, zip."""
    if org.get('db_or_ai') == 'ai':
        return build_address(org.get('address') or org.get('location'))
    return build_address(org.get('street'), org.get('location'),
                         org.get('state_code'), org.get('zip_code'))


def attach_distances(combined, request_id):
    """Return list of org dicts with distance fields. Never raises: on any
    failure the orgs are returned with distance=None."""
    orgs = combined.astype(object).where(combined.notna(), None).to_dict(orient='records')
    try:
        beneficiary = get_beneficiary_coordinates(_db_conn, _db_name, request_id, _coord_cache)
    except Exception:
        try:
            _db_conn.rollback()
        except Exception:
            pass
        beneficiary = None
    result = add_distances(orgs, beneficiary, _coord_cache, _org_address)
    for org in result:
        for c in ADDRESS_COLUMNS:
            org.pop(c, None)
    return result
