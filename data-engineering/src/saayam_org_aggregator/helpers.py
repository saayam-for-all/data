from dotenv import load_dotenv
load_dotenv()  # Must be called BEFORE any boto3/AWS code

import boto3
import json
import os
from aws_lambda_powertools.utilities import parameters
import pandas as pd
import pg8000

GEN_AI_LAMBDA = "More_Org_GenAI_Py_v3126"

# --- Initialized once on cold start ---
lambda_client = boto3.client('lambda')

# Fetch credentials (AWS Parameter Store)
try:
    _creds = json.loads(parameters.get_parameter(
        '/dev/saayam/db/Virginia/Analytics/user',
        decrypt=True,
        max_age=3600
    ))
except Exception:
    # Fallback for local development using your .env
    _creds = {
        'HOST': os.getenv('HOST'),
        'USERNAME': os.getenv('USERNAME'),
        'PASSWORD': os.getenv('PASSWORD'),
        'PORT': int(os.getenv('PORT', 5432))
    }

# Environment-aware database name
_db_name = _creds.get('DATABASE NAME') or os.getenv('DATABASE_NAME') or os.getenv('DATABASE NAME')

_db_conn = pg8000.connect(
    host=_creds['HOST'],
    user=_creds['USERNAME'],
    password=_creds['PASSWORD'],
    database=_db_name,
    port=_creds['PORT'],
    ssl_context=True
)

def get_orgs_from_db(location, category):
    """Fetches organizations and handles the is_collaborator schema safety."""
    try:
        # Full query with new fields
        query = f"SELECT org_name, city_name, phone, email, web_url, mission, source, org_type, is_collaborator FROM {_db_name}.organizations WHERE mission = '{category}' AND city_name = '{location}'"
        
        df = pd.read_sql(query, _db_conn)
        df["db_or_ai"] = "db"
        return df
    except Exception as e:
        # Fallback if the column doesn't exist yet in the DB
        if "is_collaborator" in str(e):
            fallback_query = f"SELECT org_name, city_name, phone, email, web_url, mission, source, org_type FROM {_db_name}.organizations WHERE mission = '{category}' AND city_name = '{location}'"
            df = pd.read_sql(fallback_query, _db_conn)
            df["is_collaborator"] = False # Default for local testing
            df["db_or_ai"] = "db"
            return df
        raise Exception(f'Database error: {str(e)}')

def get_ai_orgs(subject, description, location):
    """Fetches from GenAI and flags as non-collaborators."""
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
        
        orgs = pd.DataFrame(payload['body']['organizations'])
        orgs["is_collaborator"] = False # AI results are not verified collaborators
        orgs["db_or_ai"] = "ai"
        
        if "org_type" not in orgs.columns:
            orgs["org_type"] = "non_profit"
            
        return orgs
    except Exception as e:
        raise Exception(f'Error fetching AI orgs: {str(e)}')

def merge_organizations(db_organizations, genAI_organizations):
    """Merges sources and pins collaborators to the top."""
    try:
        # Rename for UI consistency
        db_orgs = db_organizations.rename(columns={'org_name': 'name', 'city_name': 'location', 'phone': 'contact'})
        ai_orgs = genAI_organizations.rename(columns={'organization_name': 'name'})

        combined_df = pd.concat([db_orgs, ai_orgs], ignore_index=True)

        # PINNING LOGIC: Sort True (Collaborators) to the top
        combined_df = combined_df.sort_values(by='is_collaborator', ascending=False)

        # Final UI Schema
        cols = ['name', 'location', 'contact', 'email', 'web_url', 'mission', 'source', 'org_type', 'is_collaborator', 'db_or_ai']
        return combined_df[[c for c in cols if c in combined_df.columns]]
    except Exception as e:
        raise Exception(f'Merge error: {str(e)}')