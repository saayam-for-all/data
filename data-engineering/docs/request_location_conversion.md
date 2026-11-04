# Request location conversion

`src/utils/request_location.py` converts hexadecimal PostGIS WKB/EWKB POINT
values to `POINT(longitude latitude)` text for readable exports.

```python
from src.utils.request_location import convert_req_loc

convert_req_loc("0101000020e6100000aaf1d24d628052c05e4bc8073d5b4440")
# "POINT(-74.006 40.7128)"
```

The converter supports either byte order, EWKB SRID flags, and 2D/3D/4D
point encodings. It takes the first two ordinates in their stored order and
preserves their floating-point values. It returns `None` for null, empty,
malformed, non-finite, or unsupported geometry values. An exporter can write
that result as an empty CSV field without dropping the request row.

Run the mock comparison locally from `data-engineering/`:

```sh
python -m scripts.compare_request_locations
python -m pytest tests/test_request_location.py
```

The script writes actual outputs and pass/fail comparisons to
`docs/request_location_comparison.csv`. These examples are synthetic mock
inputs; no database or AWS resources are used. The repository does not yet
contain a request archive export workflow to wire this utility into, and the
complete maintainer-provided mock dataset has not been supplied.

The generated comparison currently contains:

| Mock input | Expected | Actual | Match |
|---|---|---|---|
| New York EWKB with SRID | `POINT(-74.006 40.7128)` | `POINT(-74.006 40.7128)` | Yes |
| Rome little-endian WKB | `POINT(12.4964 41.9028)` | `POINT(12.4964 41.9028)` | Yes |
| Dateline big-endian WKB | `POINT(179.5 -16.25)` | `POINT(179.5 -16.25)` | Yes |
