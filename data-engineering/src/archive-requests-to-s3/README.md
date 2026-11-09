
# Request Location Conversion — Issue #578

## Overview

This utility converts hexadecimal WKB/EWKB POINT geometries from
the `req_loc` field into readable coordinates:

`POINT(longitude latitude)`

It is intended to support the request-data archival workflow.

## Implementation

File: `location_converter.py`

Function: `convert_location(value)`

The converter:

- Accepts hexadecimal WKB and EWKB POINT values.
- Supports little-endian and big-endian byte ordering.
- Supports EWKB values containing an SRID.
- Preserves longitude-first, latitude-second coordinate ordering.
- Returns an empty string for null, empty, malformed, unsupported,
  non-finite, or out-of-range coordinate inputs.
- Rejects non-POINT geometries and 3D/measured POINT geometries.
- Does not require a database connection or AWS credentials.

For invalid inputs, the intended CSV representation is an empty field.
The converter itself returns an empty string rather than raising an error.

## Local Testing

Run the unit tests from the repository root:

```powershell
python .\data-engineering\src\archive-requests-to-s3\test_location_converter.py
```

Run the mock-data comparison:

```powershell
python .\data-engineering\src\archive-requests-to-s3\generate_comparison.py
```

## Test Evidence

The comparison script generates:

`evidence/comparison.csv`

This file includes:

- Synthetic request IDs
- Mock hexadecimal location inputs
- Independently specified expected outputs
- Actual converter outputs
- PASS/FAIL results

The local comparison completed successfully with **12/12 PASS**.

A screenshot is available at:

`evidence/comparison-results.png`

The separate unit test suite also completed successfully with
**6/6 tests passing**.

## Null and Invalid Input Handling

| Input condition | Converter output |
|---|---|
| Null or empty | Empty string |
| Invalid hexadecimal | Empty string |
| Incomplete binary geometry | Empty string |
| Non-POINT geometry | Empty string |
| Out-of-range coordinates | Empty string |
| Valid supported POINT | `POINT(longitude latitude)` |

## Scope and Limitations

All comparison fixtures are synthetic. The full maintainer-provided
mock dataset has not yet been received or validated.

This implementation is a standalone conversion utility.
It has **not yet been integrated into the existing PostgreSQL-to-S3
export process**. Consequently, the tests demonstrate local conversion
behavior, not successful end-to-end S3 archival.

The converter formats floating-point coordinates with up to 17
significant digits to preserve their binary double-precision values.
Some decimal coordinates may therefore display additional digits.

No existing SQL archival implementation was modified as part of
this standalone utility.
