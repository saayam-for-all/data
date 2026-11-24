Local test harness for issue #586 (verify the requests S3 archive matches the
source database).

This folder is **not** the deliverable for #586 -- that's
`data-engineering/scripts/verify_archive.py`, one level up, which is meant to
run against the real dev database and the real S3 bucket once credentials
are provided. This folder exists because no such credentials were available
while doing this work, so it builds a local stand-in to validate that
`verify_archive.py` actually does what the issue asks before handing it over.

What it does:

1. `local_schema.sql` -- the `requests` table, its lookup tables, and the
   `archive.*` bookkeeping tables, matching
   `data-engineering/infrastructure/db/requests_s3_archive/001_requests_s3_archive.sql`
   and the FK layout documented in
   `data-analytics/testing/issue_573_requests_foreign_key_mapping.xlsx`.
2. `load_mock_data.py` -- loads 300 requests across 5 days with null ratios
   matching the real prod stats for `lead_volunteer_id` / `beneficiary_id`,
   plus one request whose `req_cat_id` points at a category row that was
   never created (inserted by temporarily dropping the FK, per issue #586's
   own instructions, then restoring it `NOT VALID` so later inserts stay
   protected).
3. `local_export.py` -- reproduces `archive.export_requests_to_s3()`'s
   watermark/partitioning/bookkeeping logic in Python, writing each day's
   partition to a local CSV instead of calling the `aws_s3` extension (which
   only runs on RDS/Aurora, not a local container).
4. `fault_injection_test.py` -- takes the clean output from step 3, mutates
   a copy one way at a time (deleted row, duplicated row, changed field,
   changed FK, shifted row), and confirms `verify_archive.py` reports a FAIL
   on the specific check each mutation should break.

To reproduce (requires Docker and a Postgres+PostGIS image):

```
docker run -d --name saayam586 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=saayam -p 55432:5432 postgis/postgis:16-3.4
psql postgresql://postgres:postgres@localhost:55432/saayam -f local_schema.sql
PGPASSWORD=postgres python load_mock_data.py
python local_export.py --watermark-end 2026-11-16T00:00:00
PGHOST=localhost PGPORT=55432 PGUSER=postgres PGPASSWORD=postgres PGDATABASE=saayam \
  python ../verify_archive.py --run-id 1 --s3-root ./local_s3 --known-broken-ids REQ-BROKENREF
python fault_injection_test.py
```

See `data-engineering/testing/issue_586_archive_verification.md` for the
actual results of running this.
