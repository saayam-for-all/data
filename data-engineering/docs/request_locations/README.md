# Request location conversion (#578)

## Purpose

Convert the archived `requests.req_loc` value from PostGIS WKB/EWKB
hexadecimal text into readable WKT:

```text
POINT(longitude latitude)
```

The converter is implemented in
`src/utils/request_location.py` and uses only the Python standard library.

## Conversion contract

- Longitude remains the first coordinate and latitude remains the second.
- Coordinate precision is preserved using a round-trippable float
  representation.
- Little-endian and big-endian WKB are supported.
- EWKB SRID, Z, and M metadata are accepted; the readable export contains
  longitude and latitude only.
- Hexadecimal strings with optional `\x` or `0x` prefixes are accepted.
- Binary values from database drivers and already-readable `POINT` values are
  also accepted.

## Null and invalid values

Null, blank, malformed, unsupported, non-finite, or out-of-range locations
produce an empty `req_loc` value. They do not raise an exception and do not
remove the request row from the export.

## Local verification

From the repository root with the project virtual environment active:

```bash
PYTHONDONTWRITEBYTECODE=1 python data-engineering/scripts/compare_request_locations.py

cd data-engineering
PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  -p no:cacheprovider \
  tests/test_request_location.py -q
cd ..
```

The comparison command uses fixed local fixtures only. It does not require a
database, AWS credentials, or network access.

## Evidence

The comparison command writes:

- `docs/request_locations/evidence/comparison.csv`: mock input, expected
  output, actual output, and pass/fail result.
- `docs/request_locations/evidence/converted_requests.csv`: retained request
  rows with their final readable or empty `req_loc` value.

The checked-in fixture set covers normal WKB, big-endian WKB, EWKB with SRID,
EWKB with Z, high-precision coordinates, already-readable values, null values,
malformed data, non-point geometry, and out-of-range coordinates.
