
# Task #578 - Request Location Conversion

## Objective
Convert hexadecimal request locations (req_loc)
into readable POINT(longitude latitude) coordinates.

## Implementation
The location_converter.py file contains the
convert_req_loc() function.

It:
- Converts WKB/EWKB hexadecimal POINT locations.
- Preserves longitude and latitude order.
- Supports 2D POINT geometry.
- Handles null and invalid inputs.
- Uses Python standard libraries only.

## Invalid Input Handling
Null, empty, malformed, or unsupported locations
return an empty string.

When exported to CSV, this becomes an empty field.

## Testing
Run:
python data-engineering/request_location_578/test_location.py

Generate comparisons:
python data-engineering/request_location_578/generate_comparison.py

## Local Results
7 out of 7 synthetic tests passed.

Expected and actual outputs matched.

## Evidence
- comparison_results.csv
- comparison_screenshot.png

## Integration Status
The conversion function is implemented and locally tested.

Integration with the request archive export is not yet
completed. The export must apply convert_req_loc()
to req_loc when writing CSV rows.

Official maintainer-provided mock data has not yet
been validated.
