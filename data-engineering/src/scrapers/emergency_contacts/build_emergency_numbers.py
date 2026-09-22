"""Build the issue #333 hierarchy from collected data and sourced corrections.

The CSV is a secondary source, not a claim of official verification. The generated
provenance file identifies every emitted number and records omitted/ambiguous data.
"""

import csv
from collections import Counter
from datetime import date
import hashlib
import json
import re
import unicodedata
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[3]
MODULE_DIR = Path(__file__).resolve().parent
INPUT_FILE = BASE_DIR / "datasets/cleaned/cleaned_emergency_numbers.csv"
OUTPUT_FILE = BASE_DIR / "datasets/cleaned/emergency_numbers.json"
REPORT_FILE = BASE_DIR / "datasets/cleaned/emergency_numbers_provenance.json"
OVERRIDES_FILE = MODULE_DIR / "contact_overrides.json"
COUNTRY_NAMES_FILE = MODULE_DIR / "country_names.json"
COVERAGE_NOTES_FILE = MODULE_DIR / "coverage_notes.json"
NUMBER_REVIEW_FILE = MODULE_DIR / "number_review_decisions.json"
SOURCE_URL = "https://en.wikipedia.org/wiki/List_of_emergency_telephone_numbers"
PHONE_PATTERN = re.compile(r"\+?[0-9]{2,15}")
REVIEW_STATUSES = {"secondary_source", "government_guidance", "official_or_service_operator"}

ALIASES = {
    "Cape Verde": "CV", "Republic of Congo": "CG", "Democratic Republic of Congo": "CD",
    "Ivory Coast": "CI", "The Bahamas": "BS", "British Virgin Islands": "VG",
    "Caribbean Netherlands": "BQ", "Curacao": "CW", "Saint Martin": "MF",
    "Turks and Caicos": "TC", "U.S. Virgin Islands": "VI", "United States of America": "US",
    "Brunei": "BN", "People's Republic of China": "CN", "East Timor": "TL",
    "Democratic People's Republic of Korea": "KP", "Republic of Korea": "KR",
    "Laos": "LA", "Macau": "MO", "Palestine": "PS", "Republic of China ( Taiwan )": "TW",
    "Turkey": "TR", "Czech Republic": "CZ", "Russia": "RU", "Vatican City": "VA",
    "Micronesia": "FM", "South Korea": "KR", "North Korea": "KP", "Saint Helena": "SH",
    "Falkland Islands": "FK", "Sint Maarten": "SX",
}


def strip_references(value: str) -> str:
    """Remove footnotes while leaving descriptive content intact."""
    return re.sub(r"\[[^\]]*\]", "", value).strip()


def normalize_country(value: str) -> str:
    """Normalize accents and whitespace, without fuzzy country matching."""
    value = unicodedata.normalize("NFKD", strip_references(value))
    return " ".join("".join(c for c in value if not unicodedata.combining(c)).casefold().split())


def clean_phone_number(raw_value: str) -> str:
    """Normalize one unqualified number; leave alternatives for source review.

    Never infer purpose from prose or take the first digit run from a number.
    Optional international trunk prefixes need country-specific review.
    """
    if not isinstance(raw_value, str):
        raise TypeError("Phone numbers must be strings")
    value = strip_references(raw_value)
    value = re.sub(r"^\(\+([0-9]+)\)", r"+\1", value)
    if not value or "(0)" in value or not re.fullmatch(r"\+?[0-9 ()-]+", value):
        return ""
    number = re.sub(r"[ ()-]", "", value)
    return number if PHONE_PATTERN.fullmatch(number) else ""


def iter_contacts(dataset):
    """Yield path/value pairs for every emergency contact in the hierarchy."""
    for code, country in dataset.items():
        for service, number in country["default"].items():
            yield (code, "default", service), number
        for name, state in country["states"].items():
            prefix = (code, "states", name)
            for service, number in state["default"].items():
                yield prefix + ("default", service), number
            for level in ("cities", "zips"):
                for place, contacts in state[level].items():
                    for service, number in contacts.items():
                        yield prefix + (level, place, service), number


def prune_inherited(dataset):
    """Keep regional differences and the containers required to reach them."""
    for country in dataset.values():
        for name, state in list(country["states"].items()):
            state["default"] = {
                key: value for key, value in state["default"].items()
                if country["default"].get(key) != value
            }
            inherited = {**country["default"], **state["default"]}
            for level in ("cities", "zips"):
                state[level] = {
                    place: {key: value for key, value in contacts.items()
                            if inherited.get(key) != value}
                    for place, contacts in state[level].items()
                }
                state[level] = {key: value for key, value in state[level].items() if value}
            if not any(state.values()):
                del country["states"][name]


