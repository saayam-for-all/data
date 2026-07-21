from volunteer_application_analytics import lambda_handler
import json

if __name__ == "__main__":
    with open("local_event.json") as f:
        event = json.load(f)

    result = lambda_handler(event, None)
    print(json.dumps(result, indent=4))
