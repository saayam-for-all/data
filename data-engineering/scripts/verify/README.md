# verify_archive.py

Checks an exported archive file against the source database. Issue #586.

```
source ~/saayam.env
python3 scripts/verify/verify_archive.py                  # newest successful run
python3 scripts/verify/verify_archive.py --key backup/... # a specific object
```

Needs `psql` and the `PG*` environment variables. No pip installs, it uses only
the standard library. Everything it does is read only.

## What it checks

- row count in the file matches the source for that window
- row count matches what `archive_run_log` recorded
- no duplicate request ids in the file
- every source row is present in the file
- the file contains no row that is not in the source
- every field of every row matches the source, not a sample
- every joined label matches what its lookup table actually says

It also reports how many null and unmatched references each join had, since
those are the rows an inner join would have dropped.

## Why it does not reuse the exporter's query

It rebuilds the expected file from the raw tables and the lookup tables
separately. Re-running the exporter's own SQL would only prove the exporter
agrees with itself, which is how a wrong join or a shifted column survives a
test suite. This is the same reason counts alone are not enough: a row shifted
by one column keeps the count correct and makes every value wrong.

## It has been tested against failures

Before it was used, five faults were injected into a known-good file and all
five were caught:

| injected | caught by |
|---|---|
| a row deleted | row count, and every source row present |
| a row duplicated | row count, and no duplicate ids |
| one field changed | field comparison |
| one label changed | label comparison |
| a whole row shifted one column | source row present, and no invented rows |

## Comparing values, not representations

`psql` and Python render some values differently and neither is wrong, so the
comparison normalises two cases before comparing:

- booleans, `t` and `f` from psql against `True` and `False` from the csv writer
- fractional seconds, psql strips trailing zeros where Python pads to six digits

Both were found by running this against real output. Nothing else is
normalised, so a genuine difference still fails.

## Result against the live archive

17 November 2026, 240 rows, all seven checks passed. 5280 field values and 1440
labels compared.
