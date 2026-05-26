import boto3
import json
import pg8000
from aws_lambda_powertools.utilities import parameters
import pandas as pd

s3_client = boto3.client('lambda')

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

def get_metric_numbers(data):
    '''
    totalRequests: 0,
    requestsResolved: 0,
    totalVolunteers: 0,
    totalBeneficiaries: 0
    '''

def get_requests_metrics():

    sql_query = '''
        select
            r.*,
            rs.req_status
        from {_db_name}.request as r
        left join {_db_name}.request_status as rs on rs.req_status_id = r.req_status_id

        '''
    df = pd.read_sql(sql_query)

    totalRequests = len(df)
    requestsResolved = len(df[df["req_status_id"] == 3])

    return {
        "totalRequests": totalRequests,
        "requestsResolved": requestsResolved
    }

def get_volunteers_metrics():
    
    sql_query = '''
        select
            *,
        from {_db_name}..volunteer_details
        '''
    df = pd.read_sql(sql_query)

    return {
        "totalVolunteers": len(df)
    }

def get_beneficiary_metrics():
    # sql_query = '''
    #     select
    #         *,
    #     from {_db_name}..volunteer_details
    #     '''
    # df = pd.read_sql(sql_query)

    return {
        "totalBeneficiaries": 99
    }

def get_metrics():
    try:

        requests_metrics = get_requests_metrics()
        volunteers_metrics = get_volunteers_metrics()
        beneficiaries_metrics = get_beneficiary_metrics()

        metrics = {**requests_metrics, **volunteers_metrics, **beneficiaries_metrics}

        return metrics

    except pg8000.DatabaseError as e:
        raise Exception(f'Database error: {str(e)}')
    except Exception as e:
        raise Exception(f'Error fetching from DB: {str(e)}')
    
def write_metrics_to_s3(metrics, bucket, file_path):
    s3_client.put_object(
    Bucket=bucket,
    Key=file_path,
    Body=json.dumps(metrics, indent=2),
    ContentType="application/json"
)


