# Requests archive verification (#586)

Checks that the archive `Data_ArchiveRequestData` writes to S3 (Task 2, #574)
matches the source database. The results so far are in [RESULTS.md](RESULTS.md).

| File | What it does |
| --- | --- |
| `verify_request_archive.py` | The verifier. Reads the source (read-only) and the archive (S3 or a local folder), prints PASS / FAIL / SKIP for the seven checks, times itself, and writes a JSON and Markdown report. Exits 1 if any check fails. |
| `run_local_harness.py` | Builds a local copy of the schema, runs the real Lambda against it with a mocked S3, then runs the verifier. Use this when you have no database or S3 access, and for check 5, which needs a broken reference the read-only source cannot be given. |
| `local_schema.sql` | The local schema, rebuilt from the schema spreadsheet. Every assumption is listed at the top. |
| `../../tests/test_archive_verification.py` | Shows each check failing on the problem it is meant to catch (inner-join export, second copy on re-run, gap, unresolved id, shifted timestamps). |

## The checks

1. **Row counts.** Every file holds exactly the source rows of its window. A row updated after the export has left its window in the source. It is reported as explained, not as missing.
2. **No duplicates.** No `(req_id, last_updated_at)` appears twice, within a file or across files. A request archived again after an update is a new version, because the Lambda's window follows `last_updated_at`. It is listed but only fails with `--strict-unique-requests` (see the open decision in RESULTS.md).
3. **No gaps.** Windows are contiguous, and every source row inside them is in its own window's file.
4. **Joins resolve.** Every id that exists in its lookup table carries that table's readable value.
5. **Broken references survive.** Every request whose reference is null or points at nothing is in the file, with its id kept and an empty readable value. This is computed from the source rows and lookups in Python, not with a SQL join, so it cannot share a join mistake with the Lambda.
6. **Re-runs are safe.** A window run twice leaves one object, with identical bytes.
7. **UTC.**
   - The timestamp columns are `timestamp without time zone`.
   - Each window selects the same rows under UTC, America/Phoenix and Asia/Kolkata sessions.
   - Exported timestamps equal the source values.
   - Every row lies inside its window, and no window ends after the UTC run time in its key.

SKIP means the input cannot exercise the check (one window only, no re-run, no broken reference). It is never counted as a pass.

## Running it against the real archive

You need read access to the database and the archive bucket. The verifier opens a read-only session and only lists and reads S3.

The archived files do not record which window they cover, so list the runs in a manifest. Take the values from the Lambda's response (`export.key`, `validation_summary.watermark_start`, `validation_summary.watermark_end`) or from its CloudWatch log:

```json
{"runs": [
  {"key": "requests_enriched/archive_year=2026/.../requests_enriched.csv",
   "watermark_start": "2026-11-09 10:00:00", "watermark_end": "2026-11-09 11:00:00"}
]}
```

From `data-engineering/`:

```bash
pip install psycopg2-binary boto3
python scripts/archive_verification/verify_request_archive.py \
    --dsn "$DATABASE_URL" \
    --manifest runs.json \
    --bucket <archive-bucket> --region us-east-1 --list-prefix requests_enriched/ \
    --report-dir scripts/archive_verification/reports/$(date +%F)
```

If someone with access would rather hand over files than run the script, download the objects named in the manifest and use `--archive-dir <folder>` instead of `--bucket`. The manifest keys are then paths inside that folder.

Check 3 needs at least two consecutive runs. Check 6 needs one window invoked twice with the same `watermark_start` and `watermark_end`, which needs permission to invoke the Lambda.

## Running it locally (no access needed)

You need a PostgreSQL you can write to. The harness drops and rebuilds the `virginia_dev_saayam_rdbms` schema in it, so never point it at a shared database.

```bash
docker run --rm -d --name archive-pg -p 5433:5432 -e POSTGRES_PASSWORD=pw postgres:16
pip install -r scripts/archive_verification/requirements-dev.txt
python scripts/archive_verification/run_local_harness.py \
    --dsn postgresql://postgres:pw@localhost:5433/postgres \
    --report-dir scripts/archive_verification/reports/local
python -m pytest tests/test_archive_verification.py
```

The harness takes about 10 s, nearly all of it deliberate one-second pauses between runs.
