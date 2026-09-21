"""Build emergency_numbers.json for issue #333.

Sources:
- ISO 3166-1 alpha-2 country list
- Wikipedia "List of emergency telephone numbers" (tables only)

Missing numbers are left blank. Values are never invented.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ISO_URL = (
    "https://raw.githubusercontent.com/lukes/ISO-3166-Countries-with-Regional-Codes/"
    "master/all/all.json"
)
WIKI_URL = (
    "https://en.wikipedia.org/api/rest_v1/page/html/List_of_emergency_telephone_numbers"
)
USER_AGENT = (
    "SaayamEmergencyContacts/1.0 (https://github.com/saayam-for-all/data; issue #333)"
)

PREFERRED_FIELDS = (
    "general_emergency",
    "general_emergency_alternate",
    "police",
    "ambulance",
    "fire",
    "disaster_management",
    "women_helpline",
    "suicide_helpline",
    "child_helpline",
    "coastguard",
    "tourist_helpline",
    "traffic_police",
    "gendarmerie",
    "gas_leak",
)

# Wikipedia country labels that do not match ISO English short names.
NAME_ALIASES = {
    "united states of america": "US",
    "united states": "US",
    "people's republic of china": "CN",
    "china": "CN",
    "republic of korea": "KR",
    "south korea": "KR",
    "democratic people's republic of korea": "KP",
    "north korea": "KP",
    "republic of china (taiwan)": "TW",
    "taiwan": "TW",
    "cape verde": "CV",
    "cabo verde": "CV",
    "ivory coast": "CI",
    "cote d'ivoire": "CI",
    "côte d'ivoire": "CI",
    "republic of congo": "CG",
    "republic of the congo": "CG",
    "democratic republic of congo": "CD",
    "democratic republic of the congo": "CD",
    "the bahamas": "BS",
    "bahamas": "BS",
    "gambia": "GM",
    "the gambia": "GM",
    "east timor": "TL",
    "timor-leste": "TL",
    "macau": "MO",
    "macao": "MO",
    "palestine": "PS",
    "state of palestine": "PS",
    "vatican city": "VA",
    "holy see": "VA",
    "russia": "RU",
    "russian federation": "RU",
    "united kingdom": "GB",
    "great britain": "GB",
    "syria": "SY",
    "syrian arab republic": "SY",
    "laos": "LA",
    "lao people's democratic republic": "LA",
    "moldova": "MD",
    "republic of moldova": "MD",
    "tanzania": "TZ",
    "united republic of tanzania": "TZ",
    "iran": "IR",
    "vietnam": "VN",
    "viet nam": "VN",
    "bolivia": "BO",
    "venezuela": "VE",
    "micronesia": "FM",
    "brunei": "BN",
    "brunei darussalam": "BN",
    "czech republic": "CZ",
    "czechia": "CZ",
    "eswatini": "SZ",
    "swaziland": "SZ",
    "north macedonia": "MK",
    "myanmar": "MM",
    "caribbean netherlands": "BQ",
    "curacao": "CW",
    "curaçao": "CW",
    "sint maarten": "SX",
    "saint barthelemy": "BL",
    "saint barthélemy": "BL",
    "saint martin": "MF",
    "turks and caicos": "TC",
    "turks and caicos islands": "TC",
    "british virgin islands": "VG",
    "u.s. virgin islands": "VI",
    "united states virgin islands": "VI",
    "cocos islands": "CC",
    "cocos (keeling) islands": "CC",
    "christmas island": "CX",
    "falkland islands": "FK",
    "south georgia and the south sandwich islands": "GS",
    "british indian ocean territory": "IO",
    "northern mariana islands": "MP",
    "wallis and futuna": "WF",
    "saint helena": "SH",
    "reunion": "RE",
    "réunion": "RE",
    "mayotte": "YT",
    "western sahara": "EH",
    "aland islands": "AX",
    "åland islands": "AX",
    "sao tome and principe": "ST",
    "são tomé and príncipe": "ST",
    "guinea-bissau": "GW",
    "hong kong": "HK",
    "netherlands": "NL",
    "south africa": "ZA",
    "united arab emirates": "AE",
    "new zealand": "NZ",
    "south sudan": "SS",
    "antigua and barbuda": "AG",
    "bosnia and herzegovina": "BA",
    "trinidad and tobago": "TT",
    "saint kitts and nevis": "KN",
    "saint vincent and the grenadines": "VC",
    "marshall islands": "MH",
    "solomon islands": "SB",
    "cook islands": "CK",
    "american samoa": "AS",
    "french polynesia": "PF",
    "new caledonia": "NC",
    "french guiana": "GF",
    "guadeloupe": "GP",
    "martinique": "MQ",
    "puerto rico": "PR",
    "guam": "GU",
    "greenland": "GL",
    "faroe islands": "FO",
    "gibraltar": "GI",
    "isle of man": "IM",
    "guernsey": "GG",
    "jersey": "JE",
    "cayman islands": "KY",
    "bermuda": "BM",
    "aruba": "AW",
    "montserrat": "MS",
    "dominica": "DM",
    "dominican republic": "DO",
    "el salvador": "SV",
    "costa rica": "CR",
    "saudi arabia": "SA",
    "sri lanka": "LK",
    "papua new guinea": "PG",
    "equatorial guinea": "GQ",
    "central african republic": "CF",
    "burkina faso": "BF",
    "sierra leone": "SL",
    "south korea": "KR",
}

# Issue #333 example: documented India numbers plus the requested Karnataka sample.
# City/ZIP rows are included only as in the issue example; they are not invented.
INDIA_EXAMPLE = {
    "default": {
        "general_emergency": "112",
        "police": "112",
        "ambulance": "108",
        "fire": "101",
        "disaster_management": "108",
        "women_helpline": "1091",
        "suicide_helpline": "9152987821",
        "child_helpline": "1098",
    },
    "states": {
        "Karnataka": {
            "default": {
                "police": "112",
                "ambulance": "108",
                "fire": "101",
            },
            "cities": {
                "Bengaluru": {"police": "112", "ambulance": "108"},
                "Mysuru": {"police": "112", "ambulance": "108"},
            },
            "zips": {
                "560001": {"police": "112", "ambulance": "108"},
            },
        }
    },
}

SKIP_VALUES = re.compile(
    r"depend|local numbers only|mcmurdo|unknown|n/?a|none",
    re.I,
)
CITATIONS = re.compile(r"\[[^\]]*\]")
LABEL_NUMBER = re.compile(
    r"(?P<label>"
    r"suicide(?: hotline)?|crisis hotline|lifeline|"
    r"women(?:'?s? helpline)?|domestic violence|"
    r"child(?: helpline)?|"
    r"disaster(?: management)?|civil defense|civil protection|"
    r"coast ?guard|maritime|sea rescue|"
    r"tourist(?: helpline)?|"
    r"traffic police|"
    r"gendarme(?:rie)?|"
    r"gas leak(?:age)?|"
    r"police|ambulance|fire(?: brigade)?"
    r")\s*[–—:\-]\s*(?P<number>[+\d][\d\s\-/,or]*)",
    re.I,
)
# Shared national / multi-service numbers. When a Wikipedia cell lists these
# together with a service-specific number, keep them on separate fields.
UNIVERSAL_NUMBERS = ("112", "911", "999", "000", "111")


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


class WikiTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: List[List[List[str]]] = []
        self._in_table = False
        self._in_tr = False
        self._in_cell = False
        self._cell: List[str] = []
        self._colspan = 1
        self._row: List[str] = []
        self._table: List[List[str]] = []
        self._depth = 0
        self._ignore_sup = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attrs_d = dict(attrs)
        css = attrs_d.get("class") or ""
        if tag == "table" and "wikitable" in css and not self._in_table:
            self._in_table = True
            self._table = []
            self._depth = 1
            return
        if not self._in_table:
            return
        if tag == "table":
            self._depth += 1
        if tag == "sup":
            self._ignore_sup += 1
        if tag == "tr" and self._depth == 1:
            self._in_tr = True
            self._row = []
        if tag in ("td", "th") and self._in_tr and self._depth == 1:
            self._in_cell = True
            self._cell = []
            try:
                self._colspan = int(attrs_d.get("colspan") or "1")
            except ValueError:
                self._colspan = 1
        if tag == "br" and self._in_cell and not self._ignore_sup:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if not self._in_table:
            return
        if tag == "sup" and self._ignore_sup:
            self._ignore_sup -= 1
        if tag in ("td", "th") and self._in_cell:
            text = "".join(self._cell)
            for _ in range(max(1, self._colspan)):
                self._row.append(text)
            self._in_cell = False
        if tag == "tr" and self._in_tr and self._depth == 1:
            if self._row:
                self._table.append(self._row)
            self._in_tr = False
        if tag == "table":
            self._depth -= 1
            if self._depth == 0:
                self.tables.append(self._table)
                self._in_table = False

    def handle_data(self, data: str) -> None:
        if self._in_cell and not self._ignore_sup:
            self._cell.append(data)


def normalize_name(value: str) -> str:
    value = value.lower().replace("é", "e").replace("ó", "o").replace("á", "a")
    value = value.replace("ã", "a").replace("ç", "c")
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def extract_numbers(raw: str) -> List[str]:
    """Parse a Wikipedia cell into individual dialable numbers (no joining)."""
    if not raw:
        return []
    text = CITATIONS.sub("", raw)
    text = text.replace("\xa0", " ").strip()
    if not text or SKIP_VALUES.search(text):
        return []
    text = re.sub(r"\b(or|/|and)\b|,", ";", text, flags=re.I)
    parts: List[str] = []
    for chunk in text.split(";"):
        chunk = chunk.strip()
        chunk = re.sub(r"[^\d+\- ]+", "", chunk)
        chunk = re.sub(r"\s+", " ", chunk).strip()
        chunk = re.sub(r"(?<=\d) (?=\d)", "", chunk)
        if re.fullmatch(r"[+]?\d[\d\-]{1,18}", chunk) or re.fullmatch(r"\d{2,15}", chunk):
            parts.append(chunk)
        elif re.fullmatch(r"\d{2,6}-\d{2,8}", chunk):
            parts.append(chunk)
    unique: List[str] = []
    for part in parts:
        if part not in unique:
            unique.append(part)
    return unique


def normalize_numbers(raw: str) -> Optional[str]:
    """Compatibility helper: first extracted number only (never a joined list)."""
    numbers = extract_numbers(raw)
    return numbers[0] if numbers else None


def pick_service_number(numbers: List[str]) -> Optional[str]:
    """Prefer the service-specific number over a shared universal number."""
    if not numbers:
        return None
    specific = [num for num in numbers if num not in UNIVERSAL_NUMBERS]
    if specific:
        return specific[0]
    return numbers[0]


def pick_general_emergency(
    police_nums: List[str],
    ambulance_nums: List[str],
    fire_nums: List[str],
) -> Tuple[Optional[str], Optional[str]]:
    """Choose primary/alternate shared emergency numbers without combining them."""
    seen: List[str] = []
    for group in (police_nums, ambulance_nums, fire_nums):
        for num in group:
            if num in UNIVERSAL_NUMBERS and num not in seen:
                seen.append(num)
    # Prefer EU/GSM 112, then North-American 911, then 999/000/111.
    for preferred in UNIVERSAL_NUMBERS:
        if preferred in seen:
            rest = [num for num in seen if num != preferred]
            return preferred, (rest[0] if rest else None)
    # If every service cell shares one identical non-universal number, treat it
    # as the country default general emergency.
    flattened = [nums[0] for nums in (police_nums, ambulance_nums, fire_nums) if nums]
    if flattened and len(set(flattened)) == 1:
        return flattened[0], None
    return None, None


def classify_label(label: str) -> Optional[str]:
    label = label.lower()
    if "non-emergency" in label or "nonemergency" in label:
        return None
    if "suicide" in label or "lifeline" in label or "crisis" in label:
        return "suicide_helpline"
    if "women" in label or "domestic" in label:
        return "women_helpline"
    if "child" in label:
        return "child_helpline"
    if "disaster" in label or "civil defense" in label or "civil protection" in label:
        return "disaster_management"
    if "coast" in label or "maritime" in label or "sea rescue" in label:
        return "coastguard"
    if "tourist" in label:
        return "tourist_helpline"
    if "traffic" in label:
        return "traffic_police"
    if "gendarme" in label:
        return "gendarmerie"
    if "gas" in label:
        return "gas_leak"
    if label.startswith("police"):
        return "police"
    if label.startswith("ambulance"):
        return "ambulance"
    if label.startswith("fire"):
        return "fire"
    return None


def parse_notes(notes: str) -> Dict[str, str]:
    extras: Dict[str, str] = {}
    if not notes:
        return extras
    cleaned = CITATIONS.sub("", notes)
    for match in LABEL_NUMBER.finditer(cleaned):
        prefix = cleaned[max(0, match.start() - 24) : match.start()].lower()
        if "non-emergency" in prefix or "nonemergency" in prefix:
            continue
        key = classify_label(match.group("label"))
        numbers = extract_numbers(match.group("number"))
        if not key or not numbers or key in extras:
            continue
        # Notes often list one purpose → one number. If several are listed,
        # keep the service-specific digit and promote shared universals later.
        extras[key] = pick_service_number(numbers) or numbers[0]
        for num in numbers:
            if num in UNIVERSAL_NUMBERS and "general_emergency" not in extras:
                extras["general_emergency"] = num
                break
    return extras


def order_fields(values: Dict[str, str]) -> Dict[str, str]:
    ordered: Dict[str, str] = {}
    for key in PREFERRED_FIELDS:
        if key in values:
            ordered[key] = values[key]
    for key in sorted(values):
        if key not in ordered:
            ordered[key] = values[key]
    return ordered


def empty_country() -> Dict[str, Any]:
    return {"default": {}, "states": {}}


def build_default(police: Optional[str], ambulance: Optional[str], fire: Optional[str], notes: str) -> Dict[str, str]:
    """Build country-level contacts with one number per field (no joined strings)."""
    police_nums = extract_numbers(police or "")
    ambulance_nums = extract_numbers(ambulance or "")
    fire_nums = extract_numbers(fire or "")

    values: Dict[str, str] = {}
    police_value = pick_service_number(police_nums)
    ambulance_value = pick_service_number(ambulance_nums)
    fire_value = pick_service_number(fire_nums)
    if police_value:
        values["police"] = police_value
    if ambulance_value:
        values["ambulance"] = ambulance_value
    if fire_value:
        values["fire"] = fire_value

    general, alternate = pick_general_emergency(police_nums, ambulance_nums, fire_nums)
    if general:
        values["general_emergency"] = general
    if alternate:
        values["general_emergency_alternate"] = alternate

    extras = parse_notes(notes)
    for key, value in extras.items():
        if key in {"police", "ambulance", "fire"}:
            # Table columns win when present; notes fill gaps only.
            values.setdefault(key, value)
        elif key == "general_emergency":
            values.setdefault("general_emergency", value)
        else:
            values.setdefault(key, value)

    # If all three services already share one number and general is missing,
    # mirror that shared value as general_emergency.
    if (
        "general_emergency" not in values
        and police_value
        and police_value == ambulance_value == fire_value
    ):
        values["general_emergency"] = police_value

    return order_fields(values)


def load_iso_countries() -> Tuple[Dict[str, str], Dict[str, str]]:
    payload = json.loads(fetch(ISO_URL).decode("utf-8"))
    by_code: Dict[str, str] = {}
    by_name: Dict[str, str] = {}
    for row in payload:
        code = row["alpha-2"].upper()
        name = row["name"]
        by_code[code] = name
        by_name[normalize_name(name)] = code
    # Common ISO short-name variants.
    extra = {
        "united states of america": "US",
        "united kingdom of great britain and northern ireland": "GB",
        "korea republic of": "KR",
        "korea democratic people s republic of": "KP",
        "taiwan province of china": "TW",
        "bolivia plurinational state of": "BO",
        "venezuela bolivarian republic of": "VE",
        "iran islamic republic of": "IR",
        "moldova republic of": "MD",
        "tanzania united republic of": "TZ",
        "congo the democratic republic of the": "CD",
        "palestine state of": "PS",
        "holy see": "VA",
        "micronesia federated states of": "FM",
        "bonaire sint eustatius and saba": "BQ",
        "virgin islands british": "VG",
        "virgin islands u s": "VI",
        "svalbard and jan mayen": "SJ",
        "heard island and mcdonald islands": "HM",
        "united states minor outlying islands": "UM",
        "south georgia and the south sandwich islands": "GS",
        "lao people s democratic republic": "LA",
        "syrian arab republic": "SY",
        "russian federation": "RU",
        "viet nam": "VN",
        "cabo verde": "CV",
        "cote d ivoire": "CI",
        "turkiye": "TR",
        "turkey": "TR",
    }
    by_name.update(extra)
    for alias, code in NAME_ALIASES.items():
        by_name[normalize_name(alias)] = code
    return by_code, by_name


def resolve_code(name: str, by_name: Dict[str, str]) -> Optional[str]:
    return by_name.get(normalize_name(name))


def parse_wikipedia_rows() -> List[Tuple[str, Optional[str], Optional[str], Optional[str], str]]:
    parser = WikiTableParser()
    parser.feed(fetch(WIKI_URL).decode("utf-8", "replace"))
    rows = []
    for table in parser.tables:
        if not table:
            continue
        header = [normalize_name(cell) for cell in table[0]]
        if not header or "country" not in header[0]:
            continue
        for raw in table[1:]:
            if len(raw) < 4:
                continue
            country = re.sub(r"\s+", " ", raw[0]).strip()
            if not country or country.lower() == "country":
                continue
            police = (raw[1] if len(raw) > 1 else "").strip() or None
            ambulance = (raw[2] if len(raw) > 2 else "").strip() or None
            fire = (raw[3] if len(raw) > 3 else "").strip() or None
            notes = CITATIONS.sub("", raw[4] if len(raw) > 4 else "").strip()
            rows.append((country, police, ambulance, fire, notes))
    return rows


def build_dataset() -> Tuple[Dict[str, Any], List[str]]:
    iso_codes, by_name = load_iso_countries()
    dataset = {code: empty_country() for code in sorted(iso_codes)}
    unmatched: List[str] = []
    for country, police, ambulance, fire, notes in parse_wikipedia_rows():
        code = resolve_code(country, by_name)
        if not code:
            unmatched.append(country)
            continue
        if code not in dataset:
            unmatched.append(f"{country} ({code} not in ISO list)")
            continue
        default = build_default(police, ambulance, fire, notes)
        dataset[code]["default"] = default
        dataset[code]["states"] = {}
    dataset["IN"] = INDIA_EXAMPLE
    return dataset, unmatched


def _validate_contact_value(path: str, value: Any, errors: List[str]) -> None:
    if not isinstance(value, str):
        errors.append(f"{path} is not a string")
        return
    if ";" in value or re.search(r"\bor\b", value, re.I) or "/" in value:
        errors.append(f"{path} combines multiple numbers: {value!r}")
    if len(value) > 40:
        errors.append(f"{path} looks like descriptive text, not a dialable number: {value!r}")


def validate_dataset(data: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if not data:
        errors.append("dataset is empty")
        return errors
    for code, payload in data.items():
        if not re.fullmatch(r"[A-Z]{2}", code):
            errors.append(f"invalid country code {code!r}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"{code}: country value must be an object")
            continue
        if "default" not in payload or "states" not in payload:
            errors.append(f"{code}: missing default or states")
            continue
        if not isinstance(payload["default"], dict) or not isinstance(payload["states"], dict):
            errors.append(f"{code}: default and states must be objects")
            continue
        for key, value in payload["default"].items():
            _validate_contact_value(f"{code}.default.{key}", value, errors)
        for state_name, state in payload["states"].items():
            if not isinstance(state, dict):
                errors.append(f"{code}.states.{state_name} must be an object")
                continue
            for required in ("default", "cities", "zips"):
                if required not in state or not isinstance(state[required], dict):
                    errors.append(f"{code}.states.{state_name} missing {required} object")
            for key, value in state.get("default", {}).items():
                _validate_contact_value(f"{code}.states.{state_name}.default.{key}", value, errors)
            for city_name, city in state.get("cities", {}).items():
                if not isinstance(city, dict):
                    errors.append(f"{code} city {city_name} must be an object")
                    continue
                for key, value in city.items():
                    _validate_contact_value(f"{code} city {city_name}.{key}", value, errors)
            for zip_code, zip_row in state.get("zips", {}).items():
                if not isinstance(zip_row, dict):
                    errors.append(f"{code} zip {zip_code} must be an object")
                    continue
                for key, value in zip_row.items():
                    _validate_contact_value(f"{code} zip {zip_code}.{key}", value, errors)
    return errors


def default_output_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "datasets"
        / "cleaned"
        / "emergency_numbers.json"
    )


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate #333 emergency_numbers.json")
    parser.add_argument("--output", type=Path, default=default_output_path())
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    output = args.output.resolve()
    if args.validate_only:
        data = json.loads(output.read_text(encoding="utf-8"))
    else:
        data, unmatched = build_dataset()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        filled = sum(1 for row in data.values() if row.get("default"))
        print(f"Wrote {output}")
        print(f"Countries: {len(data)}; with at least one default number: {filled}")
        if unmatched:
            print("Unmapped Wikipedia rows (non-ISO or alias gap):")
            for name in unmatched:
                print(f"  - {name}")
    errors = validate_dataset(data)
    if errors:
        print(f"Validation failed ({len(errors)} issues):", file=sys.stderr)
        for error in errors[:40]:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("JSON structure is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
