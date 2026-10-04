import json
from pathlib import Path


DATA_PATH = Path(__file__).parents[1] / "datasets" / "cleaned" / "emergency_numbers.json"


def test_emergency_numbers_has_iso_country_structure():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    assert len(data) == 249
    assert all(len(code) == 2 and code.isupper() for code in data)

    for country in data.values():
        assert set(country) == {"default", "states"}
        assert isinstance(country["default"], dict)
        assert isinstance(country["states"], dict)

        for state in country["states"].values():
            assert set(state) == {"default", "cities", "zips"}
            assert isinstance(state["default"], dict)
            assert isinstance(state["cities"], dict)
            assert isinstance(state["zips"], dict)


def test_emergency_numbers_are_strings():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    def assert_string_values(values):
        assert all(isinstance(value, str) for value in values.values())

    for country in data.values():
        assert_string_values(country["default"])
        for state in country["states"].values():
            assert_string_values(state["default"])
            for city in state["cities"].values():
                assert_string_values(city)
            for zip_code in state["zips"].values():
                assert_string_values(zip_code)
