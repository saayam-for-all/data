"""Runs the seven archive verification checks from issue #586 and reports them.

    python -m src.archive_verification.verify

Prints a pass or fail for each check and times the run end to end, which is the
baseline #586 asks for. Exits non-zero if any check fails, so it can be wired
into CI once the real extract exists.

By default it runs against a local SQLite copy of the schema with the reference
extract. Point it at the real pipeline with ``--source postgres`` and
``--extractor module:callable``; the checks themselves do not change.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional, Sequence

from . import checks
from .adapters import (
    Archive,
    LocalDirectoryArchive,
    PostgresSource,
    S3Archive,
    Source,
    resolve_extractor,
)
from .checks import FAIL, PASS, SKIP, CheckResult

STATUS_MARK = {PASS: "PASS", FAIL: "FAIL", SKIP: "SKIP"}


def build_parser() -> argparse.ArgumentParser:
    """Define the command line."""
    parser = argparse.ArgumentParser(
        prog="python -m src.archive_verification.verify",
        description="Verify the request archive matches the source database (#586).",
    )
    parser.add_argument(
        "--extractor",
        default=None,
        metavar="MODULE:CALLABLE",
        help=(
            "the extract to verify, e.g. src.my_lambda:extract. Omit to use the "
            "reference extract, which is a test fixture and not a production "
            "pipeline - see fixture_extract.sql."
        ),
    )
    parser.add_argument(
        "--source",
        choices=("sqlite", "postgres"),
        default="sqlite",
        help=(
            "sqlite (default) builds the local copy of the schema that #586 asks "
            "for. postgres reads the real schema and is the only source that can "
            "answer check 7b."
        ),
    )
    parser.add_argument(
        "--schema",
        default="virginia_dev_saayam_rdbms",
        help="schema qualifying the tables when --source postgres",
    )
    parser.add_argument(
        "--archive-dir",
        default=None,
        metavar="PATH",
        help="directory to write exports to (default: a temporary directory)",
    )
    parser.add_argument(
        "--archive-s3",
        default=None,
        metavar="BUCKET[/PREFIX]",
        help=(
            "write exports to S3 instead. Needs boto3 and credentials, which "
            "CONTRIBUTING.md says contributors do not get."
        ),
    )
    return parser


def _build_archive(arguments: argparse.Namespace, scratch: Path) -> Archive:
    """Choose where exported files go."""
    if arguments.archive_s3:
        bucket, _, prefix = arguments.archive_s3.partition("/")
        return S3Archive(bucket, prefix)
    return LocalDirectoryArchive(Path(arguments.archive_dir) if arguments.archive_dir else scratch)


def _postgres_factory(arguments: argparse.Namespace) -> Optional[Callable[[], Source]]:
    """Return a factory for fresh Postgres connections, for check 7b."""
    if arguments.source != "postgres":
        return None
    return lambda: PostgresSource(arguments.schema)


def run_checks(
    extract,
    archive: Archive,
    source_factory: Optional[Callable[[], Source]] = None,
) -> list[CheckResult]:
    """Run every check in order, timing each one."""
    runners: Sequence[Callable[[], CheckResult]] = (
        lambda: checks.check_row_counts(extract, archive),
        lambda: checks.check_no_duplicates(extract, archive),
        lambda: checks.check_no_gaps(extract, archive),
        lambda: checks.check_joins_resolve(extract, archive),
        lambda: checks.check_broken_references_survive(extract, archive),
        lambda: checks.check_reruns_are_safe(extract, archive),
        lambda: checks.check_timestamps_utc(extract, archive),
        lambda: checks.check_session_time_zone(extract, archive, source_factory),
    )

    results: list[CheckResult] = []
    for runner in runners:
        started = time.perf_counter()
        try:
            result = runner()
        except Exception as error:  # a check that explodes is a failure, not a crash
            result = CheckResult(
                number="?",
                name=runner.__qualname__,
                status=FAIL,
                actual=f"{type(error).__name__}: {error}",
            )
        result.seconds = time.perf_counter() - started
        results.append(result)
    return results


def render(results: Sequence[CheckResult], extractor_label: str, total: float) -> str:
    """Format the results as the printed report."""
    lines = [
        "",
        "Archive verification (#586)",
        f"  extract under test: {extractor_label}",
        "",
    ]
    width = max(len(result.name) for result in results)
    for result in results:
        lines.append(
            f"  [{STATUS_MARK[result.status]}] {result.number:<3} "
            f"{result.name:<{width}}  {result.seconds * 1000:7.1f} ms"
        )
        if result.detail:
            lines.append(f"         {result.detail}")
        if result.status != PASS:
            lines.append(f"         expected: {result.expected}")
            lines.append(f"         actual:   {result.actual}")
        for note in result.notes:
            lines.append(f"         note: {note}")

    passed = sum(1 for result in results if result.status == PASS)
    skipped = sum(1 for result in results if result.status == SKIP)
    failed = sum(1 for result in results if result.status == FAIL)
    lines.extend(
        [
            "",
            f"  {passed} passed, {failed} failed, {skipped} skipped "
            f"of {len(results)} checks",
            f"  total {total:.3f} s",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the checks and print the report. Returns the process exit code."""
    arguments = build_parser().parse_args(argv)
    extract, extractor_label = resolve_extractor(arguments.extractor)

    with tempfile.TemporaryDirectory(prefix="archive-verify-") as scratch:
        archive = _build_archive(arguments, Path(scratch))
        started = time.perf_counter()
        results = run_checks(extract, archive, _postgres_factory(arguments))
        total = time.perf_counter() - started

    print(render(results, extractor_label, total))
    return 1 if any(result.status == FAIL for result in results) else 0


if __name__ == "__main__":
    sys.exit(main())
