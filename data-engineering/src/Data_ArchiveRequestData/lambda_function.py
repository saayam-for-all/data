import json
import os
from helpers import parse_timestamp, run_archive


def bad_request(message):
    return {'statusCode': 400, 'body': json.dumps({'error': message})}


def lambda_handler(event, context):
    try:
        event = event or {}
        raw_body = event.get('body')
        body = json.loads(raw_body) if isinstance(raw_body, str) else event
        if not isinstance(body, dict):
            return bad_request('request body must be a JSON object')

        # the schedule can send nothing and rely on the environment
        bucket = body.get('bucket') or os.environ.get('BUCKET')
        prefix = body.get('prefix') or os.environ.get('S3_PREFIX') or 'request_archive'
        range_from = body.get('from')
        range_to = body.get('to')

        if not bucket or not isinstance(bucket, str):
            return bad_request('bucket is required')
        if not isinstance(prefix, str):
            return bad_request('prefix must be a string')
        prefix = prefix.strip('/')
        if (range_from is None) != (range_to is None):
            return bad_request('from and to have to be sent together')
        if range_from is not None:
            try:
                if parse_timestamp(range_from) > parse_timestamp(range_to):
                    return bad_request('from cannot be after to')
            except ValueError as e:
                return bad_request(f'from and to must be timestamps like 2026-01-01 00:00:00 ({e})')

        result = run_archive(bucket, prefix, range_from, range_to)
        print(json.dumps(result))

        if result['status'] == 'failed':
            # nothing was written to S3 and the watermark did not move
            return {'statusCode': 500, 'body': json.dumps({'error': 'validation failed', **result})}

        return {'statusCode': 200, 'body': json.dumps(result)}

    except json.JSONDecodeError as e:
        return bad_request(f'Invalid JSON in request body: {str(e)}')
    except Exception as e:
        return {'statusCode': 500, 'body': json.dumps({'error': f'Internal server error: {str(e)}'})}
