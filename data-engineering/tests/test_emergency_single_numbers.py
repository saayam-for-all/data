"""Check the lead's requested selection policy and reproducible output."""

import importlib.util
import json
import sys
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parents[1] / "src/scrapers/emergency_contacts"
sys.path.insert(0, str(MODULE_DIR))
spec = importlib.util.spec_from_file_location("single_numbers", MODULE_DIR / "build_single_numbers.py")
single = importlib.util.module_from_spec(spec)
spec.loader.exec_module(single)
sys.path.pop(0)


def test_general_then_police_priority():
    data = {"AA": {"default": {"general_emergency": "000", "police": "123"}, "states": {}},
            "BB": {"default": {"police": "0123", "ambulance": "999"}, "states": {}}}
    numbers, services = single.select_single_numbers(data)
    assert numbers == {"AA": "000", "BB": "0123"}
    assert services == {"AA": "general_emergency", "BB": "police"}


def test_restricted_or_regional_number_is_not_promoted():
    data = {"AA": {"default": {"police_mobile": "117", "ambulance": "999"},
                    "states": {"Local": {"default": {"police": "911"}, "cities": {}, "zips": {}}}}}
    numbers, services = single.select_single_numbers(data)
    assert numbers == {"AA": ""}
    assert services == {"AA": None}


def test_single_deliverables_and_provenance_reproduce():
    numbers, report = single.build_single_numbers()
    assert numbers == json.loads(single.OUTPUT_FILE.read_text(encoding="utf-8"))
    assert report == json.loads(single.REPORT_FILE.read_text(encoding="utf-8"))
    expected = set((Path(__file__).parent / "fixtures/iso_alpha2.txt").read_text().split())
    assert set(numbers) == expected
    assert all(isinstance(value, str) for value in numbers.values())
    assert {row["country"] for row in report["contacts"]} == {code for code, value in numbers.items() if value}
    assert all(numbers[row["country"]] == row["number"] for row in report["contacts"])
