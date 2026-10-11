# Beneficiary location resolution

Implements tasks 1–4 of issue #433 as injectable components in the existing aggregator.

`resolve_beneficiary_location(request_id, beneficiary_id, records)` uses an
injectable `LocationRecordSource`. A matching request/beneficiary association
is required. Missing requests or mismatched identities return `unresolved`.
Retrieval errors propagate to the caller.

Location precedence:

1. Valid request coordinates.
2. Valid beneficiary current coordinates.
3. Beneficiary profile address, returned as `requires_geocoding` without coordinates.

Coordinates must be finite, with latitude in [-90, 90] and longitude in
[-180, 180]. Valid zero is preserved. Malformed or incomplete pairs are rejected
without mixing sources. No viewer location, fabricated coordinates, or default
country is used.

## Local/test adapter

`LocalMockLocationRecordSource` accepts mock-generator rows. Explicitly call
`from_csv_directory(directory, synthetic_requests=rows)` to read `users.csv`,
`user_locations.csv`, `states.csv`, and `countries.csv`. No files are loaded on
import and the runtime handler does not select this adapter.

- `req_loc` and `user_locations.curr_loc` use
  `SRID=4326;POINT(longitude latitude)`, converted to `(latitude, longitude)`.
- Profiles use `addr_ln1/2/3`, `users.city_name`, and `zip_code` directly.
  State and country IDs resolve to lookup names; no cities join is required.
- Missing or malformed components and unresolved names are omitted. A conflicting
  state/country relationship does not add the wrong state. ZIP strings preserve
  leading zeros. Empty profiles yield no address.
- The generator has no requests table. Supply explicitly synthetic request
  fixtures with `request_id`, `beneficiary_id`, and optional `req_loc`.
  Examples are in `tests/fixtures/synthetic_requests.json`.
- Missing files/identity headers, missing row IDs, and duplicate IDs raise loading
  errors. CSVs are read only and never regenerated.

The mock contract was checked against locally cached `origin/main` generator
code and CSV headers, not a live database schema. The real database adapter and
runtime wiring remain task 5.

## Task 2: organization addresses

`OrganizationAddressAssembler(states=rows, countries=rows).from_database(row)`
uses the supplied mock generator contract:

`organizations.state_id -> states.state_id -> states.country_id -> countries.country_id`.

It joins available `street`, stored `city_name`, resolved `state_name`, `zip_code`,
and resolved `country_name`, in that order. Empty/malformed components and missing
lookups are omitted; raw IDs are never address components. ZIP strings retain
leading zeros. No cities join, city coordinates, country default, or organization
name is substituted. The generator is at
`data-analytics/mock-data-generation/generate_mock_data.py` in the locally cached
`origin/main` tree; it is inspected without executing it. Older schema metadata
under `database/` is not treated as the generator contract or live DDL.

`from_genai(row)` follows the supplied
`/Users/veerr_89/Downloads/SaayamOrgAggregatorHelper.txt`: records come from
`body.organizations`, and `location` is the supported location field. Only a
nonblank string is geocoding input. Structured address fields are not assumed.
An alternate future mapping must be explicitly injected via `location_reader`.
The live GenAI payload remains unverified; tests use clearly synthetic records.
The caller decodes the envelope before passing individual rows to this adapter.

Each adapter snapshots the organization fields in `OrganizationAddress.record`.
Missing/unusable addresses retain that record and add `distance: None` (JSON
`null`) and `distance_status: "unknown_location"`. Located records are retained
unchanged; distance calculation and full response enrichment belong to task 3.
`online_only` is an explicit optional caller classification, defaulting to
unclassified (`None`). No name, URL, location text, or source field is used to
guess it. Online distance status handling belongs to task 3.

## Task 2: injected geocoding and cache

`geocode_address(address, provider, cache)` is shared by beneficiary profile and
organization addresses. `geocode_beneficiary_profile(location, provider, cache)`
accepts only task 1's `requires_geocoding` / `profile_address` outcome; direct
coordinates and identity failures continue to be handled by task 1.

`GeocodingProvider.geocode` returns a `CoordinateRecord(latitude, longitude)` or
`None` for unmatched input. Provider adapters translate rate limits to
`GeocodingRateLimit`, timeouts to `TimeoutError`, and must enforce their own
network timeout. The resolver performs no automatic retries or sleeps.
`CoordinateCache.get` returns a record or `None`; `put` saves successful results.
Both dependencies are required; no provider or cache backend is selected here.

