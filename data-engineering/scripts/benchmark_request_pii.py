"""Benchmark PII detectors against the synthetic issue #585 test set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

from src.utils.pii_benchmark import (
    LabeledText,
    Metrics,
    detect_with_comprehend,
    detect_with_patterns,
    detect_with_patterns_and_users,
    evaluate,
    estimate_monthly_comprehend_cost,
    make_user_name_detector,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLES_PATH = (
    PROJECT_ROOT / "tests" / "fixtures" / "pii_request_descriptions.jsonl"
)
USERS_PATH = PROJECT_ROOT / "src" / "utils" / "pii_benchmark_users.json"
REPORT_PATH = PROJECT_ROOT / "docs" / "pii_approach_comparison.md"


def load_samples() -> list[LabeledText]:
    """Load the labeled synthetic request descriptions."""
    samples = []
    with SAMPLES_PATH.open(encoding="utf-8") as source:
        for line in source:
            item = json.loads(line)
            samples.append(LabeledText(
                sample_id=item["id"],
                text=item["text"],
                contains_pii=item["contains_pii"],
            ))
    return samples


def load_user_names() -> list[str]:
    """Load synthetic user-table names for the lookup approach."""
    with USERS_PATH.open(encoding="utf-8") as source:
        return json.load(source)


def make_comprehend_detector(region: str) -> Callable[[str], bool]:
    """Create the optional live Amazon Comprehend detector."""
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError(
            "Live Comprehend evaluation needs boto3; install it with "
            "`python -m pip install boto3` before retrying."
        ) from exc

    client = boto3.client("comprehend", region_name=region)

    def detect(text: str) -> bool:
        return detect_with_comprehend(text, client)

    return detect


def format_metrics(name: str, metrics: Metrics) -> str:
    """Format one benchmark result as a Markdown table row."""
    return (
        f"| {name} | {metrics.caught} | {metrics.missed} | "
        f"{metrics.false_positives} | {metrics.true_negative} | "
        f"{metrics.elapsed_seconds:.6f} | "
        f"{metrics.samples_per_second:.1f} |"
    )


def render_report(
    samples: list[LabeledText],
    results: dict[str, Metrics],
    comprehend_status: str,
) -> str:
    """Render measured results, cost scenarios, and implementation caveats."""
    pii_count = sum(sample.contains_pii for sample in samples)
    clean_count = len(samples) - pii_count
    average_chars = sum(len(sample.text) for sample in samples) / len(samples)
    # Current archive request volume is not published in the repository.
    illustrative_volume = 10_000
    estimated_cost = estimate_monthly_comprehend_cost(
        (len(sample.text) for sample in samples),
        illustrative_volume,
    )

    rows = [
        "| Approach | Caught | Missed | False positives | Clean correct | "
        "Elapsed seconds | Samples/second |",
        "|---|---:|---:|---:|---:|---:|---:|",
        format_metrics(
            "Patterns only (email, phone, card, SSN)",
            results["patterns"],
        ),
        format_metrics(
            "Patterns + mock users lookup",
            results["patterns_and_users"],
        ),
    ]
    if "comprehend" in results:
        rows.append(
            format_metrics("Amazon Comprehend PII API", results["comprehend"])
        )
        comprehend_summary = (
            "Comprehend was called live; the timing and metrics above include "
            "network/API latency."
        )
    else:
        rows.append(
            "| Amazon Comprehend PII API | Not measured | Not measured | "
            "Not measured | Not measured | Not measured | Not measured |"
        )
        comprehend_summary = comprehend_status

    return f"""# Request description PII approach evaluation (#585)

## Test method

The same {len(samples)} synthetic request descriptions were evaluated by each
available detector: {pii_count} contain labeled personal data and
{clean_count} are clean. The test corpus is checked into
`tests/fixtures/pii_request_descriptions.jsonl`; it includes English and
non-English names, addresses, email, multiple phone formats, digit-only and
spelled-out phone numbers, card/ID patterns, dates, and benign numeric text.
All names, addresses, contacts, and identifiers are fictional. This is a
sample-level measurement: a sample counts as caught if the method flags it
and as missed if it does not. A clean sample flagged by a method is a false
positive. Processing time is measured locally over one pass and excludes
process startup; live Comprehend timing includes each network call.

## Results

{chr(10).join(rows)}

### Comprehend access status

{comprehend_summary}

No AWS credentials/IAM permission were available in this environment, so no
Comprehend accuracy or latency result is fabricated. Re-run with
`python -m scripts.benchmark_request_pii --comprehend --region us-east-1`
from `data-engineering/` after granting `comprehend:DetectPiiEntities`.

## Recommendation

Use pattern matching as the inexpensive first pass and add Amazon Comprehend
for names and address-like PII only after a live evaluation confirms its
recall and false-positive rate on the maintainer-provided corpus. The local
user-name lookup only recognizes names already in the users table: it misses
other names, may reveal user-table names in matching logic, and does not
identify addresses. Pattern matching alone cannot find names or addresses.
Do not treat this synthetic benchmark as proof of production quality.
Presidio is excluded per the task's Lambda package-size constraint; confirm
its deployed dependency footprint before reconsidering it.

## Cost estimate

The repository does not publish current monthly request volume, so a factual
current-volume total cannot be calculated. AWS pricing examples bill text
analysis by 100-character units; at the published $0.0001/unit example rate,
this corpus averages {average_chars:.1f} characters per description. An
illustrative {illustrative_volume:,} descriptions/month at this corpus's
per-request rounded average costs approximately **${estimated_cost:.2f}/month**
before free-tier eligibility, taxes, and regional price differences. Replace
the volume assumption with actual archived request counts; the included
benchmark computes this using each request's rounded-up 100-character units.
This estimate does not include S3, Lambda, data transfer, or retries.

Source: [Amazon Comprehend pricing](https://aws.amazon.com/comprehend/pricing/)
(checked 2026-11-03).
"""


def run(
    include_comprehend: bool = False,
    region: str = "us-east-1",
    comprehend_detector: Callable[[str], bool] | None = None,
) -> str:
    """Run available methods and write the Markdown comparison report."""
    samples = load_samples()
    names = load_user_names()
    name_detector = make_user_name_detector(names)

    detectors: dict[str, Callable[[str], bool]] = {
        "patterns": detect_with_patterns,
        "patterns_and_users": lambda text: detect_with_patterns_and_users(
            text,
            name_detector,
        ),
    }

    status = (
        "Not run. Live PII detection requires AWS Comprehend permission, "
        "which was not available during this local-only evaluation."
    )
    if include_comprehend:
        detector = comprehend_detector or make_comprehend_detector(region)
        detectors["comprehend"] = detector
        status = ""

    results = {
        name: evaluate(samples, detector)
        for name, detector in detectors.items()
    }
    report = render_report(samples, results, status)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    return report


def main() -> None:
    """Run benchmark CLI and print a concise summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--comprehend",
        action="store_true",
        help="Call Amazon Comprehend using configured AWS credentials.",
    )
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    report = run(include_comprehend=args.comprehend, region=args.region)
    print(f"Wrote {REPORT_PATH}")
    for line in report.splitlines():
        if line.startswith("| Patterns ") or line.startswith(
            "| Amazon Comprehend"
        ):
            print(line)


if __name__ == "__main__":
    main()
