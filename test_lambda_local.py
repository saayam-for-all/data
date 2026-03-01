import json
from categorize_request_lambda import handler

tests = [
    {
        "subject": "I need a place to stay tonight",
        "description": "I lost my apartment and I am homeless."
    },
    {
        "subject": "We have no food",
        "description": "My children are hungry and we need groceries."
    },
    {
        "subject": "Need winter jacket",
        "description": "I don’t have clothes for cold weather."
    },
    {
        "subject": "Need hospital help",
        "description": "I cannot afford medical treatment."
    },
    {
        "subject": "Looking for a job",
        "description": "I need help with resume and interview."
    },
    {
        "subject": "Random help",
        "description": "I just need some assistance."
    }
]

for i, test in enumerate(tests, start=1):
    event = {"body": json.dumps(test)}
    response = handler(event, None)
    print(f"\nTest Case {i}")
    print(response)