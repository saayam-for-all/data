# Requests archival: design notes

These are the decisions behind the backup export and why they were made, for
whoever picks this up next. The README next to it covers how to run it.

## Two stages, not one

The archive has to do two jobs that pull in opposite directions. It is our
backup, so it has to be complete, and anything stripped out of it is gone for
good once rows start being deleted from Aurora. It is also going to be shared
with stakeholders, so it has to have personal data removed.

One file cannot be both. So there are two stages:

```
Postgres  ->  backup bucket       full fidelity, nothing removed
backup    ->  stakeholder bucket  de-identified
```

This code is stage one. Stage two reads the output of stage one and never
touches the database.

Doing it this way rather than running two separate extracts has two
advantages. Aurora is read once instead of twice, which matters because that
instance runs into connection limits. And the de-identified copy can be
regenerated at any time without going back to the database, so if a masking
rule turns out to be wrong we fix it and re-run stage two. With two independent
extracts we would be stuck with whatever we masked at the time.

## What gets joined, and what does not

`requests` has nine declared foreign keys. Six point at lookup tables and are
joined, so the file says `RESOLVED` rather than `3`:

```
req_cat_id       -> help_categories
req_for_id       -> request_for
req_islead_id    -> request_isleadvol
req_type_id      -> request_types
req_priority_id  -> request_priorities
req_status_id    -> request_statuses
```

The other three point at `users`: `creator_id`, `beneficiary_id`,
`lead_volunteer_id`. These are **not** joined and stay as raw IDs.

The reason is that a lookup table has a label that describes a category. A user
has no label that is not their identity, so joining `users` would write
somebody's name into every request they have ever filed. That multiplies the
personal data in the file for no analytical gain, and the IDs on their own are
enough for anyone who later needs to resolve them.

## The ID is kept, not replaced

`req_status_id` and `req_status` both appear. It would be tidier to replace the
ID with the label, but the ID is the join key back to the source, labels can be
renamed upstream while IDs do not change, and once this file is the only copy
there is no recovering a column that was dropped. The cost is a few bytes.

## Why every join is a LEFT JOIN

An inner join silently drops any request whose reference is null or broken, and
the row count looks small rather than wrong. In dev, 218 of 221 requests had a
null `lead_volunteer_id`, so an inner join there would have returned 3 rows and
reported success. In an archive that becomes the only copy, a row disappearing
quietly is unrecoverable.

## Incremental mechanics

```
read watermark -> select the window -> upload to S3 -> advance watermark, log
```

The watermark moves last. A run that dies partway through leaves it where it
was, the next run recomputes the identical window, and the S3 key is derived
from that window so a repeat overwrites the same object instead of creating a
duplicate.

The window is half-open, `(lo, hi]`. A row whose timestamp sits exactly on a
bound belongs to exactly one run, never both and never neither.

The upper bound is five minutes in the past, not `now()`. `last_updated_at` is
set when the statement runs, but the row only becomes visible to us when the
transaction commits, which is later. Reading up to `now()` would permanently
skip a row stamped just under the bound and committed just over it, and nothing
would report an error. The lag has to be longer than the longest write
transaction in the application.

The consequence worth knowing: a row that arrives more than five minutes behind
the watermark is missed and will not be picked up later. If the application
ever grows long transactions, the lag needs raising.

## Its own stream

`archive_watermark` is keyed on `(source_table, stream)`. This runs under
`stream = 'backup'`, so it keeps its own watermark and run log rows and leaves
the earlier `main` stream alone. That meant no rows had to be deleted to make
room for it, which matters because the archival database role has SELECT,
INSERT and UPDATE on those tables but deliberately not DELETE.

## Deterministic output

`gzip.open` writes the current time into the gzip header, so two runs over the
same window produced different bytes for identical rows. The file is written
with `mtime=0` and an empty filename field instead, which makes the output byte
for byte reproducible. `ORDER BY` also carries `req_id` as a tiebreaker, so two
rows sharing a timestamp always come out in the same order.

Both of those exist so that "run the same window twice and compare" is a real
check rather than something that fails for reasons unrelated to the data.

## What was verified

Against the live dev database on 17 November 2026, 240 rows:

- row count matches the source and the run log
- no duplicate request ids, no missing rows, no invented rows
- 5280 field values compared one by one, not sampled
- 1440 joined labels checked against the lookup tables independently
- same window run twice, identical S3 ETag

The verifier is `scripts/verify/verify_archive.py`. It rebuilds what the file
should contain from the raw tables rather than re-running this code's own
query, because a verifier that reuses the exporter's SQL only proves the
exporter agrees with itself. Before it was trusted it was tested against five
injected faults, a dropped row, a duplicate, a tampered field, a wrong label
and a row shifted by one column, and it caught all five.

## Known gaps

- Not on a schedule. `DataPipelineEventBridgeScheduler-role` trusts only
  `lambda.amazonaws.com` and its invoke policy points at a function that does
  not exist in the account. Both need fixing before a schedule can be created.
- The database password is passed as a Lambda environment variable, because the
  VPC has no route to Parameter Store. That is readable by anyone with
  `lambda:GetFunctionConfiguration`. It needs an SSM interface endpoint or a
  NAT, and then the `INLINE_DB_CREDS` path should be removed.
- The stakeholder bucket for stage two does not exist yet.
- `raw/` in the same bucket holds four files from the earlier pre-join version.
  They are a different schema and are kept apart by prefix. They can be deleted
  once nobody wants them.
