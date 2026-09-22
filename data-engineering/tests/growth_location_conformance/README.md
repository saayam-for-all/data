# Growth & Location Analytics Conformance Checker (#336)

A standalone spec checker for [issue #336](https://github.com/saayam-for-all/data/issues/336)
(Growth & Location Analytics API). It is **not** part of any one candidate
PR's implementation -- several people submitted independent implementations
for #336, and this tool exists to check any of them (or a future
implementation) against the same rules on equal footing.

It encodes:

- The issue's written spec (five top-level buckets, `total_organizations` as
  an all-time running total vs. `collaborators` as window-scoped, daily vs.
  monthly bucketing, sparse arrays, top-4 countries with no "Other"/percentage
  field, independent Custom date pairs).
- The team lead's rulings from the #336 WhatsApp thread (2026-09-21):
  - Supplying only one of a `start_date`/`end_date` pair (or
    `location_start_date`/`location_end_date`) must be a 400, not a
    partial/empty result.
  - `"1Y"` means trailing 12 **calendar months**, not a rolling 365 days.
  - `country.csv`/`state.csv` must be internally consistent. The CSVs
    circulated for #336 have every US state pointing at `country_id=1`,
    which is Afghanistan in `countries.csv`, not the USA. Build your own
    corrected test CSVs -- `fixtures.py` in this package already does.

## Quick start: check your own implementation

```bash
cd data-engineering
python -m tests.growth_location_conformance.conformance \
    --impl path/to/your/lambda_function.py \
    --entry lambda_handler
```

This writes fixture CSVs to `<your-impl-dir>/mock_data/` and also sets the
`MOCK_DATA_DIR` environment variable to that path, to cover both
conventions seen across the open #336 PRs (some read `MOCK_DATA_DIR`, some
hardcode a `mock_data/` folder next to the handler file). Pass `--mock-dir`
to override.

## Using it as a library

```python
from tests.growth_location_conformance import conformance

def call(event):
    result = my_lambda_handler(event, None)
    body = result["body"]
    if isinstance(body, str):
        body = json.loads(body)
    return result["statusCode"], body

report = conformance.run_conformance(call, mock_dir="/tmp/my_mock_data")
conformance.print_report(report)
```

`R12` (the response `body` must be a JSON *string*, per the API Gateway
proxy-integration contract) has to be checked against the raw handler
return value, since the adapter above already unwraps JSON for the other
rules -- see the CLI's `main()` for the two-line pattern.

## Files

| File | Purpose |
|---|---|
| `fixtures.py` | Builds a shared mock dataset with deliberate edge cases: a gap month (sparse-array check), five countries (top-4 truncation check), and a recency ladder straddling the 7D/30D/1Y boundaries. |
| `oracle.py` | Independent expected-value calculator, computed directly from the raw fixture data -- not derived from any candidate implementation -- used as the ground truth for R4-R7. |
| `conformance.py` | The rule checks (R1-R12) plus a CLI for pointing them at any implementation. |
| `test_self_check.py` | Pytest suite validating the fixture/oracle are internally consistent. Runs standalone, no candidate implementation required. |

## What this does *not* do

It does not pick a winner among the #336 PRs, and it is not wired into any
of them. Once the team settles on an implementation, whoever owns that PR
can run this against it (or fold `test_self_check.py`'s pattern into their
own PR's test suite) as part of getting it merge-ready.
