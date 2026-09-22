"""Offline regression tests for extraction, cleaning and source propagation."""

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import requests
from bs4 import BeautifulSoup

MODULE_DIR = Path(__file__).resolve().parents[1] / "src/scrapers/emergency_contacts"
# Load the existing package by location; tests work from either repository root.
spec = importlib.util.spec_from_file_location("emergency_contacts", MODULE_DIR / "__init__.py",
                                             submodule_search_locations=[str(MODULE_DIR)])
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
from emergency_contacts import build_emergency_numbers as builder
from emergency_contacts import cleaner, scraper


@pytest.mark.parametrize("raw, expected", [
    ("000", "000"), ("024", "024"), ("0800-0113", "08000113"),
    ("(+683) 4333", "+6834333"), ("21 35 09 62", "21350962"),
    ("+224 621 35 01 01 or +224 664 26 98 53", ""),
    ("+44 (20) 123", "+4420123"), ("+44 (0) 123", ""), ("112 [ 1 ]", "112"),
    ("112 or 999", ""), ("115 and 1122", ""), ("112/116", ""),
    ("", ""), ("Gendarme - 1055", ""), ("depends on town/city", ""),
    ("122 CBV (national) 123 CBM (local)", ""), ("112+999", ""),
    ("++112", ""), ("+", ""), ("911 ext 23", ""), ("911; text only", ""),
])
def test_phone_normalization_does_not_manufacture_numbers(raw, expected):
    assert builder.clean_phone_number(raw) == expected


def test_numbers_must_be_strings():
    with pytest.raises(TypeError):
        builder.clean_phone_number(24)


def test_alternatives_require_review_instead_of_guessed_purpose_keys(tmp_path):
    source = tmp_path / "source.csv"
    overrides = tmp_path / "overrides.json"
    overrides.write_text("[]")
    write_source(source, [["Austria", "112 or 133", "144", "122", ""],
                         ["Pakistan", "15", "115 and 1122", "1122", ""]])
    data, report = builder.build_with_provenance(source, overrides, verified_only=False)
    assert "police" not in data["AT"]["default"]
    assert "ambulance" not in data["PK"]["default"]
    assert len(report["ambiguous_cells"]) == 2
    assert all(not key.endswith("_1") for country in data.values() for key in country["default"])


def test_merged_cells_and_notes_remain_aligned():
    html = """<table class="wikitable">
    <tr><th>Country</th><th>Police</th><th>Ambulance</th><th>Fire</th><th>Other numbers</th></tr>
    <tr><td>Algeria</td><td>1548<sup>[1]</sup></td><td colspan="2">14</td><td>Gendarme - 1055</td></tr>
    <tr><td>Japan</td><td>110</td><td colspan="2">119</td><td>Coast guard - 118</td></tr>
    <tr><td>Australia</td><td colspan="3">000</td><td>Mobile - 112</td></tr>
    </table>"""
    rows = scraper.parse_emergency_numbers(html).set_index("Country")
    assert rows.loc["Algeria", "Fire"] == "14"
    assert rows.loc["Algeria", "Notes"] == "Gendarme - 1055"
    assert rows.loc["Japan", "Fire"] == "119"
    assert rows.loc["Japan", "Notes"] == "Coast guard - 118"
    assert list(rows.loc["Australia", ["Police", "Ambulance", "Fire"]]) == ["000"] * 3


def test_rowspan_is_expanded():
    table = BeautifulSoup('<table><tr><td rowspan="2">A</td><td>1</td></tr>'
                          '<tr><td>2</td></tr></table>', "html.parser").table
    assert list(scraper.expand_table(table)) == [["A", "1"], ["A", "2"]]


@pytest.mark.parametrize("html", ["<html>rate limited</html>", """<table class="wikitable">
<tr><th>Country</th><th>Police</th><th>Ambulance</th><th>Fire</th><th>Notes</th></tr>
<tr><td>A</td><td>111</td></tr></table>"""])
def test_unexpected_source_does_not_become_guessed_data(html):
    with pytest.raises(ValueError):
        scraper.parse_emergency_numbers(html)


def test_http_failure_preserves_existing_output(tmp_path, monkeypatch):
    output = tmp_path / "raw.csv"
    output.write_text("existing source")
    class FailedResponse:
        def raise_for_status(self):
            raise requests.HTTPError("503 Service Unavailable")
    monkeypatch.setattr(scraper.requests, "get", lambda *a, **kw: FailedResponse())
    with pytest.raises(requests.HTTPError):
        scraper.scrape_emergency_numbers(output)
    assert output.read_text() == "existing source"


def write_source(path, rows):
    """Write synthetic source rows using the real CSV schema."""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(scraper.COLUMNS)
        writer.writerows(rows)


def test_cleaner_preserves_zero_prefixes_and_na_country(tmp_path, monkeypatch):
    overrides = tmp_path / "overrides.json"
    overrides.write_text("[]")
    monkeypatch.setattr(cleaner, "build_with_provenance", lambda path:
                        builder.build_with_provenance(path, overrides, verified_only=False))
    raw = tmp_path / "raw.csv"
    write_source(raw, [["Australia", "000", "000", "000", ""],
                       ["Namibia", "10111", "", "", ""]])
    cleaned = tmp_path / "cleaned.csv"
    data, report = cleaner.clean_emergency_data(raw, cleaned, tmp_path / "out.json", tmp_path / "report.json")
    rows = list(csv.DictReader(cleaned.open(encoding="utf-8")))
    assert rows[0]["Police"] == "000"
    assert data["AU"]["default"]["police"] == "000"
    assert data["NA"]["default"]["police"] == "10111"
    assert "ambulance" not in data["NA"]["default"]


