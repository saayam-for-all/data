import boto3
import json
import psycopg2
from aws_lambda_powertools.utilities import parameters

s3_client = boto3.client('s3')

_creds = json.loads(parameters.get_parameter(
    '/dev/saayam/db/Virginia/Analytics/user',
    decrypt=True,
    max_age=3600
))

_db_name = _creds['DATABASE NAME']

_db_conn = psycopg2.connect(
    host=_creds['HOST'],
    user=_creds['USERNAME'],
    password=_creds['PASSWORD'],
    database=_db_name,
    port=_creds['PORT'],
    sslmode='require'
)


def get_requests_metrics():
    cursor = _db_conn.cursor()

    cursor.execute(f"SELECT COUNT(*) FROM {_db_name}.request")
    totalRequests = cursor.fetchone()[0]

    cursor.execute(f"SELECT COUNT(*) FROM {_db_name}.request WHERE req_status_id = 3")
    requestsResolved = cursor.fetchone()[0]

    return {
        "totalRequests": totalRequests,
        "requestsResolved": requestsResolved
    }


def get_volunteers_metrics():
    cursor = _db_conn.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM {_db_name}.volunteer_details")
    return {"totalVolunteers": cursor.fetchone()[0]}


def get_beneficiary_metrics():
    cursor = _db_conn.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM {_db_name}.users")
    return {"totalBeneficiaries": cursor.fetchone()[0]}


def get_metrics():
    try:
        requests_metrics = get_requests_metrics()
        volunteers_metrics = get_volunteers_metrics()
        beneficiaries_metrics = get_beneficiary_metrics()

        return {**requests_metrics, **volunteers_metrics, **beneficiaries_metrics}

    except psycopg2.DatabaseError as e:
        raise Exception(f'Database error: {str(e)}')
    except Exception as e:
        raise Exception(f'Error fetching from DB: {str(e)}')


def write_metrics_to_s3(metrics, bucket, file_path):
    print("metrics:", metrics)
    s3_client.put_object(
        Bucket=bucket,
        Key=file_path,
        Body=json.dumps(metrics, indent=2),
        ContentType="application/json"
    )
