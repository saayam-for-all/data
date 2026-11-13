
import csv
import statistics
import time
from collections import defaultdict
from pathlib import Path

from methods.regex_masking import mask_pii
from methods.lookup_masking import (
    load_user_names,
    mask_pii_with_lookup,
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


def read_csv(filename):
    with (DATA_DIR / filename).open(
        newline="", encoding="utf-8-sig"
    ) as file:
        return list(csv.DictReader(file))


def benchmark(method_name, masking_function, requests, annotations):
    annotations_by_id = defaultdict(list)

    for annotation in annotations:
        annotations_by_id[annotation["request_id"]].append(annotation)

    # Warm up before timing.
    for request in requests:
        masking_function(request["description"])

    durations = []
    outputs = {}

    # Repeated measurements reduce single-run timing noise.
    for _ in range(100):
        start = time.perf_counter()

        for request in requests:
            outputs[request["id"]] = masking_function(
                request["description"]
            )

        durations.append((time.perf_counter() - start) * 1000)

    caught = 0
    missed = 0
    false_positives = 0
    fully_masked_requests = 0
    partially_masked_requests = 0

    missed_examples = []

    for request in requests:
        request_id = request["id"]
        original = request["description"]
        masked = outputs[request_id]
        expected = annotations_by_id[request_id]

        if not expected:
            if original != masked:
                false_positives += 1
            continue

        remaining = []

        for annotation in expected:
            value = annotation["pii_value"]

            if value in masked:
                missed += 1
                remaining.append(value)
            else:
                caught += 1

        if not remaining:
            fully_masked_requests += 1
        elif len(remaining) < len(expected):
            partially_masked_requests += 1

        if remaining:
            missed_examples.append({
                "id": request_id,
                "remaining": remaining,
            })

    median_ms = statistics.median(durations)

    print(f"\n{method_name}")
    print("-" * 45)
    print(f"Total requests: {len(requests)}")
    print(f"PII values removed: {caught}")
    print(f"PII values remaining: {missed}")
    print(f"Fully masked PII requests: {fully_masked_requests}")
    print(f"Partially masked requests: {partially_masked_requests}")
    print(f"False-positive clean requests: {false_positives}")
    print(f"Median processing time: {median_ms:.3f} ms")

    print("\nMissed PII examples:")
    for example in missed_examples:
        print(
            f"  Request {example['id']}: "
            f"{example['remaining']}"
        )


def main():
    requests = read_csv("extended_requests.csv")
    annotations = read_csv("extended_annotations.csv")

    names = load_user_names()

    benchmark(
        "METHOD 1: REGEX",
        mask_pii,
        requests,
        annotations,
    )

    benchmark(
        "METHOD 2: REGEX + USERS LOOKUP",
        lambda text: mask_pii_with_lookup(text, names),
        requests,
        annotations,
    )


if __name__ == "__main__":
    main()