Cache keys trim only outer whitespace and otherwise preserve supplied text.
The cache is checked before provider calls. Valid cached pairs bypass the provider.
All cached/provider coordinates use task 1's finite/range validation, including
valid zero. Invalid cached pairs are treated as misses and replaced on success;
invalid provider pairs produce an error and are never saved. Only successful
provider results are cached, as normalized numeric coordinate pairs.

| Geocoding status | Meaning |
| --- | --- |
| `resolved` | Valid pair from `cache` or `provider` |
| `missing_location` | Absent/blank/unusable address; no dependency calls |
| `not_found` | Provider returned no match |
| `deferred` | Provider reported rate limit |
| `timeout` | Provider timed out |
| `error` | Provider failure or invalid returned coordinates |

Unavailable outcomes have no coordinates. Cache read failures permit provider
fallback. Cache write failures preserve successful coordinates, reporting
`cache_error: "write_error"`; read failures and invalid entries report
`read_error` and `invalid_coordinates`. Exception text is not returned. These
are geocoding outcomes, not the full distance-status mapping reserved for task 3.

`FakeGeocodingProvider` uses explicit configured address responses or exceptions;
unconfigured addresses are unmatched. `FakeCoordinateCache` records reads/writes
in instance-local memory. These fakes are explicitly constructed for local tests,
never selected by the Lambda handler. **The local fake cache does not prove
persistence across Lambda invocations.** Approved provider, persistent-cache
backend/configuration, key namespace, expiry, and operational policies remain
integration points. No live helper is imported by these components or their tests.

Run tests from the repository root with the existing venv:

```bash
venv/bin/python -m pytest data-engineering/tests -q
```

## Task 3: straight-line distance and offline aggregation

`organization_distance.straight_line_miles` uses the haversine formula on a sphere
with mean Earth radius 6371.0088 km, converted at 1.609344 km per mile. This is
straight-line distance, not road distance. The haversine term is clamped to [0, 1]
to protect antipodal calculations from floating-point drift. Coordinates use the
same validation as tasks 1–2. The calculation and serialized `distance` retain
full floating-point precision; no display rounding policy has been selected.

`AggregatorDependencies` composes the record source, resolver, provider, cache,
database-style organization source, GenAI-style organization source, and address
assembler. Source callbacks receive a copy of the request body; they can use
`category`, `subject`, `description`, and other explicitly supplied search fields.
They return lists of mappings or DataFrames. The GenAI callback may instead return
the attached helper's `statusCode` and `body.organizations` envelope, with `body`
as a mapping or JSON string. No remote helper or live client is imported in this
path. Explicitly supply dependencies to
`lambda_handler(event, context, dependencies=dependencies)` to use it.
The original two-argument handler retains its existing live path, now imported
lazily. Production wiring, database queries, real provider configuration, and
persistent caching remain task 5.

Offline requests require `request_id`, `beneficiary_id`, and `category`. Direct
body mappings and API Gateway JSON bodies are accepted. Beneficiary coordinates
are resolved once through tasks 1–2; arbitrary request `location` text cannot
replace that identity-bound resolution. A missing/mismatched beneficiary location
retains organizations with unavailable distance. Resolver retrieval errors map to
`error`, without leaking exception text.

Organization coordinates are used only through an explicitly injected
`coordinate_reader(OrganizationAddress) -> CoordinateRecord | None`. Returning
`None` uses the task 2 organization address and shared cache/geocoder. Invalid
injected coordinates map to `error`. Raw generator `latitude`/`longitude` are
never automatically read, since they may be city centroids. An explicitly
injected `online_reader(OrganizationAddress)` classifies online-only organizations;
only `True` produces `online`. No classification is inferred from names or URLs.

| `distance_status` | `distance` and meaning |
| --- | --- |
| `ok` | Finite, unrounded miles, including valid `0.0` |
| `online` | `null`; explicitly classified online-only |
| `unknown_location` | `null`; organization address/coordinates or beneficiary location unavailable |
| `not_found` | `null`; beneficiary or organization address unmatched |
| `deferred` | `null`; beneficiary or organization geocoder rate-limited |
| `error` | `null`; timeout, invalid coordinates, resolver failure, or organization enrichment failure |

Online classification takes precedence. Otherwise missing organization location
produces `unknown_location`; if beneficiary resolution failed, its status applies
to located organizations and unnecessary organization geocoding is skipped.
Each response record also has `distance_unit: "miles"` and
`distance_method: "straight_line"`, including unavailable outcomes.

