"""Validate the delivered hierarchy against independent references and sources."""

import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = ROOT / "src/scrapers/emergency_contacts"
DATA_PATH = ROOT / "datasets/cleaned/emergency_numbers.json"
REPORT_PATH = ROOT / "datasets/cleaned/emergency_numbers_provenance.json"
ISO_PATH = Path(__file__).parent / "fixtures/iso_alpha2.txt"
spec = importlib.util.spec_from_file_location("emergency_builder", MODULE_DIR / "build_emergency_numbers.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def unique_object(pairs):
    """Reject duplicate JSON keys, which json.loads normally hides."""
    result = {}
    for key, value in pairs:
        assert key not in result, f"Duplicate JSON key: {key}"
        result[key] = value
    return result


@pytest.fixture(scope="module")
def emergency_data():
    return json.loads(DATA_PATH.read_text(encoding="utf-8"), object_pairs_hook=unique_object)


def test_independent_iso_membership(emergency_data):
    # Factual ISO alpha-2 reference collected independently from pycountry's
    # iso3166-1 database, 2026-09-15. Do not derive it from the builder/output.
    expected = set(ISO_PATH.read_text().split())
    assert len(expected) == 249
    assert set(emergency_data) == expected


@pytest.mark.parametrize("code, expected", [
    ("AT", {"general_emergency": "112", "police": "133"}),
    ("BE", {"general_emergency": "112", "police": "101"}),
    ("GB", {"general_emergency": "999", "general_emergency_alternate": "112"}),
    ("PK", {"ambulance": "1122", "ambulance_edhi": "115"}),
    ("SC", {"general_emergency": "999", "general_emergency_mobile": "112", "ambulance": "151"}),
    ("SB", {"police": "999", "ambulance": "111", "ambulance_alternate": "911"}),
    ("LK", {"police": "119", "emergency_information": "118", "ambulance": "1990"}),
    ("BQ", {"ambulance": "912", "coast_guard": "913"}),
    ("LA", {"ambulance_local_sim": "0305257239", "ambulance_foreign_sim": "+856305257239"}),
])
def test_reviewed_alternatives_have_actual_service_fields(emergency_data, code, expected):
    assert expected.items() <= emergency_data[code]["default"].items()


def test_municipal_contacts_are_not_promoted_to_country_defaults(emergency_data):
    assert "municipal_police" not in emergency_data["TR"]["default"]
    assert emergency_data["TR"]["states"]["Istanbul"]["cities"]["Istanbul"]["municipal_police"] == "153"
    assert "fire_municipal" not in emergency_data["GT"]["default"]
    assert emergency_data["GT"]["states"]["Guatemala"]["cities"]["Guatemala City"]["fire_municipal"] == "123"


def test_review_audit_accounts_for_candidates_without_guessing(emergency_data):
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    cases = {(r["country"], r["number"]): r for r in report["number_review"]}
    assert len(cases) == len(report["number_review"])
    assert cases["AT", "112"]["disposition"] == "mapped"
    assert any(m["path"][-1] == "general_emergency" for m in cases["AT", "112"]["mappings"])
    assert cases["GI", "190"]["disposition"] == "superseded"
    assert cases["KI", "100"]["disposition"] == "not_emergency"
    assert cases["GA", "0174"]["disposition"] == "needs_verification"
    for case in cases.values():
        if case["disposition"] == "mapped":
            for mapping in case["mappings"]:
                value = emergency_data
                for key in mapping["path"]:
                    value = value[key]
                assert value == case["number"]
                assert mapping["source_url"].startswith("https://")
        else:
            assert case["reason"] and case["source_url"].startswith("https://")
    for code, retired in [("AM", {"911"}), ("GI", {"190", "199", "112"})]:
        assert not retired.intersection(emergency_data[code]["default"].values())


def test_complete_hierarchy_and_string_values(emergency_data):
    for code, country in emergency_data.items():
        assert re.fullmatch(r"[A-Z]{2}", code)
        assert set(country) == {"default", "states"}
        assert isinstance(country["default"], dict)
        assert isinstance(country["states"], dict)
        for name, state in country["states"].items():
            assert isinstance(name, str) and name.strip()
            assert set(state) == {"default", "cities", "zips"}
            assert all(isinstance(value, dict) for value in state.values())
            for level in ("cities", "zips"):
                for place, contacts in state[level].items():
                    assert isinstance(place, str) and place.strip()
                    assert isinstance(contacts, dict)
    for path, number in builder.iter_contacts(emergency_data):
        assert re.fullmatch(r"[a-z][a-z0-9_]*", path[-1])
        assert isinstance(number, str)
        assert re.fullmatch(r"\+?[0-9]{2,15}", number), (path, number)


def test_no_repeated_inherited_regional_values(emergency_data):
    for country in emergency_data.values():
        for state in country["states"].values():
            assert any(state.values()), "Empty regional containers should be omitted"
            for key, value in state["default"].items():
                assert country["default"].get(key) != value
            inherited = {**country["default"], **state["default"]}
            for level in ("cities", "zips"):
                for contacts in state[level].values():
                    assert contacts
                    assert all(inherited.get(key) != value for key, value in contacts.items())


def test_verified_corrections_and_local_scope(emergency_data):
    assert emergency_data["BH"]["default"]["fire"] == "999"
    assert emergency_data["DZ"]["default"]["ambulance"] == "1021"
    assert "ambulance" not in emergency_data["AF"]["default"]
    assert emergency_data["AF"]["states"]["Kabul"]["cities"]["Kabul"]["ambulance"] == "102"
    assert emergency_data["ES"]["default"]["suicide_helpline"] == "024"
    assert emergency_data["KR"]["default"]["suicide_helpline"] == "109"
    assert emergency_data["IN"]["default"]["disaster_management"] == "1078"
    assert emergency_data["PK"]["states"]["Punjab"]["default"]["women_helpline"] == "1043"
    assert "women_helpline" not in emergency_data["PK"]["default"]
    assert emergency_data["AU"]["default"]["police"] == "000"
    assert emergency_data["NF"]["default"]["general_emergency"] == "000"
    assert emergency_data["PN"]["default"] == {}


def test_every_contact_has_traceable_provenance(emergency_data):
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    rows = report["contacts"]
    indexed = {tuple(row["path"]): row for row in rows}
    assert len(indexed) == len(rows)
    assert set(indexed) == {path for path, _ in builder.iter_contacts(emergency_data)}
    for path, number in builder.iter_contacts(emergency_data):
        source = indexed[path]
        assert source["number"] == number
        assert source["source_url"].startswith("https://")
        assert source["review_status"] in {"government_guidance", "official_or_service_operator"}
        assert "source_row" in source or (source["checked_on"] and source["note"])
    assert report["countries_without_contacts"] == [
        code for code, country in emergency_data.items() if not country["default"]
    ]


def test_deliverables_reproduce_from_committed_inputs(emergency_data):
    data, report = builder.build_with_provenance()
    assert data == emergency_data
    assert report == json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def test_country_review_inventory_and_documented_empty_sections(emergency_data):
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    assert set(report["country_coverage"]) == set(emergency_data)
    assert sum(report["review_status_counts"].values()) == len(report["contacts"])
    for code, coverage in report["country_coverage"].items():
        if not coverage["contact_count"]:
            assert emergency_data[code] == {"default": {}, "states": {}}
            assert coverage["research_note"]["source_urls"]
            assert coverage["research_note"]["checked_on"]


def test_network_and_geographic_restrictions_are_not_promoted(emergency_data):
    assert emergency_data["MY"]["default"]["fire"] == "999"
    assert emergency_data["CM"]["default"]["fire_mobile"] == "118"
    assert "police" not in emergency_data["CM"]["default"]
    assert emergency_data["CM"]["states"]["Centre"]["cities"]["Yaoundé"]["police_mobile"] == "117"
    assert emergency_data["SH"]["default"] == {}
    assert emergency_data["SH"]["states"]["Tristan da Cunha"]["default"]["police"] == "5111"
    assert "ambulance" not in emergency_data["MH"]["default"]
    assert emergency_data["MH"]["states"]["Majuro"]["cities"]["Majuro"]["ambulance"] == "6254144"
    assert "general_emergency" not in emergency_data["ZW"]["default"]
    assert emergency_data["ZW"]["default"]["general_emergency_netone"] == "114"
    assert emergency_data["AQ"]["default"] == {}
    assert emergency_data["AQ"]["states"]["Ross Island"]["cities"]["McMurdo Station"]["fire"] == "911"
