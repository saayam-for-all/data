# Design Doc: Periodic Archival of `request` Table to S3

**Issue:** [#175](https://github.com/saayam-for-all/data/issues/175)  
**Status:** Draft — Awaiting Review  
**Author:** Madhumitha Pamala 
**Reviewers:** Data Engineering Team  
---

## 1. Problem Statement and Goals

### Why This Exists

The `request` table in the Saayam operational PostgreSQL database (`virginia_dev_saayam_rdbms`) grows monotonically — every help request submitted through the platform appends a new row and rows are rarely deleted. As of the current mock dataset, the table holds ~300+ rows spanning December 2025 through May 2026. At this growth trajectory, the table will become a performance bottleneck on the volunteer matching path, which queries it heavily for open/active requests.

Additionally, analytics queries (fulfillment SLA tracking, geographic demand analysis, category trends, donor reporting) cannot safely run against the production database without risking impact to live users.

### What "Done" Looks Like

- Closed requests (status `RESOLVED`, `CANCELLED`, `DELETED`, `RATED_BY_REQUESTER`, `RATED_BY_VOLUNTEER`) older than a configurable threshold (default: 90 days) are periodically exported to S3 in Parquet format.
- Exported data is queryable via Amazon Athena for analytics use cases.
- The pipeline runs automatically on a schedule with no manual intervention.
- PII fields are handled per-column according to the policy in Section 5.
- The operational database is not modified by this process (read-only extraction).

### Explicit Non-Goals

- **Not real-time CDC**: This is a batch archival job, not a streaming pipeline.
- **Not replacing the operational DB**: The `request` table remains the source of truth for active requests. Archived rows are not deleted from production (deletion is a separate decision requiring leadership sign-off).
- **Not archiving other tables**: `volunteers_assigned`, `volunteer_rating`, `users`, and related tables are out of scope for this design but the architecture should generalize.
- **Not a BI tool selection**: Athena is the query interface; dashboarding tools are a separate concern.
- **Not real-time analytics**: Freshness SLA is daily, not sub-minute.

---

## 2. Requirements

### 2.1 Functional Requirements

| Requirement | Decision | Justification |
|---|---|---|
| Which rows to archive | Rows where `req_status_id` ∈ {3, 4, 5, 6, 7} (terminal statuses) AND `last_update_date` < NOW() - 90 days | Active requests (status 0, 1, 2) must remain fast in the operational DB. The 90-day buffer allows for any late updates or disputes. |
| Cadence | **Daily**, triggered at 2:00 AM UTC | Daily balances freshness for analytics against compute cost. Hourly is unnecessary — closed requests don't need sub-day analytics. Weekly risks accumulating too large a batch on failure. |
| Extraction mode | **Incremental** (watermark-based) | Full snapshots would re-export all historical data on every run, wasting storage and compute. Incremental uses `last_update_date` as a high-water mark. |
| Updates to historical rows | Re-export updated rows on the next run. A row is included if `last_update_date` > last_run_timestamp, regardless of prior export status. | Handles edge cases like late rating submissions on old requests. |
| Deletes in source | Soft-deleted rows (`req_status_id = 5`) are included in the archive. Hard deletes (if ever introduced) would be handled via a tombstone record in S3. |

### 2.2 Non-Functional Requirements

| Requirement | Target |
|---|---|
| Freshness SLA for analytics | Data available in Athena within 24 hours of a request being closed |
| Monthly cost ceiling | < $20/month at current scale; < $150/month at 10× scale |
| Recovery on failure | Full re-run of the failed day's window is safe (idempotent write to S3 with overwrite) |
| Idempotency | Same `submission_date` partition written twice produces identical output — no duplicates |
| Operational DB impact | Queries run against a read replica only; zero write load on production |
| Data retention in S3 | 7 years (driven by nonprofit compliance expectations — confirm with leadership) |

---

## 3. Proposed Architecture

### 3.1 Overview Diagram

```
┌──────────────────────────────────────────────────────────┐
│               AWS EventBridge (cron: daily 2 AM UTC)      │
└─────────────────────────┬────────────────────────────────┘
                          │ triggers
                          ▼
┌──────────────────────────────────────────────────────────┐
│               AWS Lambda (Archival Job)                   │
│  1. Read high-water mark from SSM Parameter Store        │
│  2. Query read replica: SELECT * FROM request WHERE      │
│     req_status_id IN (3,4,5,6,7)                        │
│     AND last_update_date BETWEEN last_run AND NOW()      │
│  3. Apply PII transformations (hash/redact)              │
│  4. Write Parquet to S3 (partitioned by date)            │
│  5. Update high-water mark in SSM                        │
│  6. Trigger Glue Crawler (or use Glue auto-catalog)      │
└─────────────────────────┬────────────────────────────────┘
                          │ writes
                          ▼
┌──────────────────────────────────────────────────────────┐
│  S3 Bucket: saayam-data-lake-requests                    │
│  s3://saayam-data-lake/requests/                         │
│    year=2025/month=12/day=01/part-0001.parquet           │
│    year=2025/month=12/day=02/part-0001.parquet           │
│    ...                                                    │
└─────────────────────────┬────────────────────────────────┘
                          │ cataloged by
                          ▼
┌──────────────────────────────────────────────────────────┐
│  AWS Glue Data Catalog  ──────►  Amazon Athena           │
│  (schema + partition metadata)   (SQL queries by analysts)│
└──────────────────────────────────────────────────────────┘
```

### 3.2 Extraction: Watermark-Based SELECT on Read Replica

**Chosen approach:** Scheduled Lambda queries the RDS PostgreSQL read replica using a watermark stored in AWS SSM Parameter Store.

```sql
SELECT *
FROM request
WHERE req_status_id IN (3, 4, 5, 6, 7)
  AND last_update_date > :last_run_timestamp
  AND last_update_date <= :current_run_timestamp
ORDER BY last_update_date ASC;
```

**Why this over alternatives:**

- **AWS DMS (Database Migration Service):** Designed for ongoing replication/migration, not periodic archival. Adds cost and operational complexity for a daily batch job.
- **Debezium/CDC:** Captures every row-level change in real time. Overkill for a daily archival pattern; requires Kafka or Kinesis infrastructure.
- **Full snapshot SELECT:** Simple but re-exports all historical data every run — wasteful at scale.

**Tradeoff accepted:** Watermark-based extraction can miss rows if `last_update_date` is not updated reliably on every status change. The team must verify that all application code updates this column on every write.

### 3.3 S3 Layout

```
s3://saayam-data-lake/
  requests/
    year=YYYY/
      month=MM/
        day=DD/
          part-NNNN.parquet
```

**Partitioning key:** `submission_date` (when the request was originally created), not `last_update_date`. Analytics queries most commonly ask "how many requests were submitted in December?" — partitioning by submission date makes these efficient. Filtering by status or update date happens within partitions via Parquet column pruning.

**File format:** Parquet with Snappy compression.
- Columnar storage: Athena scans only the columns needed — critical for cost control (Athena bills per TB scanned).
- Snappy: Fast decompression, moderate compression ratio (~3–4×). Better for query performance than Gzip; Gzip is better for pure storage cost. Snappy chosen because query speed matters more than marginal storage savings at this scale.
- Target file size: 128 MB per file. Files smaller than ~64 MB result in Athena overhead per file; files larger than 256 MB slow down parallel reads.

### 3.4 Catalog and Query Layer

**AWS Glue Data Catalog** stores the schema and partition metadata. A Glue Crawler runs after each daily export to register new partitions.

**Amazon Athena** is the query interface for analysts. Example query:

```sql
SELECT req_cat_id, COUNT(*) as request_count, AVG(
  DATE_DIFF('day', submission_date, serviced_date)
) as avg_days_to_service
FROM "saayam_data_lake"."requests"
WHERE year = '2025' AND month = '12'
  AND req_status_id = 3  -- RESOLVED only
GROUP BY req_cat_id
ORDER BY request_count DESC;
```

**Tradeoff:** Glue Catalog + Athena is the lowest-friction path for a team already on AWS. It requires no additional infrastructure. The alternative (Redshift Spectrum) adds a cluster cost and is not justified at this data volume.

### 3.5 Orchestration

**EventBridge cron rule** (daily at 02:00 UTC) → **AWS Lambda** (Python, boto3 + psycopg2 + pyarrow).

Lambda is chosen over Step Functions because the job is a single-step extraction — no branching logic or parallel fan-out. If the job grows (e.g., multi-table, multi-partition backfill), Step Functions should be revisited.

Lambda timeout: 15 minutes (maximum). At current scale (~300 rows/day), this is far more than enough. At 10× scale (~3,000 rows/day), Parquet write and S3 upload will remain well under 5 minutes.

### 3.6 S3 Lifecycle Policy

| Age | Storage Class | Monthly cost (per GB) |
|---|---|---|
| 0–90 days | S3 Standard | ~$0.023 |
| 91–365 days | S3 Infrequent Access | ~$0.0125 |
| 366 days–7 years | S3 Glacier Instant Retrieval | ~$0.004 |
| > 7 years | Expire / Delete | — |

This matches expected access patterns: recent data is queried frequently; data older than a year is rarely touched except for annual reporting.

---

## 4. Schema Handling

### 4.1 Source Schema (`request` table)

The table lives in `virginia_dev_saayam_rdbms` and has the following columns (confirmed from `Saayam_Table.column.names_data.xlsx`):

| Column | Source Type | Parquet Type | PII? | Archival Treatment |
|---|---|---|---|---|
| `req_id` | `VARCHAR(255)` | `STRING` | No | Pass through (primary key) |
| `req_user_id` | `VARCHAR(255)` | `STRING` | **Yes** | Hash (SHA-256) — see Section 5 |
| `req_for_id` | `INTEGER` | `INT32` | No | Pass through (FK to lookup) |
| `req_islead_id` | `INTEGER` | `INT32` | No | Pass through |
| `req_cat_id` | `VARCHAR(50)` | `STRING` | No | Pass through |
| `req_type_id` | `INTEGER` | `INT32` | No | Pass through |
| `req_priority_id` | `INTEGER` | `INT32` | No | Pass through |
| `req_status_id` | `INTEGER` | `INT32` | No | Pass through |
| `req_loc` | `VARCHAR(125)` | `STRING` | **Yes** | Keep city/state only (strip street-level precision) |
| `iscalamity` | `BOOLEAN` | `BOOLEAN` | No | Pass through |
| `req_subj` | `VARCHAR(125)` | `STRING` | **Yes** | Pass through with warning — may contain names |
| `req_desc` | `VARCHAR(255)` | `STRING` | **Yes** | Pass through with warning — free text, may contain PII |
| `req_doc_link` | `TEXT` | `STRING` | **Yes** | Redact (S3 paths may expose user identity) |
| `audio_req_desc` | `VARCHAR(255)` | `STRING` | **Yes** | Redact (audio transcript text) |
| `submission_date` | `TIMESTAMP` | `TIMESTAMP(UTC)` | No | Pass through (also used as partition key) |
| `serviced_date` | `TIMESTAMP` | `TIMESTAMP(UTC)` | No | Pass through |
| `last_update_date` | `TIMESTAMP` | `TIMESTAMP(UTC)` | No | Pass through (used as watermark) |
| `to_public` | `BOOLEAN` | `BOOLEAN` | No | Pass through |

**Added columns in archive (not in source):**
- `archive_date`: DATE — date this row was written to S3 (for audit/debugging)
- `req_user_id_hashed`: STRING — SHA-256 of `req_user_id` (for analytics joins without exposing raw ID)

### 4.2 Schema Evolution Strategy

| Change type | Handling |
|---|---|
| New column added to source | Glue Crawler detects new column; existing Parquet files show NULL for that column in Athena. No pipeline change needed. |
| Column removed from source | Archived files retain the column; new files will not have it. Athena queries must use `IF EXISTS` or COALESCE patterns. |
| Column renamed | Treat as remove + add. Historical data retains old name; new data uses new name. Analytics queries must handle both. Document in changelog. |
| Column type changed | Flag as breaking. Test Parquet write; if incompatible, introduce a new column (e.g., `req_loc_v2`) rather than overwriting. |

**Type mappings (PostgreSQL → Parquet):**

| PostgreSQL | Parquet |
|---|---|
| `VARCHAR`, `TEXT`, `CHARACTER VARYING` | `UTF8 (STRING)` |
| `INTEGER`, `INT` | `INT32` |
| `BIGINT` | `INT64` |
| `BOOLEAN` | `BOOLEAN` |
| `NUMERIC(9)` | `DOUBLE` |
| `TIMESTAMP WITHOUT TIME ZONE` | `TIMESTAMP(isAdjustedToUTC=false, unit=MICROS)` |
| `TIMESTAMP WITH TIME ZONE` | `TIMESTAMP(isAdjustedToUTC=true, unit=MICROS)` |
| `TEXT[]`, `JSONB` | `STRING` (serialize as JSON string) |

---

## 5. PII and Privacy

### 5.1 PII Columns Identified

The `request` table contains the following PII fields based on schema analysis and sample data review:

| Column | PII Type | Risk Level |
|---|---|---|
| `req_user_id` | User identifier (links to `users` table with name, email, phone, address) | High |
| `req_loc` | Location string (observed values: "Ashburn, VA", "Charlotte", "North Carolina") | Medium |
| `req_subj` | Free text — observed values include personal names, languages, specific needs | Medium |
| `req_desc` | Free text — observed values include personal names (e.g., "Rashmi Purandare"), locations, medical needs | High |
| `req_doc_link` | S3 path containing `req_id` and file names that may be identifying | Medium |
| `audio_req_desc` | Audio transcript text — same risk as `req_desc` | High |

**Note:** `request_guest_details` (a related table, out of scope here) contains `req_fname`, `req_lname`, `req_email`, `req_phone` — if this table is archived in a future phase, those columns must be treated as high-risk PII.

### 5.2 Per-Column Decisions

| Column | Decision | Method |
|---|---|---|
| `req_user_id` | **Hash** | SHA-256 with a secret pepper (stored in AWS Secrets Manager). Store as `req_user_id_hashed`. Drop raw value. Allows analytics joins across tables using the same hash without exposing the ID. |
| `req_loc` | **Coarsen** | Extract only city and state (e.g., "Ashburn, VA" → "Virginia"). Remove street-level data if present. Sufficient for geographic demand analytics. |
| `req_subj` | **Pass through with flag** | Analytics consumers must be trained not to surface raw values. Future phase: NLP-based PII redaction. |
| `req_desc` | **Pass through with flag** | Same as `req_subj`. High-risk but necessary for NLP/ML model training. Access restricted by IAM + Lake Formation. |
| `req_doc_link` | **Redact** | Replace with boolean `has_doc_link` (TRUE/FALSE). Document paths expose S3 bucket structure and user-specific paths. |
| `audio_req_desc` | **Redact** | Replace with boolean `has_audio_desc` (TRUE/FALSE). Transcript text is high-risk and not needed for current analytics use cases. |

### 5.3 Encryption and Access Control

- **At rest:** SSE-KMS on the S3 bucket using a dedicated CMK (Customer Managed Key). Key rotation enabled annually.
- **In transit:** HTTPS for all S3 and Athena API calls (enforced via bucket policy `aws:SecureTransport`).
- **Access control:** IAM roles — separate roles for the Lambda writer and Athena read-only analysts. Bucket policy denies all access without valid IAM role.
- **Lake Formation (optional):** If column-level access control is needed (e.g., only data engineers can see `req_desc`; analysts see everything else), enable Lake Formation on the Glue catalog. This is recommended but not required for initial rollout.
- **Bucket policy:** Block all public access. Enable S3 access logging.

---

## 6. Alternatives Considered

### Alternative 1: AWS Kinesis Firehose (Streaming)

**How it works:** Firehose taps into application events (via the request microservice) and streams every new/updated request to S3 in near real-time, converting to Parquet automatically.

**Pros:**
- Near real-time data in S3 (seconds to minutes of lag)
- No database load — reads from the application layer, not the DB
- Managed service with built-in buffering and retry

**Cons:**
- Requires changes to the `request` microservice to emit events to Kinesis — cross-team dependency and significant scope expansion
- More expensive at low volume (Firehose charges per GB ingested + per PUT request)
- Does not solve the historical backfill problem — only captures future events
- More complex to operate than a nightly Lambda

**Why not chosen:** Scope too large for this phase. The team does not yet have event streaming infrastructure. Revisit when real-time analytics becomes a requirement.

### Alternative 2: Native RDS Export to S3 (AWS RDS Snapshot Export)

**How it works:** AWS supports exporting RDS snapshots directly to S3 as Parquet. A daily snapshot can be exported automatically.

**Pros:**
- No code to write — fully managed by AWS
- Exports the entire database (all tables) in one operation
- Parquet output natively supported

**Cons:**
- Exports the **entire database**, not just the `request` table. Cannot filter by status or date range.
- Exports the **entire history** on every run — no incremental support. Storage costs scale linearly with database size.
- PII transformations cannot be applied during export — a post-processing Lambda would still be needed
- Snapshot must be taken first, adding latency and storage cost for the snapshot itself
- All tables are exported even if only `request` is needed

**Why not chosen:** The lack of incremental filtering and inability to apply PII transformations during export make this approach unsuitable. It solves the "get data to S3" problem but not the "clean, query-ready, PII-safe data lake" problem.

### Alternative 3: Third-Party ETL (Fivetran / Airbyte)

**How it works:** Managed ETL services connect to the PostgreSQL database and sync data to a destination (S3, Redshift, BigQuery) on a schedule.

**Pros:**
- Zero infrastructure to manage
- Schema change handling built-in
- Rich monitoring and alerting dashboards

**Cons:**
- Fivetran cost is significant (~$1/month per 1,000 MAR — Monthly Active Rows). At 10× scale, this could exceed $500/month easily.
- PII transformations must be applied in a separate step or via destination transformations — adds complexity
- Vendor lock-in: changing providers requires pipeline redesign
- Data passes through third-party infrastructure — may conflict with donor data privacy commitments

**Why not chosen:** Cost and data privacy concerns outweigh the operational convenience, especially for a nonprofit with a tight cost ceiling. The custom Lambda approach is simple enough to not need a managed ETL tool.

---

## 7. Failure Modes and Observability

### 7.1 Failure Scenarios

| Failure | Behavior | Recovery |
|---|---|---|
| Lambda times out mid-export | Partial Parquet file NOT committed to S3 (write is atomic via multi-part upload; partial files are abandoned). High-water mark is NOT updated. | Next scheduled run re-processes the same window. Idempotent. |
| RDS read replica unavailable | Lambda catches connection error, publishes to SNS alert, exits with non-zero code. EventBridge retry policy triggers 2 retries with exponential backoff. | Manual re-run or wait for next day's scheduled run. |
| S3 write fails (permissions, bucket policy) | Lambda catches boto3 exception, publishes to SNS, exits. High-water mark NOT updated. | Fix IAM/bucket policy, re-run. |
| Glue Crawler fails | Existing partitions remain queryable. New partition not visible in Athena until next successful crawler run. | Re-run crawler manually via AWS Console or CLI. |
| Watermark corrupted in SSM | Lambda reads invalid timestamp, fails validation check, publishes alert, exits without writing. | Restore watermark from CloudWatch logs (last successful run timestamp is logged). |
| Duplicate run (EventBridge fires twice) | S3 overwrite with identical data (idempotent). Glue Crawler re-registers same partitions (no-op). | No action needed. |

### 7.2 Metrics and Alerts

The following CloudWatch metrics should be published by the Lambda on every run:

- `archival/rows_exported` — count of rows written in this run
- `archival/bytes_written` — size of Parquet file written
- `archival/run_duration_seconds` — total Lambda execution time
- `archival/watermark_lag_hours` — hours between current watermark and NOW() (alert if > 26 hours)

**SNS alerts on:**
- Lambda error (any unhandled exception)
- `archival/rows_exported = 0` for 3 consecutive days (possible watermark drift or pipeline stall)
- Lambda duration > 10 minutes (risk of timeout)

### 7.3 On-Call Ownership

Data Engineering team owns this pipeline. Runbook should be documented in `data-engineering/runbooks/requests-archival.md` covering: how to check the high-water mark, how to trigger a manual backfill, and how to verify Athena queryability after a fix.

---

## 8. Cost Estimate

### Assumptions

- **Current scale:** ~300 rows/month, average row size ~1 KB uncompressed → ~300 KB/month raw → ~75 KB/month Parquet (Snappy, ~4× compression)
- **10× scale:** ~3,000 rows/month → ~750 KB/month Parquet
- **AWS region:** us-east-1 (Virginia, where the existing RDS is deployed)

### Current Scale (~300 rows/month)

| Service | Usage | Monthly Cost |
|---|---|---|
| S3 Storage (Standard, first 90 days) | ~1 MB/month accumulating | ~$0.00 |
| S3 Storage (IA, months 4–12) | ~10 MB | ~$0.00 |
| S3 Storage (Glacier, year 2+) | ~120 MB/year | ~$0.001 |
| Lambda (daily runs, ~30s each) | 30 invocations × 512 MB × 30s | ~$0.00 (within free tier) |
| Athena (assuming 10 queries/month, 10 MB scanned each) | 100 MB scanned | ~$0.00 (< $0.0005) |
| Glue Crawler (daily, ~1 min each) | 30 DPU-minutes/month | ~$0.07 |
| EventBridge | 30 scheduled rule invocations | ~$0.00 (free tier) |
| CloudWatch Logs | ~1 MB/month | ~$0.005 |
| **Total** | | **< $1/month** |

### 10× Scale (~3,000 rows/month)

| Service | Usage | Monthly Cost |
|---|---|---|
| S3 Storage (all tiers, 2-year accumulation) | ~18 MB Parquet | ~$0.001 |
| Lambda | Same as above | ~$0.00 |
| Athena (100 queries/month, 100 MB scanned each) | 10 GB scanned | ~$0.05 |
| Glue Crawler | Same | ~$0.07 |
| **Total** | | **< $2/month** |

**Note:** At 100× scale (30,000 rows/month — realistic in 2–3 years with user growth), costs remain under $10/month. The architecture is highly cost-efficient for this data volume. The cost ceiling of $20/month is not a concern at projected growth rates.

---

## 9. Rollout Plan

### Phase 1: Shadow Run (Week 1)

- Deploy Lambda in a dev environment pointed at a dev/staging RDS replica.
- Run manually (not on schedule) for 3 consecutive days.
- Validate: row counts match expectations, Parquet files are readable via pyarrow locally, PII transformations applied correctly.
- No Athena queries yet — just verify S3 output.

### Phase 2: Historical Backfill (Week 1–2)

- Run Lambda with `last_run_timestamp = 2025-01-01 00:00:00` to backfill all historical closed requests.
- Verify Glue Crawler catalogs all partitions correctly.
- Run sample Athena queries to confirm data is queryable.
- Spot-check 10 random rows against production DB to verify data integrity.

### Phase 3: Production Cutover (Week 2)

- Enable EventBridge cron rule in production.
- Monitor first 5 automated runs via CloudWatch dashboard.
- Share Athena access credentials with Data Analytics team.
- Document query examples in `data-analytics/` folder.

### Phase 4: Steady State

- Monitor weekly for first month.
- After 30 days of clean runs, reduce monitoring to monthly review.
- Review and adjust the 90-day archival threshold after 6 months based on team feedback.

### Rollback Plan

If the pipeline produces incorrect data (wrong rows, PII exposure, corrupt Parquet):
1. Disable EventBridge rule immediately.
2. Delete affected S3 partitions (`aws s3 rm s3://saayam-data-lake/requests/year=YYYY/...`).
3. Drop affected Glue partitions (`MSCK REPAIR TABLE` or manual partition drop in Athena).
4. Fix the Lambda code, re-validate in dev, re-run backfill for affected dates.
5. No changes to the operational database are ever needed — this pipeline is read-only.

---

## 10. Open Questions

The following items could not be decided without additional input:

1. **Archival threshold:** Is 90 days the right cutoff for moving closed requests to S3? Should the operational DB also delete (or soft-archive) rows after export, or keep them indefinitely? This requires leadership sign-off.

2. **Data retention period:** 7 years was assumed based on typical nonprofit compliance. Does Saayam For All have specific legal retention obligations (state-level nonprofit laws, IRS 501(c)(3) record-keeping requirements)? Legal/leadership must confirm.

3. **`req_subj` and `req_desc` PII handling:** These free-text fields may contain names and personal information (e.g., "Rashmi Purandare", medical conditions). Currently proposed as pass-through with restricted access. Does the analytics team actually need raw text, or would category and status fields alone suffice? If raw text is not needed, redact both columns.

4. **Read replica availability:** Does a RDS read replica exist in the current AWS setup, or does the Lambda need to query the primary? Querying primary is acceptable at current scale but adds risk.

5. **`req_user_id` hash pepper rotation:** If the SHA-256 pepper is rotated, historical hashes become inconsistent (old and new data cannot be joined on `req_user_id_hashed`). What is the key rotation policy?

6. **Lake Formation requirement:** Is column-level access control (e.g., hiding `req_desc` from junior analysts) required from day one, or can it be added in a later phase?

7. **`request_guest_details` table:** Guest users' requests include `req_fname`, `req_lname`, `req_email`, `req_phone`. Should these be joined and included in the archive (with appropriate PII handling), or archived separately?

8. **Glue Crawler cost vs. partition projection:** At higher query volumes, Glue Crawler cost could be reduced by switching to Athena partition projection (eliminates the crawler entirely). Not needed now but should be revisited at scale.

---

