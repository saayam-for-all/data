# Beneficiary location resolution

Implements task 1 of issue #433 in the existing aggregator.

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
runtime wiring remain task 5; geocoding remains task 2.

Run tests from the repository root with the existing venv:

```bash
venv/bin/python -m pytest data-engineering/tests -q
```
