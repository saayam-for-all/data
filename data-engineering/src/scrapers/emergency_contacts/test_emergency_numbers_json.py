"""Tests for #333 emergency_numbers.json."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import generate_emergency_numbers_json as gen

JSON_PATH = (
    Path(__file__).resolve().parents[3] / "datasets" / "cleaned" / "emergency_numbers.json"
)


class EmergencyNumbersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(JSON_PATH.read_text(encoding="utf-8"))

    def test_file_is_object(self):
        self.assertIsInstance(self.data, dict)
        self.assertGreaterEqual(len(self.data), 240)

    def test_iso_codes_and_required_keys(self):
        for code, payload in self.data.items():
            self.assertRegex(code, r"^[A-Z]{2}$", code)
            self.assertIn("default", payload, code)
            self.assertIn("states", payload, code)
            self.assertIsInstance(payload["default"], dict, code)
            self.assertIsInstance(payload["states"], dict, code)

    def test_numbers_are_strings(self):
        self.assertEqual(gen.validate_dataset(self.data), [])

    def test_no_combined_number_strings(self):
        """Issue guidance: never store '112 or 133' / '999; 112' in one field."""
        combined = []

        def walk(path, obj):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    walk(f"{path}.{key}" if path else key, value)
            elif isinstance(obj, str):
                if ";" in obj or re.search(r"\bor\b", obj, re.I) or "/" in obj:
                    combined.append((path, obj))

        walk("", self.data)
        self.assertEqual(combined, [])

    def test_india_example_hierarchy(self):
        india = self.data["IN"]
        self.assertEqual(india["default"]["general_emergency"], "112")
        self.assertEqual(india["default"]["ambulance"], "108")
        self.assertEqual(india["default"]["fire"], "101")
        karnataka = india["states"]["Karnataka"]
        self.assertIn("default", karnataka)
        self.assertIn("Bengaluru", karnataka["cities"])
        self.assertIn("Mysuru", karnataka["cities"])
        self.assertIn("560001", karnataka["zips"])
        self.assertEqual(karnataka["cities"]["Bengaluru"]["police"], "112")

    def test_us_and_qatar_defaults(self):
        self.assertEqual(self.data["US"]["default"]["general_emergency"], "911")
        self.assertEqual(self.data["QA"]["default"]["general_emergency"], "999")
        self.assertEqual(self.data["US"]["states"], {})
        self.assertEqual(self.data["GB"]["default"]["police"], "999")
        self.assertEqual(self.data["GB"]["default"]["general_emergency"], "112")
        self.assertEqual(self.data["AU"]["default"]["police"], "000")

    def test_france_splits_service_numbers(self):
        france = self.data["FR"]["default"]
        self.assertEqual(france["general_emergency"], "112")
        self.assertEqual(france["police"], "17")
        self.assertEqual(france["ambulance"], "15")
        self.assertEqual(france["fire"], "18")

    def test_empty_sections_are_objects(self):
        self.assertEqual(self.data["AQ"]["states"], {})
        self.assertIsInstance(self.data["AQ"]["default"], dict)

    def test_extract_and_pick_numbers(self):
        self.assertEqual(gen.extract_numbers("112 or 999 [1]"), ["112", "999"])
        self.assertEqual(gen.extract_numbers("112, 999"), ["112", "999"])
        self.assertEqual(gen.normalize_numbers("112 or 999 [1]"), "112")
        self.assertEqual(gen.normalize_numbers("10 111"), "10111")
        self.assertIsNone(gen.normalize_numbers("depends on town/city"))
        self.assertEqual(gen.pick_service_number(["112", "133"]), "133")
        self.assertEqual(gen.pick_general_emergency(["112", "133"], ["144"], ["122"]), ("112", None))

    def test_dataset_uses_only_iso_alpha2_codes(self):
        self.assertNotIn("XK", self.data)
        for code in self.data:
            self.assertRegex(code, r"^[A-Z]{2}$")
            # XK is user-assigned, not an official ISO 3166-1 code.
            self.assertNotEqual(code, "XK")

    def test_validator_rejects_combined_and_non_string(self):
        bad = {"US": {"default": {"police": "112; 911"}, "states": {}}}
        errors = gen.validate_dataset(bad)
        self.assertTrue(any("combines multiple numbers" in item for item in errors))
        bad2 = {"US": {"default": {"police": 911}, "states": {}}}
        errors2 = gen.validate_dataset(bad2)
        self.assertTrue(any("not a string" in item for item in errors2))


if __name__ == "__main__":
    unittest.main()
