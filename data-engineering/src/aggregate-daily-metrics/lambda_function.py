import json
from helpers import get_metrics, write_metrics_to_s3

def lambda_handler(event, context):
    try:

        bucket = "saayam-virginia-public/",
        file_path ="homepage_metrics/metrics.json"
        
        raw_body = event.get("body")
        body = None

        if(isinstance(raw_body, str)):
            body = json.loads(raw_body)
        else:
            body = event

        metrics = get_metrics()

        print(metrics)

        write_metrics_to_s3(metrics, bucket, file_path)

        return {
            "statusCode": 200,
        }

    except json.JSONDecodeError as e:
        return {'statusCode': 400, 'body': json.dumps({'error': f'Invalid JSON in request body: {str(e)}'})}
    except Exception as e:
        return {'statusCode': 500, 'body': json.dumps({'error': f'Internal server error: {str(e)}'})}


