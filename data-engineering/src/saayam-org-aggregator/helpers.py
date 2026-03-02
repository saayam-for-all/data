import subprocess
import boto3
import sys
import json
from aws_lambda_powertools.utilities import parameters
import pandas as pd

subprocess.call([sys.executable, "-m", "pip", "install", "pg8000", "-t", "/tmp/"])
sys.path.insert(0, "/tmp/")
import pg8000

GEN_AI_LAMBDA = "More_Org_GenAI_Py_v3126"

def get_orgs_from_db(location, category):
    try:
        creds = json.loads(parameters.get_parameter(
            '/dev/saayam/db/Virginia/Analytics/user',
            decrypt=True,
            max_age=3600
        ))
        database = creds['DATABASE NAME']

        conn = pg8000.connect(
            host=creds['HOST'],
            user=creds['USERNAME'],
            password=creds['PASSWORD'],
            database=database,
            port=creds['PORT'],
            ssl_context=True
        )

        df = pd.read_sql(
            f"SELECT * FROM {database}.organizations WHERE mission = '{category}' AND city_name = '{location}'",
            conn
        )
        conn.close()
        return df

    except parameters.GetParameterError as e:
        raise Exception(f'Failed to retrieve DB credentials: {str(e)}')
    except pg8000.DatabaseError as e:
        raise Exception(f'Database error: {str(e)}')
    except Exception as e:
        raise Exception(f'Error fetching from DB: {str(e)}')


def get_ai_orgs(subject, description, location):
    try:
        response = boto3.client('lambda').invoke(
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

        return pd.DataFrame(payload['body']['organizations'])

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
        })[['name', 'location', 'contact', 'email', 'web_url', 'mission', 'source']]

        genAI_organizations = genAI_organizations.rename(columns={
            'organization_name': 'name'
        })[['name', 'location', 'contact', 'email', 'web_url', 'mission', 'source']]

        return pd.concat([db_organizations, genAI_organizations], ignore_index=True)

    except KeyError as e:
        raise Exception(f'Missing expected column during merge: {str(e)}')
    except Exception as e:
        raise Exception(f'Error merging organizations: {str(e)}')