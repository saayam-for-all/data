# Beneficiary location resolution

Implements tasks 1–2 of issue #433 as independent components in the existing aggregator.

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
