"""Benchmark PII detection approaches on the Issue #585 synthetic dataset.

Run from ``data-engineering/``::

    python -m scripts.benchmark_pii_detection
    python -m scripts.benchmark_pii_detection --output docs/pii_masking_evaluation_585_results.json

Approach C calls Amazon Comprehend, which is billable. It runs only when both
flags are given and AWS credentials with ``comprehend:DetectPiiEntities`` exist::

    python -m scripts.benchmark_pii_detection --comprehend --allow-billable-aws-calls
"""

from __future__ import annotations

import argparse
import json
import platform
import random
import re
import sys
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from src.pii_evaluation import name_cues, patterns
from src.pii_evaluation.comprehend import (
    ComprehendPiiDetector,
    comprehend_availability,
    create_comprehend_client,
)
from src.pii_evaluation.costs import (
    COMPREHEND_PRICE_PER_UNIT_USD,
    comprehend_monthly_cost,
    comprehend_units,
    lambda_compute_cost,
)
from src.pii_evaluation.dataset import LabeledRequest, load_binary_dataset, load_dataset
from src.pii_evaluation.detectors import Approach, approach_a, approach_b, approach_c, approach_d
from src.pii_evaluation.metrics import document_metrics, entity_metrics, latency_summary
from src.pii_evaluation.name_lookup import NameIndex
from src.pii_evaluation.spans import redact

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "pii_evaluation"
DEFAULT_DATASET = FIXTURE_DIR / "request_texts.jsonl"
DEFAULT_USERS = FIXTURE_DIR / "synthetic_users.csv"
VOLUMES = (1_000, 10_000, 100_000)
ASSUMED_COMPREHEND_LATENCY_MS = (50, 100, 200)
LAMBDA_MEMORY_MB = 512


def _compile_seconds(sources: list[tuple[str, int]]) -> float:
    """Time to compile regex sources with the ``re`` cache cleared."""
    re.purge()
    started = time.perf_counter()
    for source, flags in sources:
        re.compile(source, flags)
    return time.perf_counter() - started


def _module_patterns(*modules) -> list[tuple[str, int]]:
    found = []
    for module in modules:
        for value in vars(module).values():
            if isinstance(value, re.Pattern):
                found.append((value.pattern, value.flags))
            elif isinstance(value, list):
                found += [(item.pattern, item.flags) for item in value if isinstance(item, re.Pattern)]
    return found


def _timed(build: Callable[[], object]) -> tuple[object, float]:
    started = time.perf_counter()
    value = build()
    return value, time.perf_counter() - started


def build_local_approaches(users_path: Path) -> list[tuple[Approach, float, str]]:
    """Return (approach, initialisation seconds, what initialisation covers)."""
    baseline_compile = _compile_seconds([(p.pattern, p.flags) for _, p in patterns.BASELINE_PATTERNS])
    enhanced_compile = _compile_seconds(_module_patterns(patterns, name_cues))
    index, index_seconds = _timed(lambda: NameIndex.from_csv(users_path))
    return [
        (approach_a(), baseline_compile, "regex compilation"),
        (approach_b(index, "full"), baseline_compile + index_seconds,
         "regex compilation + users name index build from CSV"),
        (approach_b(index, "token"), baseline_compile + index_seconds,
         "regex compilation + users name index build from CSV"),
        (approach_d(index), enhanced_compile + index_seconds,
         "regex compilation + users name index build from CSV"),
    ]


