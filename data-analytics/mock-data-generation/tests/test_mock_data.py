from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_DIR),
    )


from config import GeneratorConfig
from generators import generate_all
from schema import (
    ORGANIZATION_SIZES,
    ORGANIZATION_TYPES,
    SKILL_LEVELS,
    TABLE_COLUMNS,
)
from utils import (
    generate_org_id,
    generate_user_id,
    parse_geography_point,
    parse_timestamp,
)
from validation import (
    ValidationError,
    validate_all,
)


class MockDataGenerationTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.config = GeneratorConfig(
            seed=42,
            users=100,
            organizations=100,
            cities_per_state=5,
            volunteer_ratio=0.50,
            user_location_ratio=0.75,
            volunteer_location_ratio=1.00,
            skills_per_user_min=1,
            skills_per_user_max=3,
        )

        cls.data = generate_all(
            cls.config
        )

    def test_all_required_tables_generated(self):
        self.assertEqual(
            set(self.data.keys()),
            set(TABLE_COLUMNS.keys()),
        )

    def test_complete_validation_passes(self):
        validate_all(self.data)

    def test_user_count(self):
        self.assertEqual(
            len(self.data["users"]),
            100,
        )

    def test_organization_count(self):
        self.assertEqual(
            len(self.data["organizations"]),
            100,
        )

    def test_city_count(self):
        self.assertEqual(
            len(self.data["cities"]),
            50,
        )

    def test_volunteer_count(self):
        self.assertEqual(
            len(self.data["volunteer_details"]),
            50,
        )

    def test_user_location_count(self):
        self.assertEqual(
            len(self.data["user_locations"]),
            75,
        )

    def test_volunteer_locations_reference_only_volunteers(self):
        volunteer_ids = {
            row["user_id"]
            for row in self.data["volunteer_details"]
        }

        for row in self.data["volunteer_locations"]:
            self.assertIn(
                row["user_id"],
                volunteer_ids,
            )

    def test_user_locations_reference_users(self):
        user_ids = {
            row["user_id"]
            for row in self.data["users"]
        }

        for row in self.data["user_locations"]:
            self.assertIn(
                row["user_id"],
                user_ids,
            )

    def test_users_reference_valid_states(self):
        state_ids = {
            row["state_id"]
            for row in self.data["states"]
        }

        for row in self.data["users"]:
            self.assertIn(
                row["state_id"],
                state_ids,
            )

    def test_users_reference_valid_countries(self):
        country_ids = {
            row["country_id"]
            for row in self.data["countries"]
        }

        for row in self.data["users"]:
            self.assertIn(
                row["country_id"],
                country_ids,
            )

    def test_states_reference_valid_countries(self):
        country_ids = {
            row["country_id"]
            for row in self.data["countries"]
        }

        for row in self.data["states"]:
            self.assertIn(
                row["country_id"],
                country_ids,
            )

    def test_cities_reference_valid_states(self):
        state_ids = {
            row["state_id"]
            for row in self.data["states"]
        }

        for row in self.data["cities"]:
            self.assertIn(
                row["state_id"],
                state_ids,
            )

    def test_organizations_reference_valid_states(self):
        state_ids = {
            row["state_id"]
            for row in self.data["states"]
        }

        for row in self.data["organizations"]:
            self.assertIn(
                row["state_id"],
                state_ids,
            )

    def test_volunteer_details_reference_users(self):
        user_ids = {
            row["user_id"]
            for row in self.data["users"]
        }

        for row in self.data["volunteer_details"]:
            self.assertIn(
                row["user_id"],
                user_ids,
            )

    def test_user_skills_reference_users(self):
        user_ids = {
            row["user_id"]
            for row in self.data["users"]
        }

        for row in self.data["user_skills"]:
            self.assertIn(
                row["user_id"],
                user_ids,
            )

    def test_user_skills_reference_categories(self):
        category_ids = {
            row["cat_id"]
            for row in self.data["help_categories"]
        }

        for row in self.data["user_skills"]:
            self.assertIn(
                row["cat_id"],
                category_ids,
            )

    def test_user_ids_unique(self):
        user_ids = [
            row["user_id"]
            for row in self.data["users"]
        ]

        self.assertEqual(
            len(user_ids),
            len(set(user_ids)),
        )

    def test_organization_ids_unique(self):
        org_ids = [
            row["org_id"]
            for row in self.data["organizations"]
        ]

        self.assertEqual(
            len(org_ids),
            len(set(org_ids)),
        )

    def test_user_skills_composite_key_unique(self):
        keys = [
            (
                row["user_id"],
                row["cat_id"],
            )
            for row in self.data["user_skills"]
        ]

        self.assertEqual(
            len(keys),
            len(set(keys)),
        )

    def test_current_sid_format(self):
        self.assertEqual(
            generate_user_id(1),
            "SID-00-000-000-000-000-001",
        )

        self.assertEqual(
            generate_user_id(123456),
            "SID-00-000-000-000-123-456",
        )

    def test_current_org_id_format(self):
        self.assertEqual(
            generate_org_id(1),
            "ORG-000-000-000-0001",
        )

        self.assertEqual(
            generate_org_id(123456),
            "ORG-000-000-012-3456",
        )

    def test_city_schema_uses_lattitude(self):
        self.assertIn(
            "lattitude",
            TABLE_COLUMNS["cities"],
        )

        self.assertNotIn(
            "latitude",
            TABLE_COLUMNS["cities"],
        )

    def test_skill_levels(self):
        for row in self.data["user_skills"]:
            self.assertIn(
                row["skill_level"],
                SKILL_LEVELS,
            )

    def test_organization_types(self):
        for row in self.data["organizations"]:
            self.assertIn(
                row["org_type"],
                ORGANIZATION_TYPES,
            )

    def test_organization_sizes(self):
        for row in self.data["organizations"]:
            self.assertIn(
                row["org_size"],
                ORGANIZATION_SIZES,
            )

    def test_organization_rating_range(self):
        for row in self.data["organizations"]:
            self.assertGreaterEqual(
                row["org_rating"],
                1,
            )

            self.assertLessEqual(
                row["org_rating"],
                5,
            )

    def test_volunteer_json_valid(self):
        for row in self.data["volunteer_details"]:
            days = json.loads(
                row["availability_days"]
            )

            times = json.loads(
                row["availability_times"]
            )

            self.assertIsInstance(
                days,
                list,
            )

            self.assertIsInstance(
                times,
                list,
            )

    def test_user_emails_are_synthetic(self):
        for row in self.data["users"]:
            self.assertTrue(
                row["primary_email_address"].endswith(
                    "@example.invalid"
                )
            )

    def test_user_names_are_synthetic(self):
        for row in self.data["users"]:
            self.assertTrue(
                row["first_name"].startswith(
                    "Synthetic"
                )
            )

    def test_user_phone_numbers_are_synthetic(self):
        for row in self.data["users"]:
            self.assertTrue(
                row["primary_phone_number"].startswith(
                    "555"
                )
            )

    def test_organization_emails_are_synthetic(self):
        for row in self.data["organizations"]:
            self.assertTrue(
                row["email"].endswith(
                    "@example.invalid"
                )
            )

    def test_geography_format(self):
        for table_name in (
            "user_locations",
            "volunteer_locations",
        ):
            for row in self.data[table_name]:
                for field in (
                    "prev_loc",
                    "curr_loc",
                ):
                    latitude, longitude = (
                        parse_geography_point(
                            row[field]
                        )
                    )

                    self.assertGreaterEqual(
                        latitude,
                        -90,
                    )

                    self.assertLessEqual(
                        latitude,
                        90,
                    )

                    self.assertGreaterEqual(
                        longitude,
                        -180,
                    )

                    self.assertLessEqual(
                        longitude,
                        180,
                    )

    def test_volunteer_timestamp_order(self):
        for row in self.data["volunteer_details"]:
            created = parse_timestamp(
                row["created_at"]
            )

            updated = parse_timestamp(
                row["last_updated_at"]
            )

            self.assertLessEqual(
                created,
                updated,
            )

    def test_organization_timestamp_order(self):
        for row in self.data["organizations"]:
            created = parse_timestamp(
                row["created_at"]
            )

            updated = parse_timestamp(
                row["last_updated_at"]
            )

            self.assertLessEqual(
                created,
                updated,
            )

    def test_deterministic_generation(self):
        first = generate_all(
            self.config
        )

        second = generate_all(
            self.config
        )

        self.assertEqual(
            first,
            second,
        )

    def test_different_seed_changes_data(self):
        different_config = GeneratorConfig(
            seed=99,
            users=100,
            organizations=100,
            cities_per_state=5,
            volunteer_ratio=0.50,
            user_location_ratio=0.75,
            volunteer_location_ratio=1.00,
            skills_per_user_min=1,
            skills_per_user_max=3,
        )

        different_data = generate_all(
            different_config
        )

        self.assertNotEqual(
            self.data["users"],
            different_data["users"],
        )

    def test_invalid_configuration_rejected(self):
        config = GeneratorConfig(
            users=-1
        )

        with self.assertRaises(ValueError):
            config.validate()

    def test_invalid_ratio_rejected(self):
        config = GeneratorConfig(
            volunteer_ratio=1.5
        )

        with self.assertRaises(ValueError):
            config.validate()

    def test_duplicate_primary_key_detected(self):
        broken_data = generate_all(
            self.config
        )

        broken_data["users"][1]["user_id"] = (
            broken_data["users"][0]["user_id"]
        )

        with self.assertRaises(ValidationError):
            validate_all(broken_data)

    def test_orphan_volunteer_location_detected(self):
        broken_data = generate_all(
            self.config
        )

        broken_data["volunteer_locations"][0][
            "user_id"
        ] = "SID-00-999-999-999-999-999"

        with self.assertRaises(ValidationError):
            validate_all(broken_data)

    def test_orphan_skill_category_detected(self):
        broken_data = generate_all(
            self.config
        )

        broken_data["user_skills"][0][
            "cat_id"
        ] = "9999"

        with self.assertRaises(ValidationError):
            validate_all(broken_data)


if __name__ == "__main__":
    unittest.main()