def review_number_candidates(dataset, report, lookup, review_path=NUMBER_REVIEW_FILE):
    """Account for ambiguous source numbers without using them to create contacts.

    Candidate extraction is audit-only. Every exported mapping must already have
    passed the curated source checks. Matching a number reports its actual field
    and location; it does not endorse the original CSV service label.
    """
    decisions = json.loads(Path(review_path).read_text(encoding="utf-8"))
    report["number_review_sha256"] = hashlib.sha256(Path(review_path).read_bytes()).hexdigest()
    candidates = {}
    for cell in report["ambiguous_cells"]:
        code = lookup[normalize_country(cell["country"])]
        for number in re.findall(r"(?<![\w+])\+?[0-9]{2,15}(?!\w)", cell["value"]):
            entry = candidates.setdefault((code, number), {"country": code, "number": number,
                                                         "source_cells": []})
            entry["source_cells"].append(cell)
    for case in decisions["additional_cases"]:
        for number in case["numbers"]:
            entry = candidates.setdefault((case["country"], number), {
                "country": case["country"], "number": number, "source_cells": []})
            entry.setdefault("additional_sources", []).append(case["source_url"])
    withheld = {(r["country"], r["number"]): r for r in decisions["withheld"]}
    contacts = {}
    for contact in report["contacts"]:
        contacts.setdefault((contact["path"][0], contact["number"]), []).append(contact)
    for key, entry in candidates.items():
        matches = contacts.get(key, [])
        if matches:
            entry["disposition"] = "mapped"
            entry["mappings"] = [{"path": c["path"], "source_url": c["source_url"]}
                                 for c in matches]
        elif key in withheld:
            entry.update(withheld[key])
        else:
            entry.update(disposition="needs_verification",
                         reason="No reviewed purpose and location mapping for this candidate.")
    report["number_review"] = [candidates[key] for key in sorted(candidates)]
    report["number_review_summary"] = dict(sorted(Counter(
        item["disposition"] for item in report["number_review"]
    ).items()))