The attached helper's consumer fields are retained: `name`, `organization_type`,
`collaborator`, `location`, `size`, `rating`, `contact`, `email`, `web_url`, `mission`,
and `source`. Existing consumer names win over raw aliases. Database `org_name`,
`org_type`, `is_collaborator`, `org_size`, `org_rating`, `phone`, and `city_name`
and GenAI `organization_name`, `org_type`, and `is_collaborator` are normalized.
Missing consumer fields become `null`, except that GenAI records without either
collaborator field retain the attached helper's `false` default. Explicitly supplied
collaborator values are preserved. Additional source fields, including
`Representatives`, are retained. Original records are not mutated.

Sources are retrieved independently, sequentially in the offline composition.
A failing/invalid GenAI envelope retains database results; a failed DB source also
allows AI records through. Source failures log only the source label. Two failed
sources return 502; valid empty source results return an empty list with 200.
Per-organization address, classification, and coordinate-reader failures retain
that organization with `error` and allow subsequent records to continue.
Malformed non-record entries are skipped individually; valid organizations in the
same source are retained. Invalid source containers still count as source failures.
Serialization uses `allow_nan=False`, converts nonfinite numeric fields and
DataFrame missing values to JSON `null`, and preserves zeros/false values.
Date, datetime, and pandas Timestamp values serialize as ISO strings, preserving
supplied timezone offsets. An unsupported or circular field becomes `null` without
discarding its organization or other records; its valid distance remains available.
Serialization warnings contain no field values or exception text.

### Runnable offline example

From the repository root (all inputs below are explicitly synthetic):

```bash
PYTHONPATH=data-engineering/src/saayam-org-aggregator venv/bin/python - <<'PY'
import json
from lambda_function import lambda_handler
from address_geocoding import CoordinateRecord
from local_geocoding import FakeCoordinateCache, FakeGeocodingProvider
from local_location_records import LocalMockLocationRecordSource
from offline_aggregator import AggregatorDependencies

records = LocalMockLocationRecordSource(synthetic_requests=[{
    "request_id": "synthetic-request", "beneficiary_id": "synthetic-beneficiary",
    "req_loc": "SRID=4326;POINT(0 0)",
}])
dependencies = AggregatorDependencies(
    records=records,
    provider=FakeGeocodingProvider({
        "Synthetic City": CoordinateRecord(0, 1),
        "Synthetic Address": CoordinateRecord(0, 0),
    }),
    cache=FakeCoordinateCache(),
    db_source=lambda body: [{
        "org_name": "Synthetic DB", "org_type": "NGO", "is_collaborator": False,
        "city_name": "Synthetic City", "org_size": 0, "org_rating": 4,
    }],
    ai_source=lambda body: {"statusCode": 200, "body": {"organizations": [{
        "organization_name": "Synthetic AI", "organization_type": "Charity",
        "collaborator": False, "location": "Synthetic Address", "size": 2, "rating": 0,
    }]}},
)
response = lambda_handler({
    "request_id": "synthetic-request", "beneficiary_id": "synthetic-beneficiary",
    "category": "Synthetic category",
}, None, dependencies=dependencies)
print(json.dumps(json.loads(response["body"]), indent=2, allow_nan=False))
PY
```

`tests/test_organization_distance.py` verifies the helper field contract after
Lambda serialization, spherical benchmarks (equator, NYC–London, antimeridian,
antipodes), identical coordinates, all six statuses, both list/frame sources,
reference mock address relationships, all beneficiary fallbacks, cache reuse,
explicit coordinates, failure isolation, strict serialization, and import safety.
These checks prove the supplied helper contract offline; they do not prove live
provider behavior or frontend integration. Future PR base is `test`; no commit,
push, PR, task 5, or deployment is part of this change.

## Task 4: offline runner and consumer verification

`AggregatorDependencies.request_info_reader(request_id, beneficiary_id)` is an
optional injected callback returning `category`, `subject`, and `description`.
With it selected, the handler accepts the attached handler's IDs-only input,
either directly or inside an API Gateway JSON `body`. Retrieved request details
take precedence over caller search fields. The callback must verify the association
before returning details. `LocalMockLocationRecordSource.get_request_info` checks
the synthetic request's beneficiary and reads these explicitly synthetic fixture
fields. The generator has no requests table; these fields do not establish live DDL.
Missing/mismatched details return 400; unexpected lookup failures return 500, with
an `error` JSON object and no dependency exception text. A missing category returns
400. Without this callback the existing explicit-category offline input still works.
The lower-level `aggregate_organizations` receives an already prepared request body.
The offline handler normalizes integer IDs to strings and trims surrounding
whitespace on string IDs once, before both details lookup and location resolution.
Booleans, floats, containers, and blank/missing IDs return 400. Caller inputs are
not mutated. This normalization does not change the deployed default handler.

