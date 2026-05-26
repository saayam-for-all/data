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
        })[['name', 'location', 'contact', 'email', 'web_url', 'mission', 'source', "db_or_ai"]]

        genAI_organizations = genAI_organizations.rename(columns={
            'organization_name': 'name'
        })[['name', 'location', 'contact', 'email', 'web_url', 'mission', 'source', "db_or_ai"]]

        return pd.concat([db_organizations, genAI_organizations], ignore_index=True)
    except KeyError as e:
        raise Exception(f'Missing expected column during merge: {str(e)}')
    except Exception as e:
        raise Exception(f'Error merging organizations: {str(e)}')