def build_with_provenance(input_path=INPUT_FILE, overrides_path=OVERRIDES_FILE, *, verified_only=True):
    """Build reviewed contacts; optionally include secondary data for research.

    Reviewed means checked against the cited publication, not a live-call test.
    Government guidance is distinguished from local authorities and operators.
    """
    names = json.loads(COUNTRY_NAMES_FILE.read_text(encoding="utf-8"))
    codes = set(names.values())
    lookup = {normalize_country(name): code for name, code in {**names, **ALIASES}.items()}
    dataset = {code: {"default": {}, "states": {}} for code in sorted(codes)}
    provenance = {}
    report = {
        "source_url": SOURCE_URL,
        "input_sha256": hashlib.sha256(Path(input_path).read_bytes()).hexdigest(),
        "curated_input_sha256": hashlib.sha256(Path(overrides_path).read_bytes()).hexdigest(),
        "source_status": "reviewed_contacts_only" if verified_only else "research_including_secondary_sources",
        "unmapped_rows": [], "ambiguous_cells": [], "suppressed_contacts": [],
        "source_notes": {},
    }
    seen = {}
    source_row_count = 0
    with Path(input_path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not {"Country", "Police", "Ambulance", "Fire", "Notes"}.issubset(reader.fieldnames or []):
            raise ValueError("CSV must contain Country, Police, Ambulance, Fire and Notes")
        for line, row in enumerate(reader, 2):
            source_row_count += 1
            if any(value is None for value in row.values()) or None in row:
                raise ValueError(f"Malformed CSV row {line}")
            if row["Notes"]:
                report["source_notes"][str(line)] = row["Notes"]
            code = lookup.get(normalize_country(row["Country"]))
            if code is None:
                report["unmapped_rows"].append({"row": line, "country": row["Country"],
                    "source_contacts": {key.lower(): row[key] for key in ("Police", "Ambulance", "Fire")}})
                continue
            contacts = {}
            for column in ("Police", "Ambulance", "Fire"):
                raw = row[column]
                number = clean_phone_number(raw)
                if not number:
                    if raw:
                        report["ambiguous_cells"].append({"row": line, "country": row["Country"],
                                                           "service": column.lower(), "value": raw})
                    continue
                service = column.lower()
                contacts[service] = number
                provenance[(code, "default", service)] = {
                    "source_url": SOURCE_URL, "source_row": line,
                    "source_country": row["Country"], "source_column": column,
                    "source_value": raw, "review_status": "secondary_source",
                }
            if code in seen and seen[code] != contacts:
                raise ValueError(f"Conflicting source rows for {code}; add an explicit location mapping")
            seen[code] = contacts.copy()
            # Equal service columns document a shared emergency number. No other
            # country-level general number is inferred from a single service.
            primary_services = ["police", "ambulance", "fire"]
            if all(s in contacts for s in primary_services) and len(set(contacts[s] for s in primary_services)) == 1:
                general_num = contacts["police"]
                contacts["general_emergency"] = general_num
                provenance[(code, "default", "general_emergency")] = {
                    "source_url": SOURCE_URL, "source_row": line,
                    "source_country": row["Country"],
                    "derivation": "same number in all three primary-service columns",
                    "review_status": "secondary_source",
                }
            dataset[code]["default"] = contacts

    if source_row_count == 0 or not seen:
        raise ValueError("No mapped emergency-number source rows")

    overrides = json.loads(Path(overrides_path).read_text(encoding="utf-8"))
    for record in overrides:
        code = record["country"]
        if code not in dataset:
            raise ValueError(f"Non-ISO override: {code}")
        if not record.get("source_url", "").startswith("https://") or not record.get("checked_on"):
            raise ValueError(f"Missing source/date: {record}")
        date.fromisoformat(record["checked_on"])
        if record.get("review_status") not in REVIEW_STATUSES:
            raise ValueError(f"Unknown review status for {code}")
        if record.get("city") and record.get("zip"):
            raise ValueError("An override must target either a city or a postal code")
        for field in ("state", "city", "zip"):
            if field in record and (not isinstance(record[field], str) or not record[field].strip()):
                raise ValueError(f"{field} must be a nonempty string")
        country = dataset[code]
        path = (code, "default")
        target = country["default"]
        if record.get("state"):
            state = country["states"].setdefault(record["state"], {"default": {}, "cities": {}, "zips": {}})
            path = (code, "states", record["state"], "default")
            target = state["default"]
            for field, level in (("city", "cities"), ("zip", "zips")):
                if record.get(field):
                    target = state[level].setdefault(record[field], {})
                    path = (code, "states", record["state"], level, record[field])
        elif record.get("city") or record.get("zip"):
            raise ValueError("City/postal-code records require a state")
        for service in record.get("remove", []):
            target.pop(service, None)
            provenance.pop(path + (service,), None)
            report["suppressed_contacts"].append({"path": list(path + (service,)), "reason": record["note"],
                                                   "source_url": record["source_url"]})
        for service, number in record.get("contacts", {}).items():
            if not re.fullmatch(r"[a-z][a-z0-9_]*", service):
                raise ValueError(f"Invalid service key: {service}")
            if not isinstance(number, str) or not PHONE_PATTERN.fullmatch(number):
                raise ValueError(f"Invalid curated number: {code}/{service}: {number!r}")
            target[service] = number
            provenance[path + (service,)] = {key: record[key] for key in
                                            ("source_url", "checked_on", "note", "review_status")}
            if record.get("source_updated_on"):
                date.fromisoformat(record["source_updated_on"])
                provenance[path + (service,)]["source_updated_on"] = record["source_updated_on"]
    # Filter before pruning: an unreviewed national value must not suppress a
    # reviewed regional contact merely because the two happen to be identical.
    report["withheld_contacts"] = []
    if verified_only:
        for path, number in list(iter_contacts(dataset)):
            if provenance[path]["review_status"] not in {
                "official_or_service_operator", "government_guidance"
            }:
                target = dataset
                for key in path[:-1]:
                    target = target[key]
                del target[path[-1]]
                report["withheld_contacts"].append({
                    "path": list(path), "number": number, **provenance[path],
                    "reason": "No reviewed government or service-operator source for this contact."
                })
    prune_inherited(dataset)
    report["contacts"] = [{"path": list(path), "number": number, **provenance[path]}
                          for path, number in iter_contacts(dataset)]
    report["countries_without_contacts"] = [code for code, country in dataset.items()
                                             if not country["default"]]
    report["country_count"] = len(dataset)
    report["countries_without_any_contacts"] = [
        code for code, country in dataset.items() if not any(country.values())
    ]
    report["review_status_counts"] = dict(sorted(Counter(
        row["review_status"] for row in report["contacts"]
    ).items()))
    report["country_coverage"] = {}
    coverage_notes = json.loads(COVERAGE_NOTES_FILE.read_text(encoding="utf-8"))
    for code, country in dataset.items():
        contacts = [row for row in report["contacts"] if row["path"][0] == code]
        report["country_coverage"][code] = {
            "contact_count": len(contacts),
            "national_services": sorted(country["default"]),
            "states": sorted(country["states"]),
            "source_urls": sorted({row["source_url"] for row in contacts}),
            "status": "has_reviewed_contacts" if contacts else "no_suitable_contact_collected",
        }
        if not contacts and code in coverage_notes:
            report["country_coverage"][code]["research_note"] = coverage_notes[code]
    if Path(input_path).resolve() == INPUT_FILE.resolve() and Path(overrides_path).resolve() == OVERRIDES_FILE.resolve():
        review_number_candidates(dataset, report, lookup)
    return dataset, report


def build_emergency_numbers_dataset(input_path=INPUT_FILE, overrides_path=OVERRIDES_FILE, *, verified_only=True):
    """Return only the issue's requested hierarchy; metadata lives separately."""
    return build_with_provenance(input_path, overrides_path, verified_only=verified_only)[0]


def save_dataset(dataset: dict, output_path: Path):
    """Write deterministic, UTF-8 JSON with a terminating newline."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(dataset, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    dataset, report = build_with_provenance()
    save_dataset(dataset, OUTPUT_FILE)
    save_dataset(report, REPORT_FILE)
    print(f"Built {len(dataset)} countries; {len(report['countries_without_contacts'])} empty defaults.")
