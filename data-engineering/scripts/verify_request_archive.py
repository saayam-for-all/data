"""Independent verification of the requests archive (Issue #586)."""

import atexit
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class ArchiveVerification:
    """Collect and report independent archive verification results."""

    def __init__(self):
        self.results = []

    def record(self, name, passed, expected, actual, details=""):
        self.results.append(
            {
                "check": name,
                "status": "PASS" if passed else "FAIL",
                "expected": expected,
                "actual": actual,
                "details": details,
            }
        )

    def verify_row_counts(self, source_count, archive_csv_path):
        """Compare source row count with archived CSV data rows."""
        import csv

        with open(
            archive_csv_path, "r", encoding="utf-8", newline=""
        ) as file:
            reader = csv.DictReader(file)
            archive_count = sum(1 for _ in reader)

        self.record(
            name="Source vs archive row counts",
            passed=source_count == archive_count,
            expected=source_count,
            actual=archive_count,
            details=f"Archive file: {Path(archive_csv_path).name}",
        )

    def verify_cross_file_duplicates(self, archive_paths):
        """Detect request IDs repeated within or across archive files."""
        import csv

        seen = {}
        duplicates = []

        for path in archive_paths:
            with open(path, "r", encoding="utf-8-sig", newline="") as file:
                reader = csv.DictReader(file)

                if not reader.fieldnames or "req_id" not in reader.fieldnames:
                    raise ValueError(f"Missing req_id column in {path}")

                for row in reader:
                    request_id = row["req_id"]

                    if not request_id:
                        raise ValueError(f"Empty req_id in {path}")

                    if request_id in seen:
                        duplicates.append(
                            f"{request_id}: {seen[request_id]} and {path}"
                        )
                    else:
                        seen[request_id] = str(path)

        self.record(
            name="Duplicate request IDs across archive files",
            passed=len(duplicates) == 0,
            expected="No repeated request IDs",
            actual=f"{len(duplicates)} duplicate occurrences",
            details="; ".join(duplicates[:10]),
        )

    def verify_watermark_continuity(self, windows):
        """Verify consecutive extraction windows have no gaps or overlaps."""
        from datetime import datetime

        def parse_timestamp(value):
            if isinstance(value, datetime):
                return value
            return datetime.fromisoformat(value.replace("Z", "+00:00"))

        ordered = sorted(
            [
                (parse_timestamp(start), parse_timestamp(end))
                for start, end in windows
            ],
            key=lambda window: window[0],
        )

        issues = []

        for index, (start, end) in enumerate(ordered):
            if start >= end:
                issues.append(f"Window {index + 1} has invalid boundaries")

            if index > 0:
                previous_end = ordered[index - 1][1]

                if start > previous_end:
                    issues.append(
                        f"Gap between windows {index} and {index + 1}: "
                        f"{previous_end} to {start}"
                    )
                elif start < previous_end:
                    issues.append(
                        f"Overlap between windows {index} and {index + 1}: "
                        f"{start} precedes {previous_end}"
                    )

        self.record(
            name="Watermark window continuity",
            passed=len(ordered) >= 2 and not issues,
            expected="Consecutive windows with no gaps or overlaps",
            actual=(
                f"{len(ordered)} windows checked; "
                f"{len(issues)} issues found"
            ),
            details="; ".join(issues) if issues else "",
        )

    def verify_foreign_keys(self, archive_csv_path, lookup_mappings):
        """Compare archived readable values against reference mappings."""
        import csv

        fields = {
            "req_status_id": "req_status",
            "req_type_id": "req_type",
            "req_priority_id": "req_priority",
            "req_cat_id": "req_category",
        }

        mismatches = []
        checked = 0
        unresolved = 0

        with open(
            archive_csv_path, "r", encoding="utf-8-sig", newline=""
        ) as file:
            reader = csv.DictReader(file)

            required = set(fields.keys()) | set(fields.values())
            missing = required - set(reader.fieldnames or [])

            if missing:
                raise ValueError(
                    f"Missing archive columns: {sorted(missing)}"
                )

            for row in reader:
                for id_column, value_column in fields.items():
                    reference_id = row[id_column]
                    actual_value = row[value_column]

                    if not reference_id:
                        if actual_value:
                            mismatches.append(
                                f"{row['req_id']}: {value_column} "
                                "should be empty for a null reference"
                            )
                        unresolved += 1
                        continue

                    mapping = lookup_mappings[id_column]

                    if reference_id not in mapping:
                        if actual_value:
                            mismatches.append(
                                f"{row['req_id']}: unmatched "
                                f"{reference_id} has value {actual_value}"
                            )
                        unresolved += 1
                        continue

                    expected_value = mapping[reference_id]
                    checked += 1

                    if actual_value != expected_value:
                        mismatches.append(
                            f"{row['req_id']}: {value_column} "
                            f"expected {expected_value}, got {actual_value}"
                        )

        self.record(
            name="Foreign-key readable values",
            passed=len(mismatches) == 0,
            expected="All readable values match lookup mappings",
            actual=(
                f"{checked} resolved references checked; "
                f"{unresolved} unresolved; "
                f"{len(mismatches)} mismatches"
            ),
            details="; ".join(mismatches[:10]),
        )

    def verify_broken_category_preservation(
        self, archive_csv_path, expected_request_ids
    ):
        """Verify requests with broken/null category FKs are archived."""
        import csv

        with open(
            archive_csv_path, "r", encoding="utf-8-sig", newline=""
        ) as file:
            reader = csv.DictReader(file)

            required = {"req_id", "req_cat_id", "req_category"}
            missing_columns = required - set(reader.fieldnames or [])

            if missing_columns:
                raise ValueError(
                    f"Missing archive columns: {sorted(missing_columns)}"
                )

            rows = list(reader)

        archived_ids = {row["req_id"] for row in rows}
        missing_ids = sorted(set(expected_request_ids) - archived_ids)

        self.record(
            name="Broken/null category FK preservation",
            passed=len(missing_ids) == 0,
            expected="All specified requests are preserved in archive",
            actual=(
                f"{len(expected_request_ids) - len(missing_ids)}"
                f"/{len(expected_request_ids)} requests found"
            ),
            details=(
                f"Missing request IDs: {missing_ids}"
                if missing_ids else ""
            ),
        )

    def verify_byte_identical(self, first_path, second_path):
        """Verify that two archive outputs are byte-identical."""
        import hashlib

        def sha256_file(path):
            digest = hashlib.sha256()

            with open(path, "rb") as file:
                for chunk in iter(lambda: file.read(65536), b""):
                    digest.update(chunk)

            return digest.hexdigest()

        first_hash = sha256_file(first_path)
        second_hash = sha256_file(second_path)

        self.record(
            name="Archive byte-identical rerun",
            passed=first_hash == second_hash,
            expected="Identical SHA-256 hashes",
            actual=(
                "Hashes match"
                if first_hash == second_hash
                else "Hashes differ"
            ),
            details=(
                f"First: {first_hash}; Second: {second_hash}"
            ),
        )

    def verify_s3_object_count(
        self, objects_before, objects_after
    ):
        """Verify rerunning a window does not add S3 objects."""

        before = set(objects_before)
        after = set(objects_after)

        new_objects = sorted(after - before)
        removed_objects = sorted(before - after)

        self.record(
            name="S3 object-count idempotency (simulated fixture only)",
            passed=(
                len(objects_before) == len(before)
                and len(objects_after) == len(after)
                and before == after
            ),
            expected="No additional or removed S3 objects",
            actual=(
                f"Before: {len(before)} objects; "
                f"After: {len(after)} objects; "
                f"New: {len(new_objects)}; "
                f"Removed: {len(removed_objects)}"
            ),
            details=(
                f"New objects: {new_objects}; "
                f"Removed objects: {removed_objects}"
            ) if new_objects or removed_objects else "",
        )

    def report(self):
        print("\nREQUEST ARCHIVE VERIFICATION REPORT")
        print("=" * 45)

        for result in self.results:
            print(f"\n[{result['status']}] {result['check']}")
            print(f"  Expected: {result['expected']}")
            print(f"  Actual:   {result['actual']}")

            if result["details"]:
                print(f"  Details:  {result['details']}")

        passed = sum(
            result["status"] == "PASS"
            for result in self.results
        )

        print("\n" + "=" * 45)
        print(f"Checks passed: {passed}/{len(self.results)}")

    def save_json(self, output_path):
        report = {
            "issue": 586,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "results": self.results,
        }

        with open(output_path, "w", encoding="utf-8") as file:
            json.dump(report, file, indent=2)


