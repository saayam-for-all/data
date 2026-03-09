from dotenv import load_dotenv
load_dotenv()

import boto3
import json
import os
import pandas as pd


GEN_AI_LAMBDA = "More_Org_GenAI_Py_v3126"


def get_ai_orgs(subject: str, description: str, location: str) -> pd.DataFrame:
    """Fetches AI-suggested orgs from GenAI Lambda. Only called in production — mock in local tests."""
    try:
        client = boto3.client('lambda', region_name=os.getenv('AWS_REGION'))
        response = client.invoke(
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
        orgs["is_collaborator"] = False
        orgs["db_or_ai"] = "ai"
        if "org_type" not in orgs.columns:
            orgs["org_type"] = "non_profit"
        return orgs
    except Exception as e:
        raise Exception(f'Error fetching AI orgs: {str(e)}')