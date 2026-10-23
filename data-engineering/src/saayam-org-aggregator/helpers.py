import boto3
import json
import os
import threading
import pandas as pd
import pg8000


GEN_AI_LAMBDA = "More_Org_GenAI_Py_v3126"

# LOCAL_TESTING=1 connects to a local Postgres from LOCAL_DB_* env vars and
# never calls SSM. Unset (production), behavior is unchanged.
LOCAL_TESTING = os.environ.get("LOCAL_TESTING", "").strip().lower() in ("1", "true", "yes")

# --- All cached at module level, initialized once on cold start ---
if LOCAL_TESTING:
    lambda_client = None  # created on first real GenAI call, if any
    _db_name = os.environ["LOCAL_DB_NAME"]
    _db_conn = pg8000.connect(
        host=os.environ["LOCAL_DB_HOST"],
        user=os.environ["LOCAL_DB_USER"],
        password=os.environ["LOCAL_DB_PASSWORD"],
        database=_db_name,
        port=int(os.environ.get("LOCAL_DB_PORT", "5432"))
    )
else:
    from aws_lambda_powertools.utilities import parameters

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

# pg8000 connections are not thread-safe; the handler queries from threads.
_db_lock = threading.Lock()
# -----------------------------------------------------------------

def get_orgs_from_db(location, category):
    try:
        with _db_lock:
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


def run_query(sql: str, params: tuple = ()) -> list[dict]:
    """Run a parameterized (%s) query and return rows as dicts.

    Rolls back on failure so a bad query can't leave the shared connection
    in an aborted transaction for later queries.
    """
    with _db_lock:
        cursor = _db_conn.cursor()
        try:
            cursor.execute(sql, params)
            names = [d[0] for d in cursor.description or []]
            return [dict(zip(names, row)) for row in cursor.fetchall()]
        except Exception:
            _db_conn.rollback()
            raise
        finally:
            cursor.close()


def _invoke_genai_lambda(request_payload: dict) -> dict:
    """Invoke the GenAI Lambda and return its decoded response payload.

    With LOCAL_TESTING and LOCAL_GENAI_MOCK_FILE set, the payload is read
    from that JSON file instead.
    """
    global lambda_client
    mock_file = os.environ.get("LOCAL_GENAI_MOCK_FILE") if LOCAL_TESTING else None
    if mock_file:
        with open(mock_file, encoding="utf-8") as f:
            return json.load(f)
    if lambda_client is None:
        lambda_client = boto3.client('lambda')
    response = lambda_client.invoke(
        FunctionName=GEN_AI_LAMBDA,
        InvocationType='RequestResponse',
        Payload=json.dumps(request_payload)
    )
    return json.loads(response['Payload'].read())


def get_ai_orgs(subject, description, location):
    try:
        payload = _invoke_genai_lambda({
            "subject": subject,
            "description": description,
            "location": location
        })
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


# Distance fields (issue #433) appended after the original response keys.
DISTANCE_RESPONSE_COLUMNS = ["distance", "distance_unit", "distance_method", "distance_status"]


def merge_organizations(db_organizations, genAI_organizations):
    """Merge DB and GenAI orgs; either side may be None if its source failed."""
    try:
        frames = []
        if db_organizations is not None:
            frames.append(db_organizations.rename(columns={
                'org_name': 'name',
                'city_name': 'location',
                'phone': 'contact'
            })[['name', 'location', 'contact', 'email', 'web_url', 'mission', 'source', "db_or_ai"]
               + DISTANCE_RESPONSE_COLUMNS])

        if genAI_organizations is not None:
            frames.append(genAI_organizations.rename(columns={
                'organization_name': 'name'
            })[['name', 'location', 'contact', 'email', 'web_url', 'mission', 'source', "db_or_ai"]
               + DISTANCE_RESPONSE_COLUMNS])

        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)
    except KeyError as e:
        raise Exception(f'Missing expected column during merge: {str(e)}')
    except Exception as e:
        raise Exception(f'Error merging organizations: {str(e)}')