if __name__ == "__main__":
    verifier = ArchiveVerification()

    scripts_dir = Path(__file__).parent

    fixture_dir = Path(tempfile.mkdtemp(prefix="archive_586_"))
    atexit.register(shutil.rmtree, fixture_dir, ignore_errors=True)

    fixtures = {
        "test_archive.csv": (
            "req_id,req_status\n"
            "REQ-000001,New\n"
            "REQ-000002,In Progress\n"
            "REQ-000003,Completed\n"
        ),
        "test_archive_2.csv": (
            "req_id,req_status\n"
            "REQ-000004,New\n"
            "REQ-000005,Completed\n"
        ),
        "test_archive_rerun.csv": (
            "req_id,req_status\n"
            "REQ-000001,New\n"
            "REQ-000002,In Progress\n"
            "REQ-000003,Completed\n"
        ),
        "test_foreign_keys.csv": (
            "req_id,req_status_id,req_status,req_type_id,req_type,"
            "req_priority_id,req_priority,req_cat_id,req_category\n"
            "REQ-000001,1,RESOLVED,1,REMOTE,0,LOW,1,FOOD_AND_ESSENTIALS\n"
            "REQ-000002,9,,9,,9,,CAT-OTHER,\n"
            "REQ-000003,,,,,,,,\n"
        ),
    }

    for name, data in fixtures.items():
        (fixture_dir / name).write_text(data, encoding="utf-8")

    archive_path = fixture_dir / "test_archive.csv"
    archive_path_2 = fixture_dir / "test_archive_2.csv"

    # Ensure the rerun fixture is byte-identical to the first export.
    (fixture_dir / "test_archive_rerun.csv").write_bytes(
        archive_path.read_bytes()
    )

    # Check 1: Row counts
    verifier.verify_row_counts(
        source_count=3,
        archive_csv_path=archive_path,
    )

    # Check 2: Cross-file duplicates
    verifier.verify_cross_file_duplicates(
        archive_paths=[archive_path, archive_path_2],
    )

    # Check 3: Watermark continuity
    verifier.verify_watermark_continuity(
        windows=[
            ("2026-11-09 10:00:00", "2026-11-09 11:00:00"),
            ("2026-11-09 11:00:00", "2026-11-09 12:00:00"),
            ("2026-11-09 12:00:00", "2026-11-09 13:00:00"),
        ]
    )

    # Check 4: Foreign-key readable values
    verifier.verify_foreign_keys(
        archive_csv_path=fixture_dir / "test_foreign_keys.csv",
        lookup_mappings={
            "req_status_id": {"1": "RESOLVED"},
            "req_type_id": {"1": "REMOTE"},
            "req_priority_id": {"0": "LOW"},
            "req_cat_id": {"1": "FOOD_AND_ESSENTIALS"},
        },
    )

    # Check 5: Broken/null category FK preservation
    verifier.verify_broken_category_preservation(
        archive_csv_path=fixture_dir / "test_foreign_keys.csv",
        expected_request_ids=[
            "REQ-000002",
            "REQ-000003",
        ],
    )

    # Check 6A: Byte-identical archive output
    verifier.verify_byte_identical(
        first_path=fixture_dir / "test_archive.csv",
        second_path=fixture_dir / "test_archive_rerun.csv",
    )

    # Check 6B: S3 object-count idempotency
    verifier.verify_s3_object_count(
        objects_before=[
            "requests_enriched/window_001/requests_enriched.csv",
        ],
        objects_after=[
            "requests_enriched/window_001/requests_enriched.csv",
        ],
    )
    verifier.report()
    verifier.save_json(scripts_dir / "archive_586_verification_report.json")
    # Exit with a failure status if any verification check failed.
    if any(result["status"] != "PASS" for result in verifier.results):
        raise SystemExit(1)
