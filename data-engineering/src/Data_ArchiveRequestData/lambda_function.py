import json
from helpers import run_archive


def bad_request(message):
    return {'statusCode': 400, 'body': json.dumps({'error': message})}


def lambda_handler(event, context):
    try:
        raw_body = event.get('body')
        body = json.loads(raw_body) if isinstance(raw_body, str) else event
        if not isinstance(body, dict):
            return bad_request('request body must be a JSON object')

        bucket = body.get('bucket')
        shared_bucket = body.get('shared_bucket')
        prefix = body.get('prefix') or 'request_archive'
        statuses = body.get('statuses')

        if not bucket or not isinstance(bucket, str):
            return bad_request('bucket is required')
        if shared_bucket is not None and not isinstance(shared_bucket, str):
            return bad_request('shared_bucket must be a string')
        if not isinstance(prefix, str):
            return bad_request('prefix must be a string')
        prefix = prefix.strip('/')
        if statuses is not None:
            if not isinstance(statuses, list) or not statuses or \
                    not all(isinstance(s, int) and not isinstance(s, bool) for s in statuses):
                return bad_request('statuses must be a non-empty list of req_status_id integers')

        result = run_archive(bucket, shared_bucket, prefix, statuses)
        print(json.dumps(result))

        if result['errors']:
            # nothing was written to S3
            return {'statusCode': 500, 'body': json.dumps({'error': 'validation failed', **result})}

        return {'statusCode': 200, 'body': json.dumps(result)}

    except json.JSONDecodeError as e:
        return bad_request(f'Invalid JSON in request body: {str(e)}')
    except Exception as e:
        return {'statusCode': 500, 'body': json.dumps({'error': f'Internal server error: {str(e)}'})}
