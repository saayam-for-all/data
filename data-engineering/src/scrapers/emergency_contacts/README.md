# Emergency contacts: issue #333

## Current deliverable: numbers separated by purpose

Use `data-engineering/datasets/cleaned/emergency_numbers.json` for the next step.
The September 22 update supersedes the earlier one-number-per-country request.
It contains **249 ISO alpha-2 country/territory keys and 1,024 sourced contacts**,
including **40 regional entries and 37 city entries**. The initial collection was
reviewed on **2026-09-15**; the multiple-number review is dated **2026-09-22**.
Each contact value is one phone-number string. Metadata stays in the separate
`emergency_numbers_provenance.json` file.

For example, Austria retains separate purposes:

```json
{
  "general_emergency": "112",
  "police": "133",
  "ambulance": "144",
  "fire": "122"
}
```

Service/provider fields distinguish, for example, `ambulance_edhi` in Pakistan,
`medical_emergency` from ambulance dispatch in Curacao, and police response from
`emergency_information` in Sri Lanka. Network restrictions use fields such as
`general_emergency_mobile` and `ambulance_local_sim`. Municipal numbers remain
inside their reviewed state/city.

When the reviewed source explicitly publishes alternatives for the same service,
use `<service>_alternate` and, when needed, `<service>_alternate_secondary`.
These mean additional published routes for that same purpose; they do not imply
priority, a different provider, or a mobile-only restriction. A published full
telephone number beside a short code uses `<service>_full_number`.
Do not manufacture purposes, numbered keys such as `police_1`, or split prose
into contact fields. Consumers should treat these as explicit service fields;
there is no new array or nested-value type for Lambda to interpret.

**Review status:** the audit accounts for **190 distinct country-number
candidates**: **168 mapped**, **4 superseded**, **1 non-emergency**, and
**17 needing verification**. The latter remain outside the contact export.
Their individual source links and reasons are in `number_review` in provenance;
`number_review_decisions.json` preserves the research decisions. Examples include
Gabon network-specific medical codes whose network mappings are unknown, and
Lao police-station numbers lacking confirmed locations/prefixes. This is a
structured reviewed release, not a claim that worldwide verification is complete.

## Legacy single-number export

`emergency_numbers_single.json` remains an optional legacy output. It selects
national `general_emergency`, then national `police`, otherwise an empty string.
It omits additional numbers and restrictions, so it is **not the deliverable for
the updated requirement**. Rebuild it and its source audit with:

```sh
python data-engineering/src/scrapers/emergency_contacts/build_single_numbers.py
```

## Build and validate

Run from the repository root:

```sh
python data-engineering/src/scrapers/emergency_contacts/build_emergency_numbers.py
python -m pytest data-engineering/tests/test_emergency_numbers_json.py data-engineering/tests/test_emergency_contacts_pipeline.py data-engineering/tests/test_emergency_single_numbers.py -q -p no:cacheprovider
```

The build is offline and uses the collected CSV and `contact_overrides.json`.
Install `data-engineering/requirements.txt` for dependencies. The output and
provenance must be regenerated together; do not edit the output JSON alone.

Optional collection tools:

```sh
python data-engineering/src/scrapers/emergency_contacts/scraper.py
python data-engineering/src/scrapers/emergency_contacts/collect_government_sources.py
```

The first refreshes the secondary research table. The second caches missing
FCDO country documents under the ignored raw-data directory. Neither certifies
new contacts. Review the service, number and geographic/telephone restrictions
before adding a dated, sourced record to `contact_overrides.json`.

## Source policy

The final export contains only contacts checked against a cited publication:

| Provenance status | Exported contacts | Meaning |
| --- | ---: | --- |
| `official_or_service_operator` | 220 | Government authority, health service or service operator publication |
| `government_guidance` | 804 | Government travel guidance, WHO implementation guidance, or national-authority reports in the ITU registry |
| `secondary_source` | 0 | Research material only; withheld from the default export |

These categories are deliberately separate. Government travel guidance and
reported number assignments do not constitute direct confirmation from each
local operator. Publication dates and material service restrictions are retained
in provenance notes; ITU records also have `source_updated_on`.