`local_aggregator_runner.build_local_dependencies` explicitly reads `users.csv`,
`user_locations.csv`, `states.csv`, `countries.csv`, and `organizations.csv` from
the selected directory. It composes both organization adapters, synthetic requests,
fake geocoder, and instance-local cache. The local sources retain the supplied
organization rows: search filtering and pagination are not simulated.
Known organization CSV types are decoded at the local source boundary:
`is_collaborator` true/false text becomes a JSON boolean, and `org_rating` becomes
a finite JSON number. Blank or malformed values become null, including nonfinite
ratings. IDs, ZIP codes (including leading zeros), and textual sizes stay strings.
CSV files are never rewritten.
The deployed two-argument handler retains its previous data source and behavior;
it never selects this runner or loads local CSVs automatically.

The CLI requires every input path, performs no generation, writes no output files,
and prints the existing API response envelope to stdout. For example, after
preparing synthetic inputs in a disposable directory outside the checkout:

```bash
venv/bin/python data-engineering/src/saayam-org-aggregator/local_aggregator_runner.py \
  --mock-directory /tmp/saayam-synthetic \
  --requests /tmp/saayam-synthetic/requests.json \
  --ai /tmp/saayam-synthetic/ai.json \
  --geocodes /tmp/saayam-synthetic/geocodes.json \
  --event /tmp/saayam-synthetic/event.json
```

- `requests.json`: `{"requests": [{"request_id": "r", "beneficiary_id": "b",
  "category": "Food", "subject": "Synthetic", "description": "Synthetic",
  "req_loc": "SRID=4326;POINT(0 0)"}]}`. The existing
  `tests/fixtures/synthetic_requests.json` illustrates location cases; add synthetic
  search details when using those fixtures with this runner.
- `ai.json`: organization list or the helper's `statusCode/body.organizations`
  envelope. An explicitly supplied boolean `online_only: true` classifies a local
  synthetic AI record as online-only; no text-based heuristic is used.
- `geocodes.json`: address keys mapped to `{"latitude": 0, "longitude": 1}`,
  `null` (unmatched), or the synthetic labels `"deferred"`, `"timeout"`, `"error"`.
  Unknown addresses are unmatched. These values are test responses, not a provider API.
- `event.json`: `{"request_id": "r", "beneficiary_id": "b"}` or
  `{"body": "{\"request_id\":\"r\",\"beneficiary_id\":\"b\"}"}`.

Never run the generator in a directory containing user datasets. This workflow
does not run it at all. Integration tests write invented CSV/JSON inputs only to
pytest temporary directories. Temporary datasets, screenshots, and captured output
belong outside Git (or in the existing locally excluded `.validation/` directory).

### Ordering and rendering contract

`organization_distance.nearest_first(records)` returns a stable sorted list without
mutating the input. Finite nonnegative numeric distances with `distance_status: "ok"`
sort ascending, with valid zero first. Null, negative, nonfinite, string, boolean,
and unavailable-status distances sort last. Equal distances and unavailable records
retain their original relative order. The normal aggregator keeps source order.
The CLI's `--nearest-first` option applies the helper only to its local response.
Live pagination and sorting require a confirmed backend/frontend contract first;
sorting one page alone would not establish global nearest-first ordering.

Frontend consumers should render a positive available distance as **`<value> mi`**,
valid zero as **`0 mi`**, and every unavailable distance as **`N/A`**. Check status
and null explicitly instead of testing distance truthiness. The API retains numeric
miles and full precision; frontend rounding precision still needs agreement.
Keep rows and existing contact/representative fields visible during partial failures.

`tests/test_offline_aggregator_integration.py` exercises the actual injected handler
and CLI with generator-shaped temporary files: IDs-only direct/Gateway inputs,
request association, trusted details, request/current/profile precedence, full
profile and organization addresses, both sources, shared cache reuse, all six
distance statuses, source/record/cache failures, stable sorting, and default-handler
separation. These are **component integration and consumer-contract tests**.
No frontend component or browser UI is present in this test path, so rendering,
layout, and user interaction have **not** been verified in the actual UI.

Run the components and existing analytics regressions together:

```bash
PYTHONPATH=data-engineering venv/bin/python -m pytest data-engineering/tests -q
```

Remaining dependencies: confirmed live request/beneficiary and organization schema,
database/GenAI adapters and payload validation, approved geocoding provider and
network timeouts, persistent cache backend/namespace/expiry, online-only classification,
runtime wiring, frontend acceptance of IDs and distance fields, rendering/rounding
implementation and browser verification, and a confirmed pagination/sorting contract.
Local cache reuse proves reuse of one injected instance, not cross-invocation persistence.
Task 5 remains unstarted.
