# Request location conversion (#578)

Converts `requests.req_loc` from PostGIS hex into readable `POINT(longitude latitude)`.

- Code: `src/utils/request_location.py` (`hex_to_wkt`)
- Mock inputs and expected outputs: `tests/fixtures/request_locations/cases.json`
- Tests: `tests/test_request_location.py` (14 pass)
- Comparison: `scripts/compare_request_locations.py` writes `evidence/comparison.csv`

## Example

`0101000020E6100000AAF1D24D628052C05E4BC8073D5B4440` -> `POINT(-74.006 40.7128)`

## Format

- Longitude first, then latitude, exactly as stored.
- Numbers keep full double precision, with no trailing zeros (`0.0` is written `0`).
- Accepted input: EWKB with SRID, plain WKB, little- or big-endian,
  upper or lower case, with or without a `\x` prefix.

## Null and invalid input

`hex_to_wkt` never raises. It returns an empty string for:

| Input | Output |
|---|---|
| `None` or blank | empty |
| Not hex, such as free text like `Suffolk, VA` | empty |
| Truncated or too-short hex | empty |
| Not a POINT geometry | empty |
| NaN coordinates | empty |
| Longitude outside -180..180 or latitude outside -90..90 | empty |

The export writes the empty string as an empty CSV field, so the request row is
kept and the export does not fail.

## Evidence

Screenshots and the comparison CSV are in `evidence/`.