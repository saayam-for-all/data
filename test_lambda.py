import json
from lambda_function import lambda_handler

# load json event
with open("event.json") as f:
    event = json.load(f)

# call lambda locally
response = lambda_handler(event, None)

print("Lambda response:")
print(json.dumps(response, indent=2))
