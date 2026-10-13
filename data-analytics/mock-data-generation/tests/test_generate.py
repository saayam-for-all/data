"""Regression tests for the Saayam mock-data generator.

Run from the package directory with either:
    python -m unittest discover -s tests
    python -m pytest tests

Tests write only to temporary directories (nothing is committed). They cover
invalid-input rejection, defaults, multiple seeds, zero/single/large datasets,
determinism, every strengthened validation rule, and that the committed CSVs
match a default regeneration.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import copy
from unittest.mock import patch

# Make the package importable when tests run from the tests/ dir.
_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)

import config                     # noqa: E402
import generate_mock_data as gm   # noqa: E402
from utils import ConfigError, ValidationError, set_seed  # noqa: E402

OUTPUT_DIR = os.path.join(_PKG, "output_csv_files")


def build(users=30, orgs=20, seed=42):
    set_seed(seed)
    return gm.build_dataset(users, orgs)


class ConfigValidationTests(unittest.TestCase):
    def _cfg(self, **kw):
        base = dict(users=10, orgs=10, cities_per_state=2,
                    volunteer_ratio=0.4, user_location_ratio=0.5,
                    skills_min=1, skills_max=3)
        base.update(kw)
        return config.validate(**base)

    def test_defaults_ok(self):
        self._cfg()  # no raise

    def test_negative_users_rejected(self):
        with self.assertRaises(ConfigError):
            self._cfg(users=-1)

    def test_negative_orgs_rejected(self):
        with self.assertRaises(ConfigError):
            self._cfg(orgs=-5)

    def test_bad_ratio_rejected(self):
        with self.assertRaises(ConfigError):
            self._cfg(volunteer_ratio=1.5)
        with self.assertRaises(ConfigError):
            self._cfg(user_location_ratio=-0.1)

    def test_negative_cities_rejected(self):
        with self.assertRaises(ConfigError):
            self._cfg(cities_per_state=-1)

    def test_bad_skill_range_rejected(self):
        with self.assertRaises(ConfigError):
            self._cfg(skills_min=5, skills_max=2)
        with self.assertRaises(ConfigError):
            self._cfg(skills_min=-1)

    def test_skills_cannot_exceed_categories(self):
        with self.assertRaises(ConfigError):
            self._cfg(skills_max=1000)

    def test_fractional_or_boolean_counts_rejected(self):
        for value in (1.5, True, "10"):
            with self.subTest(value=value), self.assertRaises(ConfigError):
                self._cfg(users=value)

    def test_nonfinite_ratios_rejected(self):
        for value in (float("nan"), float("inf"), "half", True):
            with self.subTest(value=value), self.assertRaises(ConfigError):
                self._cfg(volunteer_ratio=value)

    def test_invalid_lookup_configuration_rejected(self):
        for values in ([1, 1], [-1], [2**63], ["1"]):
            with self.subTest(values=values), patch.object(config, "LANGUAGE_IDS", values):
                with self.assertRaises(ConfigError):
                    self._cfg()

    def test_direct_build_rejects_negative_count(self):
        with self.assertRaises(ConfigError):
            build(users=-1)

    def test_cli_rejects_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError):
                gm.main(["--users", "-1", "--out", tmp])
            self.assertEqual(os.listdir(tmp), [])


class HappyPathTests(unittest.TestCase):
    def test_defaults_validate(self):
        ds, aux = build(users=config.USERS, orgs=config.ORGANIZATIONS)
        gm.validate(ds, aux)
        self.assertEqual(len(ds), 10)

    def test_multiple_seeds_valid(self):
        for seed in (1, 7, 99, 2026):
            ds, aux = build(seed=seed)
            gm.validate(ds, aux)

    def test_zero_users(self):
        ds, aux = build(users=0, orgs=0)
        gm.validate(ds, aux)
        for t in ("users", "user_skills", "user_locations",
                  "volunteer_details", "volunteer_locations", "organizations"):
            self.assertEqual(len(ds[t][1]), 0, t)
        self.assertGreater(len(ds["countries"][1]), 0)

    def test_single_user(self):
        ds, aux = build(users=1, orgs=1)
        gm.validate(ds, aux)
        self.assertEqual(len(ds["users"][1]), 1)

    def test_larger_dataset(self):
        ds, aux = build(users=800, orgs=300)
        gm.validate(ds, aux)
        self.assertEqual(len(ds["users"][1]), 800)

    def test_determinism_same_seed(self):
        ds1, _ = build(seed=123)
        ds2, _ = build(seed=123)
        for t in ds1:
            self.assertEqual(ds1[t][1], ds2[t][1], f"table {t} not deterministic")

    def test_different_seeds_differ(self):
        ds1, _ = build(seed=1)
        ds2, _ = build(seed=2)
        self.assertNotEqual(ds1["users"][1], ds2["users"][1])

    def test_empty_lookup_sets_emit_null(self):
        with patch.object(config, "LANGUAGE_IDS", []), patch.object(config, "USER_STATUS_IDS", []):
            ds, aux = build()
            gm.validate(ds, aux)
            for row in ds["users"][1]:
                for col in ("language_1", "language_2", "language_3", "user_status_id"):
                    self.assertIsNone(row[col])


class InjectedInvalidDataTests(unittest.TestCase):
    """Build a valid dataset, corrupt one field, expect ValidationError."""

    def setUp(self):
        self.ds, self.aux = build(users=40, orgs=20, seed=5)
        gm.validate(self.ds, self.aux)  # sanity: starts valid

    def _expect_fail(self):
        with self.assertRaises(ValidationError):
            gm.validate(self.ds, self.aux)

    def test_bad_org_type_enum(self):
        self.ds["organizations"][1][0]["org_type"] = "charity"
        self._expect_fail()

    def test_bad_org_size_enum(self):
        self.ds["organizations"][1][0]["org_size"] = "HUGE"
        self._expect_fail()

    def test_rating_out_of_range(self):
        self.ds["organizations"][1][0]["org_rating"] = 9
        self._expect_fail()

    def test_timestamp_order_violation(self):
        r = self.ds["user_skills"][1][0]
        r["created_at"] = "2099-01-01 00:00:00"
        r["last_updated_at"] = "2000-01-01 00:00:00"
        self._expect_fail()

    def test_document_update_after_last_updated(self):
        self.ds["volunteer_details"][1][0]["path1_updated_at"] = "2099-12-31 23:59:59"
        self._expect_fail()

    def test_volunteer_location_predates_details(self):
        self.ds["volunteer_locations"][1][0]["last_updated_at"] = "1999-01-01 00:00:00"
        self._expect_fail()

    def test_orphan_volunteer_location(self):
        row = dict(self.ds["volunteer_locations"][1][0])
        row["user_id"] = "not-a-volunteer"
        self.ds["volunteer_locations"][1].append(row)
        self._expect_fail()

    def test_impossible_date(self):
        self.ds["users"][1][0]["dob"] = "2021-02-30"
        self._expect_fail()

    def test_impossible_timestamp(self):
        self.ds["users"][1][0]["last_updated_at"] = "2021-13-01 00:00:00"
        self._expect_fail()

    def test_coordinate_out_of_bounds(self):
        self.ds["users"][1][0]["last_location"] = "(999.0,999.0)"
        self._expect_fail()

    def test_coordinate_far_from_city(self):
        self.ds["users"][1][0]["last_location"] = "(0.0,0.0)"
        self._expect_fail()

    def test_bad_postal(self):
        self.ds["users"][1][0]["zip_code"] = "00000"
        self._expect_fail()

    def test_tz_mismatch(self):
        self.ds["users"][1][0]["time_zone"] = "Antarctica/Troll"
        self._expect_fail()

    def test_unverified_language_id(self):
        self.ds["users"][1][0]["language_1"] = "999"
        self._expect_fail()

    def test_unverified_status_id(self):
        self.ds["users"][1][0]["user_status_id"] = "42"
        self._expect_fail()

    def test_missing_field(self):
        del self.ds["users"][1][0]["gender"]
        self._expect_fail()

    def test_missing_required_field_empty(self):
        self.ds["users"][1][0]["user_id"] = ""
        self._expect_fail()

    def test_varchar_too_long(self):
        self.ds["organizations"][1][0]["org_name"] = "X" * 200
        self._expect_fail()

    def test_decimal_precision(self):
        self.ds["cities"][1][0]["lattitude"] = "12.1234567"  # 7 fractional digits
        self._expect_fail()

    def test_bad_point_format(self):
        self.ds["users"][1][0]["last_location"] = "not-a-point"
        self._expect_fail()

    def test_duplicate_pk(self):
        self.ds["users"][1].append(dict(self.ds["users"][1][0]))
        self._expect_fail()

    def test_missing_table(self):
        del self.ds["organizations"]
        self._expect_fail()

    def test_unexpected_table(self):
        self.ds["unexpected"] = ([], [])
        self._expect_fail()

    def test_postgres_integer_overflow(self):
        for value in (2**31, -(2**31)-1, 2**80):
            with self.subTest(value=value):
                self.ds["cities"][1][0]["city_id"] = value
                self._expect_fail()

    def test_bigint_overflow(self):
        self.ds["users"][1][0]["language_1"] = 2**63
        self._expect_fail()

    def test_all_remaining_varchar_limits(self):
        for table, columns in {
            "users": ["addr_ln1", "addr_ln2", "addr_ln3", "profile_picture_path", "time_zone"],
            "organizations": ["street"],
        }.items():
            for col in columns:
                with self.subTest(table=table, column=col):
                    ds = copy.deepcopy(self.ds)
                    ds[table][1][0][col] = "X" * 256
                    with self.assertRaises(ValidationError):
                        gm.validate(ds, self.aux)

    def test_city_coordinate_bounds(self):
        for col, value in (("lattitude", 99), ("lattitude", -99),
                           ("longitude", 999), ("longitude", -999)):
            with self.subTest(column=col, value=value):
                ds = copy.deepcopy(self.ds)
                ds["cities"][1][0][col] = value
                with self.assertRaises(ValidationError):
                    gm.validate(ds, self.aux)

    def test_city_coordinate_must_match_reference(self):
        self.ds["cities"][1][0]["lattitude"] = 0
        self._expect_fail()

    def test_postgres_jsonb_restrictions(self):
        for value in ('[NaN]', '[Infinity]', '[-Infinity]', '[1e999999]',
                      '["\\u0000"]', '["\\ud800"]'):
            with self.subTest(value=value):
                self.ds["volunteer_details"][1][0]["availability_days"] = value
                self._expect_fail()

    def test_nul_text_rejected(self):
        self.ds["users"][1][0]["addr_ln1"] = "test\x00address"
        self._expect_fail()

    def test_organization_sql_checks(self):
        for col, value in (("web_url", "ftp://example.org"), ("email", "missing-at")):
            with self.subTest(column=col):
                ds = copy.deepcopy(self.ds)
                ds["organizations"][1][0][col] = value
                with self.assertRaises(ValidationError):
                    gm.validate(ds, self.aux)


class CommittedCsvTests(unittest.TestCase):
    def test_committed_matches_regeneration(self):
        if not os.path.isdir(OUTPUT_DIR):
            self.skipTest("output_csv_files not present")
        with tempfile.TemporaryDirectory() as tmp:
            rc = gm.main(["--out", tmp])
            self.assertEqual(rc, 0)
            committed = sorted(f for f in os.listdir(OUTPUT_DIR) if f.endswith(".csv"))
            regenerated = sorted(f for f in os.listdir(tmp) if f.endswith(".csv"))
            self.assertEqual(committed, regenerated)
            for name in committed:
                with open(os.path.join(OUTPUT_DIR, name), "rb") as a, \
                        open(os.path.join(tmp, name), "rb") as b:
                    self.assertEqual(a.read(), b.read(),
                                     f"{name} differs from default regeneration")


if __name__ == "__main__":
    unittest.main(verbosity=2)
