"""Run Amazon Comprehend DetectPiiEntities over the test set (approach 3).

usage: python3 run_comprehend.py <out_spans.json> [region]      # real run, needs boto3 + AWS creds
       python3 run_comprehend.py --dry-run                      # plumbing check with a fake client, NO accuracy info

Real run needs credentials allowed to call comprehend:DetectPiiEntities (free-tier account is fine; ~84 calls).
Then: python3 -I run_eval.py <users.csv> out out/comprehend_spans.json   -> adds the 3_patterns_comprehend row.
Latency printed here is wall-clock per synchronous API call (includes network).
"""
import importlib.util
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


T, C = load("testset"), load("comprehend_pii")


class _EmptyFake:
    """--dry-run client: returns no entities. Proves wiring only; says nothing about Comprehend accuracy."""
    def detect_pii_entities(self, Text, LanguageCode):
        return {"Entities": []}


def main():
    if "--dry-run" in sys.argv:
        client, out_path = _EmptyFake(), None
        print("DRY RUN: fake client, results are NOT measurements of Comprehend.")
    else:
        if len(sys.argv) < 2:
            sys.exit(__doc__)
        import boto3                      # imported only for the real run
        out_path = sys.argv[1]
        client = boto3.client("comprehend", region_name=sys.argv[2] if len(sys.argv) > 2 else "us-east-1")

    result, times = {}, []
    for text, _ in T.DEV + T.HELDOUT:
        a = time.perf_counter()
        spans = C.comprehend_spans(text, client)     # raises on AccessDenied etc. so you see the real error
        times.append(time.perf_counter() - a)
        result[text] = [list(s) for s in spans]
    times.sort()
    print(f"calls={len(times)} mean_ms={1000*sum(times)/len(times):.2f} p95_ms={1000*times[int(.95*(len(times)-1))]:.2f}")
    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        json.dump(result, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("wrote", out_path)


if __name__ == "__main__":
    main()