def run_accuracy(approach: Approach, dataset: list[LabeledRequest]) -> dict:
    """One pass over the dataset: document and entity metrics plus error lists."""
    predictions = {request.id: approach.find_spans(request.text) for request in dataset}
    gold = [request.contains_pii for request in dataset]
    predicted = [bool(predictions[request.id]) for request in dataset]
    documents = document_metrics(gold, predicted)

    by_tag: dict[str, dict[str, int]] = {}
    for request, guess in zip(dataset, predicted):
        for tag in request.tags:
            bucket = by_tag.setdefault(tag, {"texts": 0, "flagged": 0, "contains_pii": 0})
            bucket["texts"] += 1
            bucket["flagged"] += guess
            bucket["contains_pii"] += request.contains_pii

    missed_entities = []
    for request in dataset:
        for gold_entity in request.entities:
            if not any(span.start < gold_entity.end and gold_entity.start < span.end
                       for span in predictions[request.id]):
                missed_entities.append({"id": request.id, "type": gold_entity.type,
                                        "text": gold_entity.text})
    return {
        "document": documents.as_dict(),
        "entity": entity_metrics(dataset, predictions),
        "by_tag": dict(sorted(by_tag.items())),
        "missed_texts": [r.id for r, g in zip(dataset, predicted) if r.contains_pii and not g],
        "wrongly_redacted_clean_texts": [r.id for r, g in zip(dataset, predicted)
                                         if not r.contains_pii and g],
        "missed_entities": missed_entities,
        "redacted": {request.id: redact(request.text, predictions[request.id]) for request in dataset},
    }


def run_latency(approach: Approach, dataset: list[LabeledRequest], repeat: int, warmup: int) -> dict:
    """Per-text detection plus redaction latency over ``repeat`` timed passes."""
    for _ in range(warmup):
        for request in dataset:
            approach.redact(request.text)
    samples = []
    started = time.perf_counter()
    for _ in range(repeat):
        for request in dataset:
            begin = time.perf_counter_ns()
            approach.redact(request.text)
            samples.append(time.perf_counter_ns() - begin)
    summary = latency_summary(samples)
    summary["timed_passes"] = repeat
    summary["wall_seconds"] = time.perf_counter() - started
    return summary


def _synthetic_user_rows(count: int, seed: int) -> list[dict[str, str]]:
    generator = random.Random(seed)
    syllables = ["ka", "ri", "mo", "an", "el", "si", "tu", "na", "ve", "lo", "da", "mi",
                 "ra", "zo", "be", "ha", "ne", "go", "ya", "fi", "ol", "us", "te", "qu"]
    rows = []
    for number in range(count):
        first = "".join(generator.choice(syllables) for _ in range(generator.randint(2, 3)))
        last = "".join(generator.choice(syllables) for _ in range(generator.randint(2, 4)))
        rows.append({"user_id": f"SCALE-{number}", "first_name": first.title(),
                     "middle_name": "", "last_name": last.title(),
                     "full_name": f"{first.title()} {last.title()}"})
    return rows


def run_name_index_scaling(dataset: list[LabeledRequest], sizes: list[int], seed: int) -> list[dict]:
    """Index build time, memory and per-text lookup latency for larger users tables."""
    results = []
    for size in sizes:
        rows = _synthetic_user_rows(size, seed)
        tracemalloc.start()
        index, build_seconds = _timed(lambda: NameIndex.from_user_rows(rows))
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        samples = []
        for _ in range(5):
            for request in dataset:
                begin = time.perf_counter_ns()
                index.find_spans(request.text, mode="full")
                samples.append(time.perf_counter_ns() - begin)
        results.append({
            "users": size,
            "distinct_full_names": len(index),
            "index_build_seconds": build_seconds,
            "index_build_peak_memory_mb": peak_bytes / 1_048_576,
            "lookup_latency": latency_summary(samples),
        })
    return results


def estimate_costs(dataset: list[LabeledRequest], latencies: dict[str, dict]) -> dict:
    """Monthly cost estimates. All volumes and Comprehend latencies are assumptions."""
    lengths = [len(request.text) for request in dataset]
    comprehend = {}
    for volume in VOLUMES:
        comprehend[str(volume)] = {
            "one_call_per_request_usd": comprehend_monthly_cost(lengths, volume, 1),
            "two_calls_per_request_usd": comprehend_monthly_cost(lengths, volume, 2),
            "lambda_wait_usd_by_assumed_latency_ms": {
                str(ms): lambda_compute_cost(ms / 1000, volume, LAMBDA_MEMORY_MB)
                for ms in ASSUMED_COMPREHEND_LATENCY_MS
            },
        }
    local = {
        key: {str(volume): lambda_compute_cost(summary["mean_us"] / 1_000_000, volume,
                                               LAMBDA_MEMORY_MB)
              for volume in VOLUMES}
        for key, summary in latencies.items()
    }
    return {
        "text_length_characters": {"min": min(lengths), "max": max(lengths),
                                   "mean": sum(lengths) / len(lengths)},
        "comprehend_units_per_call": sorted({comprehend_units(length) for length in lengths}),
        "comprehend_price_per_unit_usd": COMPREHEND_PRICE_PER_UNIT_USD,
        "lambda_memory_mb": LAMBDA_MEMORY_MB,
        "comprehend_by_monthly_volume": comprehend,
        "local_approaches_lambda_compute_usd_by_monthly_volume": local,
    }


