
# Request Location Conversion — Issue #578

## Overview

This implementation converts hexadecimal WKB/EWKB request-location
values (`req_loc`) into readable Well-Known Text (WKT) format:

`POINT(longitude latitude)`

The converter is intended to support request-data archival from
RDBMS to S3.

## Implementation

File: `location_converter.py`

Function: `convert_req_loc(value)`

Features:
- Supports standard 2D WKB and EWKB POINT geometries.
- Supports little-endian and big-endian byte ordering.
- Handles EWKB values containing an SRID.
- Preserves longitude-first, latitude-second coordinate ordering.
- Preserves round-trippable Python double-precision values.
- Returns `None` for null, empty, malformed, unsupported, or
  non-finite geometry inputs.
- Accepts hexadecimal strings with optional `0x` or `\x` prefixes.

The converter does not connect to AWS or a database.

## Automated Unit Tests

Run from the repository root:

```powershell
python -m unittest discover -s .\data-engineering\src\request_location_conversion -p "test_*.py" -v
```

Local verification result: **12 tests passed**.

## Synthetic Mock-Data Comparison

Run from the repository root:

```powershell
python .\data-engineering\src\request_location_conversion\generate_comparison.py
```

Local verification result: **8 of 8 comparisons passed**.

Generated evidence:

- `evidence/comparison.csv` — mock input, expected output,
  actual output, and PASS/FAIL status.
- `evidence/converted_requests.csv` — sample converted request export.

The comparison includes valid locations, high-precision coordinates,
different byte orders, null values, and invalid hexadecimal input.

All eight synthetic request records were preserved in the sample export.

## Invalid Location Handling

Invalid or null location values are converted to `None`.

The demonstration CSV export writes these values as empty fields
without dropping the corresponding request records.

## Scope and Limitations

- All tests use locally generated synthetic data.
- No production database or AWS resources were accessed.
- Integration with the actual request-archiving pipeline has not
  yet been tested.
- The complete maintainer-provided mock dataset has not yet been
  verified against this implementation.
- Geographic coordinate range validation is not enforced; finite
  coordinate values are preserved as encoded.

## Files

- `location_converter.py` — reusable geometry conversion function.
- `test_location_converter.py` — automated unit tests.
- `generate_comparison.py` — synthetic comparison generator.
- `evidence/comparison.csv` — expected-versus-actual evidence.
- `evidence/converted_requests.csv` — demonstration export.
