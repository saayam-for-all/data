"""Regression tests for invalid data that previously passed validation."""

import contextlib
import csv
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path

from geography import SEEDED_CITIES
from schema import BASE, DEFAULT_LOOKUP, EXPECTED_HEADERS
from validate_mock_data import validate_dataset


class MockDataTests(unittest.TestCase):
    """Exercise complete generation runs and independently corrupted fixtures."""

    def setUp(self) -> None:
        """Generate an isolated baseline so each test can safely mutate files."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        result = self.generate(100)
        self.assertEqual(result.returncode, 0, result.stderr)

    def generate(self, count: int, *args: str) -> subprocess.CompletedProcess[str]:
        """Run the generator from an unrelated working directory."""
        return subprocess.run(
            [
                sys.executable,
                str(BASE / "generate_mock_data.py"),
                "--count",
                str(count),
                "--output-dir",
                str(self.output),
                *args,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=self.output,
        )

    def valid(self) -> bool:
        """Validate the test dataset while keeping expected errors quiet."""
        with contextlib.redirect_stdout(io.StringIO()):
            return validate_dataset(self.output)

    def mutate(self, filename: str, edit: Callable[[list[dict]], object]) -> None:
        """Apply a deliberate row mutation and rewrite a single CSV."""
        path = self.output / filename
        with path.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        edit(rows)
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=EXPECTED_HEADERS[filename])
            writer.writeheader()
            writer.writerows(rows)

    def test_counts_and_determinism(self) -> None:
        """Verify configured sizes, valid output, and byte-for-byte reproducibility."""
        for count in (1, 400, 1000):
            with self.subTest(count=count):
                self.assertEqual(self.generate(count).returncode, 0)
                self.assertTrue(self.valid())
                expected_counts = {
                    "users.csv": count,
                    "organizations.csv": count,
                    "user_skills.csv": count,
                    "cities.csv": min(count, len(SEEDED_CITIES)),
                    "volunteer_details.csv": max(1, int(count * 0.6)),
                    "volunteer_locations.csv": max(1, int(count * 0.6)),
                    "user_locations.csv": max(1, int(count * 0.8)),
                }
                for filename, expected in expected_counts.items():
                    with (self.output / filename).open(
                        encoding="utf-8", newline=""
                    ) as f:
                        self.assertEqual(sum(1 for _ in csv.DictReader(f)), expected)
        before = {p.name: p.read_bytes() for p in self.output.glob("*.csv")}
        self.assertEqual(self.generate(1000).returncode, 0)
        self.assertEqual(
            before, {p.name: p.read_bytes() for p in self.output.glob("*.csv")}
        )

    def test_rejects_bad_cli_arguments(self) -> None:
        """Reject nonpositive counts and missing reference directories."""
        for count in (0, -1):
            self.assertNotEqual(self.generate(count).returncode, 0)
        self.assertNotEqual(
            self.generate(1, "--lookup-dir", str(self.output / "missing")).returncode, 0
        )

    def test_rejects_duplicate_location_keys(self) -> None:
        """Reject duplicate user IDs in both location tables."""
        for file in ("user_locations.csv", "volunteer_locations.csv"):
            with self.subTest(file=file):
                original = (self.output / file).read_bytes()
                self.mutate(file, lambda rows: rows.append(rows[0].copy()))
                self.assertFalse(self.valid())
                (self.output / file).write_bytes(original)

    def test_rejects_invalid_values(self) -> None:
        """Reject schema, temporal, contact, and relational corruption."""
        cases = [
            ("users.csv", "dob", "not-a-date"),
            ("users.csv", "last_updated_at", "not-a-date"),
            ("users.csv", "promotion_wizard_last_updated_at", "2099-01-01 00:00:00"),
            ("users.csv", "language_1", "999999"),
            ("users.csv", "user_status_id", "999999"),
            ("users.csv", "country_id", "-99"),
            ("users.csv", "primary_email_address", "user@ordinary-domain.org"),
            ("users.csv", "primary_phone_number", "+12345678901"),
            ("users.csv", "time_zone", "wrong"),
            ("users.csv", "last_location", "(0, 0)"),
            ("organizations.csv", "org_name", ""),
            ("organizations.csv", "org_name", "x" * 126),
            ("organizations.csv", "org_id", "ORG-00-000001"),
            ("organizations.csv", "org_rating", "6"),
            ("organizations.csv", "org_rating", "NaN"),
            ("organizations.csv", "org_type", "invalid"),
            ("organizations.csv", "zip_code", "bad"),
            ("organizations.csv", "is_contributor", "invalid"),
            ("volunteer_details.csv", "availability_days", "{broken"),
            ("volunteer_details.csv", "path1_updated_at", "not-a-date"),
            ("volunteer_details.csv", "created_at", "2099-01-01 00:00:00"),
            ("states.csv", "country_id", ""),
            ("states.csv", "country_id", "not-a-number"),
            ("cities.csv", "lattitude", "NaN"),
            ("cities.csv", "longitude", "0"),
            ("user_locations.csv", "curr_loc", "POINT(0 0)"),
            ("volunteer_locations.csv", "user_id", "SID-00-999-999-999-999-999"),
            ("user_skills.csv", "cat_id", "nonexistent"),
        ]
        for filename, key, value in cases:
            with self.subTest(file=filename, key=key):
                original = (self.output / filename).read_bytes()
                self.mutate(filename, lambda rows: rows[0].update({key: value}))
                self.assertFalse(self.valid())
                (self.output / filename).write_bytes(original)

    def test_rejects_numeric_duplicate_keys(self) -> None:
        """Treat differently padded integer IDs as the same SQL key."""
        self.mutate(
            "countries.csv",
            lambda rows: rows.append(
                dict(rows[0], country_id="0" + rows[0]["country_id"])
            ),
        )
        self.assertFalse(self.valid())

    def test_invalid_lookup_preserves_output(self) -> None:
        """Leave the existing dataset intact when source validation fails."""

        lookups = self.output / "lookups"
        shutil.copytree(DEFAULT_LOOKUP, lookups)
        (lookups / "help_categories.csv").write_text("cat_id,cat_name,cat_desc\n")
        before = {p.name: p.read_bytes() for p in self.output.glob("*.csv")}
        self.assertNotEqual(
            self.generate(100, "--lookup-dir", str(lookups)).returncode, 0
        )
        self.assertEqual(
            before, {p.name: p.read_bytes() for p in self.output.glob("*.csv")}
        )

    def test_rejects_duplicate_city_lookup(self) -> None:
        """Reject repeated state/city pairs even when their primary keys differ."""
        self.mutate(
            "cities.csv", lambda rows: rows.append(dict(rows[0], city_id="99999"))
        )
        self.assertFalse(self.valid())

    def test_configurable_subsets(self) -> None:
        """Exercise empty, partial, and complete subsets with valid references."""
        for fraction in (0, 0.25, 1):
            with self.subTest(fraction=fraction):
                result = self.generate(
                    100,
                    "--volunteer-fraction",
                    str(fraction),
                    "--user-location-fraction",
                    str(fraction),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(self.valid())
                for filename in (
                    "volunteer_details.csv",
                    "volunteer_locations.csv",
                    "user_locations.csv",
                ):
                    with (self.output / filename).open(
                        encoding="utf-8", newline=""
                    ) as file:
                        self.assertEqual(
                            sum(1 for _ in csv.DictReader(file)), int(100 * fraction)
                        )

    def test_location_requires_volunteer_record(self) -> None:
        """Reject a location for a real user who has no volunteer profile."""
        with (self.output / "users.csv").open(encoding="utf-8", newline="") as file:
            users = {row["user_id"] for row in csv.DictReader(file)}
        with (self.output / "volunteer_details.csv").open(
            encoding="utf-8", newline=""
        ) as file:
            volunteers = {row["user_id"] for row in csv.DictReader(file)}
        nonvolunteer = sorted(users - volunteers)[0]
        self.mutate(
            "volunteer_locations.csv",
            lambda rows: rows[0].update(user_id=nonvolunteer),
        )
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertFalse(validate_dataset(self.output))
        self.assertIn("orphan user_id", output.getvalue())

    def test_rejects_invalid_fractions(self) -> None:
        """Reject out-of-range and nonfinite subset fractions at the CLI."""
        for option in ("--volunteer-fraction", "--user-location-fraction"):
            for value in ("-0.1", "1.1", "nan", "inf"):
                with self.subTest(option=option, value=value):
                    self.assertNotEqual(self.generate(100, option, value).returncode, 0)

    def test_rejects_truncated_csv(self) -> None:
        """Report short CSV rows instead of crashing or accepting them."""
        with (self.output / "users.csv").open("a", encoding="utf-8") as f:
            f.write("too,few,columns\n")
        self.assertFalse(self.valid())


if __name__ == "__main__":
    unittest.main()