def _baseline_equivalence(dataset: list[LabeledRequest]) -> dict:
    """Check the span-based Approach A redacts exactly like the existing scrubber."""
    approach = approach_a()
    mismatches = []
    for request in dataset:
        expected = patterns.baseline_scrub_text(request.text, {}).replace("[SSN]", "[NATIONAL_ID]")
        if expected != approach.redact(request.text):
            mismatches.append(request.id)
    return {"texts_compared": len(dataset), "mismatched_ids": mismatches}


def run_external(approaches: list[Approach], external: list[LabeledRequest]) -> dict:
    """Document-level results on a held-out set written by someone else."""
    gold = [request.contains_pii for request in external]
    results = {}
    for approach in approaches:
        predicted = [approach.contains_pii(request.text) for request in external]
        results[approach.key] = {
            "name": approach.name,
            "document": document_metrics(gold, predicted).as_dict(),
            "missed_texts": [r.id for r, g in zip(external, predicted) if r.contains_pii and not g],
            "wrongly_redacted_clean_texts": [r.id for r, g in zip(external, predicted)
                                             if not r.contains_pii and g],
        }
    return results


def run(dataset_path: Path, users_path: Path, repeat: int, warmup: int,
        scale_sizes: list[int], seed: int, comprehend_client=None,
        comprehend_language: str = "en", comprehend_status: dict | None = None,
        external_path: Path | None = None) -> dict:
    """Run the full benchmark and return a JSON-serialisable result."""
    total_started = time.perf_counter()
    dataset = load_dataset(dataset_path)
    results: dict = {
        "issue": 585,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "machine": platform.machine(), "processor": platform.processor()},
        "settings": {"repeat": repeat, "warmup": warmup, "seed": seed},
        "dataset": {
            "path": str(dataset_path.relative_to(PROJECT_ROOT)
                        if dataset_path.is_relative_to(PROJECT_ROOT) else dataset_path),
            "texts": len(dataset),
            "pii_texts": sum(r.contains_pii for r in dataset),
            "clean_texts": sum(not r.contains_pii for r in dataset),
            "entities": sum(len(r.entities) for r in dataset),
        },
        "approaches": {},
    }

    latencies = {}
    local_approaches = build_local_approaches(users_path)
    for approach, init_seconds, init_scope in local_approaches:
        accuracy = run_accuracy(approach, dataset)
        latency = run_latency(approach, dataset, repeat, warmup)
        latencies[approach.key] = latency
        results["approaches"][approach.key] = {
            "name": approach.name, "status": "MEASURED", "init_seconds": init_seconds,
            "init_scope": init_scope, "latency": latency, **accuracy,
        }

    if comprehend_client is not None:
        client_started = time.perf_counter()
        detector = ComprehendPiiDetector(comprehend_client, language_code=comprehend_language)
        approach = approach_c(detector)
        init_seconds = time.perf_counter() - client_started
        accuracy = run_accuracy(approach, dataset)
        calls_after_accuracy = detector.calls
        latency = run_latency(approach, dataset, repeat=1, warmup=0)
        results["approaches"]["C"] = {
            "name": approach.name, "status": "MEASURED", "init_seconds": init_seconds,
            "init_scope": "detector construction (client created before timing)",
            "comprehend_language_code": comprehend_language,
            "comprehend_calls": detector.calls,
            "comprehend_calls_accuracy_pass": calls_after_accuracy,
            "latency": latency, **accuracy,
        }
    else:
        results["approaches"]["C"] = {
            "name": "C. Existing patterns + Amazon Comprehend",
            "status": "NOT MEASURED",
            "availability": comprehend_status or comprehend_availability(),
        }

    if external_path is not None:
        external = load_binary_dataset(external_path)
        results["external_binary_evaluation"] = {
            "path": str(external_path),
            "texts": len(external),
            "pii_texts": sum(r.contains_pii for r in external),
            "clean_texts": sum(not r.contains_pii for r in external),
            "approaches": run_external([item[0] for item in local_approaches], external),
        }

    results["baseline_equivalence"] = _baseline_equivalence(dataset)
    results["name_index_scaling"] = run_name_index_scaling(dataset, scale_sizes, seed)
    results["cost_estimates"] = estimate_costs(dataset, latencies)
    results["total_benchmark_seconds"] = time.perf_counter() - total_started
    return results


