"""
Local test script for auto_categorize_requests (issue #100).
From data-engineering/:  python -m src.auto_categorize_requests.local_test
"""
import json
import os
import sys

if __name__ == "__main__" and __package__ is None:
    _here = os.path.dirname(os.path.abspath(__file__))
    _src = os.path.dirname(_here)
    _de = os.path.dirname(_src)
    for _d in (_src, _de):
        if _d not in sys.path:
            sys.path.insert(0, _d)
    __package__ = "src.auto_categorize_requests"

from .classifier import classify_help_request


def run_interactive():
    print("Local Help Request Classifier (auto_categorize_requests)")
    print("Make sure OPENAI_API_KEY is set in your environment.")
    print("Press Enter on an empty subject to exit.\n")

    while True:
        subject = input("Subject: ").strip()
        if not subject:
            print("Exiting.")
            break
        print("Description (end with an empty line):")
        lines = []
        while True:
            line = input()
            if not line:
                break
            lines.append(line)
        description = "\n".join(lines)

        result = classify_help_request(subject=subject, description=description)
        print("\nResult:")
        print(json.dumps(result.__dict__, indent=2, ensure_ascii=False))
        print("-" * 40)


def run_sample_batch():
    samples = [
        {
            "subject": "I need a place to stay tonight",
            "description": "I just lost my apartment and I'm on the streets. I have two kids with me.",
        },
        {
            "subject": "Need help with food",
            "description": "I haven't had a proper meal in days and need food assistance.",
        },
        {
            "subject": "Looking for a job",
            "description": "I lost my job recently and need help finding new work.",
        },
        {
            "subject": "Therapy options",
            "description": "I'm struggling with anxiety and would like to talk to someone.",
        },
        {"subject": "", "description": ""},
    ]

    print("Running sample batch classification...")
    for idx, sample in enumerate(samples, start=1):
        res = classify_help_request(sample["subject"], sample["description"])
        print(f"\nSample {idx}:")
        print(json.dumps(res.__dict__, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    if not os.getenv("OPENAI_API_KEY"):
        print("WARNING: OPENAI_API_KEY is not set; OpenAI calls will fail.\n")

    mode = os.getenv("TEST_MODE", "interactive").lower()
    if mode == "batch":
        run_sample_batch()
    else:
        run_interactive()
