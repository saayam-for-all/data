"""Tests for #333 emergency_numbers.json."""

from __future__ import annotations

import json
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
        self.assertIn("999", self.data["GB"]["default"]["police"])
        self.assertNotEqual(self.data["GB"]["default"]["police"], "101")
        self.assertEqual(self.data["AU"]["default"]["police"], "000")

    def test_empty_sections_are_objects(self):
        self.assertEqual(self.data["AQ"]["states"], {})
        self.assertIsInstance(self.data["AQ"]["default"], dict)

    def test_normalize_numbers(self):
        self.assertEqual(gen.normalize_numbers("112 or 999 [1]"), "112; 999")
        self.assertEqual(gen.normalize_numbers("10 111"), "10111")
        self.assertIsNone(gen.normalize_numbers("depends on town/city"))

    def test_validator_rejects_non_string(self):
        bad = {"US": {"default": {"police": 911}, "states": {}}}
        errors = gen.validate_dataset(bad)
        self.assertTrue(any("not a string" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