def test_csv_updates_reach_json(tmp_path):
    raw = tmp_path / "source.csv"
    overrides = tmp_path / "overrides.json"
    overrides.write_text("[]")
    write_source(raw, [["United States of America", "911", "911", "911", ""]])
    before = builder.build_emergency_numbers_dataset(raw, overrides, verified_only=False)
    write_source(raw, [["United States of America", "911", "911", "999", ""]])
    after = builder.build_emergency_numbers_dataset(raw, overrides, verified_only=False)
    assert before["US"]["default"]["fire"] == "911"
    assert after["US"]["default"]["fire"] == "999"
    assert "general_emergency" not in after["US"]["default"]


def test_conflicting_country_rows_fail(tmp_path):
    source = tmp_path / "source.csv"
    write_source(source, [["Canada", "911", "911", "911", ""], ["Canada", "112", "112", "112", ""]])
    with pytest.raises(ValueError, match="Conflicting"):
        builder.build_emergency_numbers_dataset(source)


def test_duplicate_identical_source_rows_are_accepted(tmp_path):
    source = tmp_path / "source.csv"
    row = ["Turkey", "112", "112", "112", ""]
    write_source(source, [row, row])
    assert builder.build_emergency_numbers_dataset(source)["TR"]["default"]["police"] == "112"


def test_pruning_preserves_real_city_and_postal_differences():
    data = {"US": {"default": {"police": "911"}, "states": {
        "Example": {"default": {"police": "911", "fire": "112"},
                    "cities": {"Same": {"police": "911"}, "Different": {"fire": "999"}},
                    "zips": {"00123": {"police": "911", "ambulance": "112"}}},
        "Redundant": {"default": {"police": "911"}, "cities": {}, "zips": {}}
    }}}
    builder.prune_inherited(data)
    states = data["US"]["states"]
    assert "Redundant" not in states
    assert states["Example"] == {"default": {"fire": "112"},
                                  "cities": {"Different": {"fire": "999"}},
                                  "zips": {"00123": {"ambulance": "112"}}}


def test_source_note_is_not_converted_to_a_number(tmp_path):
    source = tmp_path / "source.csv"
    overrides = tmp_path / "overrides.json"
    overrides.write_text("[]")
    write_source(source, [["Namibia", "10111", "depends on town/city", "", ""]])
    data, report = builder.build_with_provenance(source, overrides, verified_only=False)
    assert data["NA"]["default"] == {"police": "10111"}
    assert report["ambiguous_cells"][0]["service"] == "ambulance"


@pytest.mark.parametrize("rows", [[], [["Unknown location", "911", "911", "911", ""]]])
def test_empty_or_unmapped_source_fails_instead_of_erasing_dataset(tmp_path, rows):
    source = tmp_path / "source.csv"
    write_source(source, rows)
    with pytest.raises(ValueError, match="No mapped"):
        builder.build_emergency_numbers_dataset(source)


def test_default_export_withholds_unreviewed_source_numbers(tmp_path):
    source, overrides = tmp_path / "source.csv", tmp_path / "overrides.json"
    write_source(source, [["Canada", "911", "911", "911", ""]])
    overrides.write_text("[]")
    data, report = builder.build_with_provenance(source, overrides)
    assert data["CA"] == {"default": {}, "states": {}}
    assert len(report["withheld_contacts"]) == 4
    assert report["contacts"] == []


def test_unreviewed_national_value_cannot_hide_reviewed_city(tmp_path):
    source, overrides = tmp_path / "source.csv", tmp_path / "overrides.json"
    write_source(source, [["Canada", "911", "911", "911", ""]])
    record = {"country": "CA", "state": "Example Province", "city": "Example City",
              "contacts": {"police": "911"}, "source_url": "https://example.org/source",
              "checked_on": "2026-09-15", "note": "Synthetic scoped source fixture.",
              "review_status": "government_guidance"}
    overrides.write_text(json.dumps([record]))
    data, report = builder.build_with_provenance(source, overrides)
    assert data["CA"]["default"] == {}
    assert data["CA"]["states"]["Example Province"]["cities"]["Example City"] == {"police": "911"}
    assert len(report["contacts"]) == 1


def test_unknown_review_status_is_rejected(tmp_path):
    source, overrides = tmp_path / "source.csv", tmp_path / "overrides.json"
    write_source(source, [["Canada", "911", "911", "911", ""]])
    overrides.write_text(json.dumps([{"country": "CA", "contacts": {"police": "911"},
                                     "source_url": "https://example.org/source", "checked_on": "2026-09-15",
                                     "note": "Synthetic fixture.", "review_status": "downloaded"}]))
    with pytest.raises(ValueError, match="Unknown review status"):
        builder.build_with_provenance(source, overrides)