Local authority/operator evidence takes precedence when sources conflict.
Examples include Malaysia's consolidated 999 service, Cameroon's mobile versus
landline numbers, and The Gambia's regulator-published service numbers.

The research CSV was collected from the
[Wikipedia list, revision 1373696077](https://en.wikipedia.org/w/index.php?title=List_of_emergency_telephone_numbers&oldid=1373696077).
See Wikipedia's [reuse terms](https://en.wikipedia.org/wiki/Wikipedia:Reusing_Wikipedia_content).
The original notes and ambiguous cells remain in the audit. A secondary number
cannot enter the final export without a reviewed source record. The explicit
`verified_only=False` builder option is for research and parser tests only.

## Hierarchy and dialing rules

- Every country has `default` and `states` objects.
- Every regional entry has `default`, `cities` and `zips` objects.
- City and postal-code entries contain service-to-string mappings directly.
- Phone numbers remain strings, including leading zeros and international `+`.
- A regional contact is omitted when its reviewed parent already supplies the
  same number. Unreviewed national data cannot suppress a reviewed local entry.
- Region names represent applicable administrative or island divisions. Station
  contacts, such as McMurdo, remain scoped to their island and station.
- No distinct postal-code service was established in this collection. All `zips`
  objects remain `{}`; national numbers are not copied into arbitrary ZIP codes.
- Keys such as `police_mobile`, `police_landline`, `general_emergency_netone`,
  and `emergency_medical_after_hours` retain restrictions that the required
  string-only JSON cannot otherwise express. Language-specific helplines use
  suffixes such as `_dutch` and `_finnish`.
- The normalizer accepts only a single unqualified number. Alternatives, prose,
  extensions and optional trunk prefixes require review; no first-number fallback
  is allowed. Formatting is removed without truncating full telephone numbers.

## Coverage and empty entries

All 249 ISO country/territory codes are represented. Eight entries have no
suitable exported contact: **BV, GS, HM, KP, PN, SS, TF and UM**. Each has a dated
research explanation and source links in `coverage_notes.json`, also included
in the generated `country_coverage` audit. For example, South Sudan's reported
number assignments conflict with current operational travel guidance; those
numbers are withheld. Empty objects mean no suitable collected contact, not
proof that no service exists.

Other entries have regional contacts without a national default. Examples:

- Antarctica: McMurdo fire and medical dispatch only.
- DR Congo: Kinshasa police and fire only.
- Saint Helena, Ascension and Tristan da Cunha: separate island contacts.
- Svalbard and Jan Mayen: the verified Svalbard contact is not assumed to cover
  Jan Mayen.
- Greenland: nationwide police contact plus town-specific acute medical contacts,
  including different after-hours numbers where published.

The collected specialist services include suicide/crisis, women's protection,
child protection, disaster management, rescue and other explicitly named
services. Geographic, network and service limitations are part of the source
review. This release does not certify an exhaustive inventory of every local
service or live operational availability.

## Audit and acceptance checks

`emergency_numbers_provenance.json` records every exported contact's path,
number, URL, review date, source class and explanation, plus:

- SHA-256 checksums of the collected CSV, curated contacts and number-review decisions;
- every ambiguous number candidate, its reviewed field/location mappings or a
  withholding decision, plus unresolved-count totals;
- withheld secondary contacts, malformed/ambiguous cells and original notes;
- coverage and source URLs for every ISO code;
- national and regional coverage, empty entries and source-class totals.

The current validation run passed **61 tests**. The tests check independent ISO membership, duplicate JSON keys, complete
hierarchy, string values, source provenance, reproducible builds, source
precedence, scoped corrections and scraper regressions. They do not place
calls. The ISO reference is the factual
[pycountry ISO database](https://raw.githubusercontent.com/pycountry/pycountry/main/src/pycountry/databases/iso3166-1.json);
tests use a separately saved code list rather than deriving expected coverage
from the output.

The issue's requested work is data collection and JSON preparation. This change
includes no S3, database, Lambda, API or UI implementation. GitHub review and
issue closure are separate from producing the local data files.