def _fmt(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def summary_table(results: dict) -> str:
    """Markdown summary of document-level results and latency."""
    lines = [
        "| Approach | Caught | Missed | Clean wrongly redacted | TN | Precision | Recall | F1 "
        "| Entity recall | Median us | P95 us |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, data in results["approaches"].items():
        if data["status"] != "MEASURED":
            lines.append(f"| {data['name']} | NOT MEASURED | | | | | | | | | |")
            continue
        doc, ent, lat = data["document"], data["entity"], data["latency"]
        lines.append(
            f"| {data['name']} | {doc['true_positive']} | {doc['false_negative']} | "
            f"{doc['false_positive']} | {doc['true_negative']} | {_fmt(doc['precision'])} | "
            f"{_fmt(doc['recall'])} | {_fmt(doc['f1'])} | {_fmt(ent['recall'])} | "
            f"{lat['median_us']:.1f} | {lat['p95_us']:.1f} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--users", type=Path, default=DEFAULT_USERS)
    parser.add_argument("--repeat", type=int, default=50, help="timed passes over the dataset")
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--scale-sizes", default="1000,10000,100000",
                        help="comma-separated users-table sizes for the lookup scaling test")
    parser.add_argument("--seed", type=int, default=585)
    parser.add_argument("--output", type=Path, help="write full results as JSON")
    parser.add_argument("--external-dataset", type=Path,
                        help="held-out JSONL with id/text/contains_pii, scored at document level")
    parser.add_argument("--comprehend", action="store_true", help="include Approach C (live AWS)")
    parser.add_argument("--allow-billable-aws-calls", action="store_true",
                        help="required with --comprehend; confirms billable calls are approved")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--comprehend-language", default="en", choices=["en", "es"])
    args = parser.parse_args(argv)

    if args.repeat < 1 or args.warmup < 0:
        parser.error("--repeat must be >= 1 and --warmup >= 0")
    if args.comprehend and not args.allow_billable_aws_calls:
        parser.error("--comprehend makes billable AWS calls; add --allow-billable-aws-calls")
    scale_sizes = [int(size) for size in args.scale_sizes.split(",") if size.strip()]

    client, status = None, None
    if args.comprehend:
        status = comprehend_availability()
        if not status["credentials_found"]:
            print(f"Comprehend NOT MEASURED: {status['reason']}", file=sys.stderr)
        else:
            client = create_comprehend_client(args.region)

    results = run(args.dataset, args.users, args.repeat, args.warmup, scale_sizes, args.seed,
                  comprehend_client=client, comprehend_language=args.comprehend_language,
                  comprehend_status=status, external_path=args.external_dataset)
    print(summary_table(results))
    external = results.get("external_binary_evaluation")
    if external:
        print(f"\nHeld-out set ({external['texts']} texts):")
        for data in external["approaches"].values():
            doc = data["document"]
            print(f"- {data['name']}: caught {doc['true_positive']}, missed {doc['false_negative']}, "
                  f"clean wrongly redacted {doc['false_positive']}")
    print(f"\nTotal benchmark time: {results['total_benchmark_seconds']:.2f} s")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")
        print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
