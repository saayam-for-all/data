# Design Doc: Periodic Archival of `requests` Table to S3

**Ticket:** #175 **Status:** Draft for review **Author:** Achyuth Kumar Undrakonda

> **Note on inputs.** Written while schema, row count, and DB engine details were still being gathered from Pallavi (sub-issue under #175). The DDL has since been received and is incorporated throughout - Section 4.1 has the logical-name → actual-column mapping, Section 4.4 covers the lookup-table issue the DDL raised, Section 10 tracks what the DDL resolved vs. what's still open. Row count, growth rate, read replica status, and exact DB version still pending from Pallavi. Retention and use-case scope came from Rao and are reflected throughout. Sections that still need Pallavi's numbers are in *italics*. Everything else is a firm recommendation.
>
> **Note on naming.** This doc uses logical column names (`request_id`, `created_at`, `updated_at`, `need_description`) throughout for readability. The actual table is `virginia_dev_saayam_rdbms.request` (singular) with its own column names. Section 4.1 is the translation table; don't use it as a code reference without checking there first.

## 1. Problem Statement and Goals

The `requests` table grows monotonically - every help request appends a row, and closed rows are almost never touched again by the matching path. That's a problem three ways: the index keeps growing and will eventually hurt tail latency on matching queries, we're paying operational-DB storage rates for cold data, and analytics can't run against production without risking impact to live users.

When we scoped this with Rao, it turned out the archival problem is also a data-product problem. The resulting dataset has three consumers, not one:

1. **Internal analytics** - fulfillment SLAs, geographic demand, volunteer reach, donor reporting. The original ticket.
2. **Internal RAG agent** - Saayam is building a retrieval-augmented generation agent against this data.
3. **Third-party data product** - Saayam plans to license request and conversation data to external vendors (Reddit/NextDoor model: behavioral data, never PII). Any PII leak to a vendor is a contractual and legal problem, not just a privacy one.

The three consumers have different needs and different trust levels, and that difference drives most of the architectural choices below.

**What we're building:** a three-stage pipeline that extracts `requests` data on a schedule, scrubs PII before anything lands anywhere consumable, and serves the result to internal analytics, the RAG agent, and licensed vendors - with the strictest controls on the vendor path.

**Done looks like:**

1. New and updated rows land in the lake on a defined cadence with a defined freshness SLA.
2. PII scrubbing is a separate, auditable stage with a quality gate before data reaches any external consumer.
3. Internal analysts can query via Athena; the RAG team has a training dataset; vendors have read-only access with zero PII.
4. Closed rows old enough to drop from the operational DB can be dropped without anyone losing access.
5. Retention windows, lifecycle rules, and SLA thresholds are in Parameter Store - not hard-coded.
6. Cost is bounded and estimated at current and 10× scale.

**Not doing:**

- Real-time anything. Freshness is in hours.
- CDC as a service. Nothing subscribes to a row-level change stream from this pipeline.
- Replacing the operational DB. Reads and writes stay there.
- Archiving other tables. `volunteers`, `donations`, `matches`, conversations each get their own design doc. This one should be the template.
- BI tool selection.
- The legal/contractual framework with vendors. That's a separate workstream. We're building the technical guarantees; someone else negotiates the contract terms.

## 2. Requirements

### 2.1 Functional

- **Rows in scope.** All rows, including open ones. Deleting cold rows from the operational DB is Phase 6 (Section 9), gated on the lake being proven trustworthy first.
- **Terminal status IDs.** For extraction queries: RESOLVED=3, CANCELLED=4, DELETED=5, RATED_BY_REQUESTER=6, RATED_BY_VOLUNTEER=7. Open/active statuses (0, 1, 2) go into the lake but stay in the operational DB and aren't candidates for deletion.
- **Grace period before DB deletion.** How long after a row goes terminal before we're allowed to delete it from the operational DB is TBD - 7 days was one proposal, 90 days another. 90 days gives more buffer for late ratings and corrections. Confirmed at design review. Note: archival to the lake has no grace period; all rows land there as soon as they're extracted.
- **Cadence.** Hourly incremental extracts, daily compaction. Hourly is what internal consumers need for the freshness SLA; nobody's asked for sub-hour. Vendor data updates on the same cadence - the scrubber is the gating step, so vendors see scrubbed data only.
- **Incremental, not full snapshots.** Watermarked on `last_update_date`. One historical backfill to start, then incremental forever. Periodic row-count reconciliation against source to catch drift.
- **Updates to historical rows.** Status changes, match assignments, late ratings - all handled by upserting into the daily partition on `created_at`, then deduplicating in the compaction job on `(request_id, max(updated_at))`.
- **Deletes.** Hard deletes are rare and almost always privacy-erasure-driven, not operational. Handled via soft-delete flag (`req_status_id = 5`); next scrubber run drops the row from the lake, with free-text and document-derived fields blanked. Vendor data must reflect erasures within the contractual SLA.

### 2.2 Non-functional

- **Freshness SLA.** P95 row visible in the internal lake within 90 minutes of source commit. P99 within 3 hours. Vendor-visible data lags by one additional cycle (scrubber + quality gate).
- **Configurability.** Retention periods, lifecycle thresholds, freshness SLA targets all live in Parameter Store. Jobs pick up changes on the next run without redeployment. *Tentative retention: 10 years. Confirm with leadership; tracked in Parameter Store.*
- **Cost ceiling.** Under $300/month at current scale, under $2,000/month at 10×. Section 8 has the breakdown.
- **Recovery.** A failed run can't corrupt prior partitions or expose unscrubbed data downstream. Reruns are idempotent. A scrubber failure leaves raw-staging untouched and the lake unchanged.
- **Idempotency.** The same watermark window run twice produces the same logical output. File names may differ; row content won't.
- **Security posture.** Hard zero-PII bar on the vendor dataset. A PII leak to a vendor is a legal liability, not just a privacy incident. We're treating this as a multi-layer defense problem, not a single transformation step.
- **Availability.** This isn't on the production critical path. A 24-hour lake outage is annoying, not an incident. A scrubber failure that could expose PII is high-severity.

## 3. Proposed Architecture

Three pipeline stages - Collection, Scrubbing, Serving - separated by S3 areas with different access controls. Internal analytics and the RAG agent read from the post-scrub internal lake. Vendors read from a separate, more restricted serving layer.

```
┌────────────────────┐
│ Operational DB      │
│ (primary)            │
└──────────┬──────────┘
           │
           ▼
┌────────────────────┐     ┌──────────────────────────┐
│ Read replica         │────▶│ STAGE 1: Collection        │
│ (lagging, RO)         │     │ Extractor (Lambda/Fargate) │
└────────────────────┘     └─────────────┬──────────────┘
                                           │ Parquet
                                           ▼
                            ┌──────────────────────────┐
                            │ S3: raw-staging/            │
                            │ Internal-only, locked down  │
                            │ Short retention (30d)       │
                            └─────────────┬──────────────┘
                                           │
                                           ▼
                            ┌──────────────────────────┐
                            │ STAGE 2: Scrubbing          │
                            │ - Column drops/hashes       │
                            │ - Free-text PII redaction   │
                            │ - Quality gate (sampling)   │
                            └─────────────┬──────────────┘
                                           │ Scrubbed Parquet
                                           ▼
                            ┌──────────────────────────┐
                            │ S3: lake/ (internal)         │
                            │ year=/month=/day=/          │
                            │ Internal analytics + RAG    │
                            └─────────────┬──────────────┘
                                           │
                                           ▼
                            ┌──────────────────────────┐
                            │ STAGE 3: Serving             │
                            │ - Internal: Athena            │
                            │ - Vendors: separate path      │
                            │   (Section 5.4)                │
                            └──────────────────────────┘
```

The two staging areas - raw and scrubbed - are the key structural decision. Section 5 explains why.

### 3.1 Stage 1: Collection

**Chosen: watermark-based incremental SELECT against the read replica, hourly.**

| Option | Why not / why yes |
|---|---|
| AWS DMS | Handles CDC + bulk-load to S3, but it's more infrastructure than we need for one table. Worth it for sub-minute freshness or many tables; neither applies here. |
| Debezium / self-managed CDC | Catches every UPDATE and DELETE without polling, but requires Kafka and couples the archive to logical replication. Good choice when we have ten tables and a streaming use case. Not now. |
| Native DB export to S3 | Good for bulk snapshots, bad for steady-state incremental. We use this for the one-time historical backfill (Section 9). |
| Kinesis Firehose | Requires the app to emit events. We don't do that. Out of scope. |
| Watermark SELECT against read replica | Simple, transparent, easy to debug locally. Read replica keeps extraction load off the matching path. **Chosen.** |

**Watermark column:** `last_update_date`, not `submission_date`. Status changes and match assignments happen on existing rows; partitioning by submission date but watermarking by last update is how we catch them.

For this to work safely:
- `last_update_date` must be set on every INSERT and every UPDATE. The received DDL shows only a `BEFORE INSERT` trigger. Confirm with Pallavi that application code handles UPDATE reliably, or we add a `BEFORE UPDATE` trigger (recommended regardless - don't depend on every code path remembering).
- Extract window is `[last_watermark, now − 60s)`. The 60-second safety margin covers clock skew and in-flight transactions.
- Watermark advances in DynamoDB only after the partition is successfully published.

**Output:** raw, unscrubbed Parquet to `s3://saayam-raw-staging-prod/requests/run_id=<uuid>/`. Only the extractor's IAM role can write here; only the scrubber's role can read. No direct human access except break-glass with audit trail. Lifecycle expires objects after 30 days (Parameter Store) - long enough to re-scrub if redaction rules change, short enough to limit the PII exposure window.

### 3.2 Stage 2: Scrubbing

A separate Fargate task that runs after each successful collection run. It reads from raw staging, applies column-level transformations (Section 5.2), runs free-text redaction (Section 5.3), writes scrubbed Parquet to `s3://saayam-lake-prod/requests/year=/month=/day=/`, updates Glue partition metadata via partition projection, and emits scrubbing metrics (PII tokens detected per run, redaction rate, sample-review queue depth).

**Why a separate stage and not a transformation step inside the extractor:**

- **Auditability.** Diffing raw vs. scrubbed proves what was redacted. You need that for vendor disputes and erasure-request compliance.
- **Re-scrubbability.** If the redaction rules improve (better model, new regulation, a missed pattern), the scrubber can re-run over historical raw data without touching the source DB.
- **Failure isolation.** An extractor bug and a scrubber bug have completely different blast radii. Keeping them separate makes on-call triage cleaner.
- **Quality gate.** The natural place to run sampling review before scrubbed data becomes vendor-visible is at the scrubber → lake handoff.

### 3.3 Stage 3: Serving

**Internal consumers** (analytics, RAG training): Glue Data Catalog + Athena, directly against the internal lake. Partition projection on `year/month/day` means new partitions are queryable as soon as they land.

**Vendor consumers:** Section 5.4. Separate path with stricter controls.

Internal and vendor consumers have different access patterns, different threat models, and different cost-attribution requirements. Keeping them on separate paths lets us meter and govern them independently.

### 3.4 S3 Layout

```
s3://saayam-raw-staging-prod/      # raw, internal-only, 30d retention
  requests/run_id=.../*.parquet

s3://saayam-lake-prod/             # scrubbed, internal analytics + RAG
  requests/
    year=2026/month=05/day=29/part-00000.parquet
    ...

s3://saayam-vendor-prod/           # vendor-facing serving layer
  (per-vendor structure - Section 5.4)

s3://saayam-lake-archive-prod/     # cold tier if needed
```

Four buckets because access patterns, audit requirements, and lifecycle rules are different for each. Combining them makes IAM and lifecycle policies harder to reason about and harder to audit.

**Partitioning: `year/month/day` on `submission_date`.**

Analytics queries ask when a request was submitted, not when it was last touched. Partitioning on `submission_date` makes time-range queries efficient and keeps update processing clean - an updated row re-lands in its original partition rather than scattering across multiple ones. Region isn't a partition key (moderate cardinality, many queries span regions) - it lives as a column with predicate pushdown. Day-level, not hour-level - hourly partitions would explode the partition count.

**File format:** Parquet, Snappy compression, 128–256 MB target file size post-compression. Standard Athena sweet spot. Daily compaction brings the hourly small files into range.

### 3.5 Catalog and Query Layer

Glue Data Catalog + Athena. It's the lowest-friction AWS-native path, partition projection eliminates registration latency, and Athena v3 is serverless and pay-per-scan - which matches a bursty read-only workload well.

Iceberg is worth keeping in the conversation. It handles real upserts, time travel, and schema evolution without the partition-rewrite dance. Starting on plain Parquet because it ships faster and is simpler; the partitioning and key columns are designed so an Iceberg migration is viable later. Revisit at the 6-month mark - worth a discussion at design review.

### 3.6 Orchestration

**EventBridge → Step Functions → Lambda or Fargate.**

- EventBridge fires the hourly collection schedule.
- Step Functions coordinates: read watermark → extract → write raw staging → trigger scrubber → scrubber writes to lake → publish Glue partitions → advance watermark → emit metrics.
- Collection extractor: Lambda if it fits in 15 minutes at expected volume, Fargate otherwise. *Depends on row count from Pallavi; at 10× scale, Fargate.*
- Scrubber: Fargate. NLP redaction libraries are too heavy for Lambda at any volume.
- Daily compaction: Fargate on its own schedule.

MWAA is overkill for three jobs. Revisit when the pipeline grows to ten or more interdependent steps.

### 3.7 Lifecycle Policy

All thresholds in Parameter Store.

- S3 Standard: 0–30 days. Most internal queries hit recent data.
- S3 Standard-IA: 30–180 days.
- S3 Glacier Instant Retrieval: 180 days–2 years. Still Athena-queryable.
- S3 Glacier Deep Archive: 2 years–10 years. Not directly queryable; retrieval is a deliberate step.
- Raw staging: deleted at 30 days.
- Vendor buckets: retention matches contractual vendor terms (typically rolling 1–2 years, configurable).

## 4. Schema Handling

### 4.1 Source → S3 Mapping

One column per source column, names preserved in snake_case. PII transformations are applied in Stage 2 (Section 5). Transformed columns keep their original name in the scrubbed output; the treatment is recorded in column metadata and in the vendor data dictionary (Section 5.4).

**Logical name → actual column.** The doc uses logical names (left column) throughout. The table below, from the received DDL (`virginia_dev_saayam_rdbms.request`), is the source of truth.

| Logical name | Actual column | Notes |
|---|---|---|
| `request_id` | `req_id` | `VARCHAR(255)` PRIMARY KEY, generated by a `BEFORE INSERT` trigger as `REQ-XX-XXX-XXX-XXXX`. Not a UUID - treat as an opaque formatted string. |
| `requester_id` | `req_user_id` | `VARCHAR(255) NOT NULL`, FK → `users.user_id`. |
| `created_at` | `submission_date` | `TIMESTAMP`. No time-zone qualifier - see Section 4.2. |
| `updated_at` | `last_update_date` | `TIMESTAMP`. Column exists but DDL has no `BEFORE UPDATE` trigger - see Section 10, item 5. |
| `status` | `req_status_id` | `INT NOT NULL`, FK → `request_status`. Not an inline value - see Section 4.4. |
| `need_description` | `req_desc` | `VARCHAR(255) NOT NULL`, free text. |
| *(none assumed previously)* | `req_loc` | `VARCHAR(125)`, free text. Replaces the assumed structured address/lat-long columns, none of which exist on `request`. See Section 5.2. |
| *(new)* | `req_subj` | `VARCHAR(125) NOT NULL`, free-text subject line. |
| *(new)* | `req_doc_link` | `TEXT`, link to uploaded documents. Dropped in scrubbed output; replaced by `has_document` boolean - see added columns below. |
| *(new)* | `audio_req_desc` | `VARCHAR(255)`, audio description/recording reference. Dropped in scrubbed output; replaced by `has_audio_description` boolean - see added columns below. |
| *(new)* | `iscalamity` | `BOOLEAN`. |
| *(new)* | `req_for_id`, `req_islead_id`, `req_cat_id`, `req_type_id`, `req_priority_id` | `INT`/`VARCHAR` FKs into lookup tables - see Section 4.4. |
| *(new)* | `serviced_date` | `TIMESTAMP`, completed-or-cancelled date. |
| *(pending confirmation)* | `to_public` | `BOOLEAN`. Present in mock dataset schema (`Saayam_Table.column.names_data.xlsx`) but absent from Pallavi's DDL. Confirm before implementation - see Section 10, item 15. Pass through if confirmed. |
| `requester_name`, `requester_phone`, `requester_email`, `street_address`, `postcode`, `city`, `region`, `latitude`, `longitude`, `submitted_ip` | **Not on `request`.** | These were assumed in the original draft. Identity fields live on `users` via `req_user_id` - out of scope unless we join `users` in later (which needs its own PII review). Also note: `request_guest_details` exists with `req_fname`, `req_lname`, `req_email`, `req_phone` for guest users - also out of scope here; see Section 10, item 16. |

**Columns the pipeline adds (not in source):**

| Added column | Parquet type | Derivation | Purpose |
|---|---|---|---|
| `req_user_id_hashed` | `STRING` | HMAC-SHA256 of `req_user_id` with KMS-managed salt | Unique-requester analytics without exposing the raw ID. Raw `req_user_id` dropped from scrubbed output. |
| `has_document` | `BOOLEAN` | `req_doc_link IS NOT NULL` | Attachment signal for analytics - no link or path exposed. |
| `has_audio_description` | `BOOLEAN` | `audio_req_desc IS NOT NULL` | Audio availability signal - no content exposed. |
| `hours_to_service` | `DOUBLE` | `(serviced_date - submission_date)` in hours; `NULL` if unserviced | Pre-computed SLA metric. |
| `source_schema_version` | `INT` | Set by extractor at run time | Schema lineage - useful during evolution events. |
| `export_run_id` | `STRING` | UUID per Step Functions execution | Traceability back to the run manifest. |
| `exported_at_utc` | `TIMESTAMP` | Set by extractor at write time | Audit trail independent of source timestamps. |

### 4.2 Type Mappings

*Confirmed against the received DDL where applicable. Rows the DDL doesn't exercise are kept for future columns.*

| Source type | Parquet type | Notes |
|---|---|---|
| `INTEGER`, `BIGINT` | `INT32`, `INT64` | Direct. Applies to FK columns. |
| `NUMERIC(p,s)` / `DECIMAL` | `DECIMAL(p,s)` logical type | Preserve precision - don't coerce to `DOUBLE`. Not in `request` currently. |
| `BOOLEAN` | `BOOLEAN` | Direct. Applies to `iscalamity`. |
| `TEXT`, `VARCHAR` | `BYTE_ARRAY` (`UTF8`) | Scrubbed if marked as free-text PII (Section 5.3). Applies to `req_desc`, `req_subj`, `req_loc`, `req_id`, `req_user_id`, `req_doc_link`, `audio_req_desc`. |
| `TIMESTAMP WITHOUT TIME ZONE` | `INT64` `TIMESTAMP(isAdjustedToUTC=false, MICROS)` | This applies to all three timestamp columns - `submission_date`, `last_update_date`, `serviced_date`. The DDL has no time-zone qualifier. We're assuming UTC, but confirm with Pallavi first - if the app writes local time, normalizing silently shifts every row. |
| `DATE` | `INT32` `DATE` | Direct. Not in `request` currently. |
| `UUID` | `BYTE_ARRAY` (`UTF8`), canonical hyphenated form | Doesn't apply to `req_id` - that's a formatted VARCHAR, not a Postgres UUID type. Keeping this row for future columns. |
| `JSON`/`JSONB` | `BYTE_ARRAY` (`UTF8`) as JSON text | Don't shred unless inner schema is stable. Not in `request` currently. |
| Geography / `POINT` | Two `DOUBLE` columns (`latitude`, `longitude`) | Doesn't apply - `request` has no geometry column. Geographic data is in `req_loc` free text (Section 5.2). |
| `ENUM` | `BYTE_ARRAY` (`UTF8`) | Doesn't apply as a native type - the DDL has a commented-out enum but `req_islead_id` is an INT FK, not a Postgres ENUM. Resolved via lookup tables (Section 4.4). |
| Arrays | Parquet `LIST<T>` | Direct. Not in `request` currently. |

### 4.3 Schema Evolution

Three cases worth calling out explicitly:

1. **Column added (nullable).** Writer emits the new column; old files return NULL for it in Athena. The important rule: new columns are NOT in the scrubbed output until they're added to the PII allowlist and reviewed. No exceptions - this is how the allowlist-not-denylist approach works.
2. **Column removed.** Writer stops emitting it. Old files still have it; new files don't. We don't retroactively rewrite. Document the removal date.
3. **Column retyped.** Parquet doesn't support in-place type changes. Write the new type into a new column (`amount_v2`), backfill, deprecate the old one. This is the strongest argument for revisiting Iceberg - it handles this natively.

Schema diffs are detected by the extractor each run, comparing `information_schema.columns` against the registered Glue schema. A diff fires an alert; schema migrations are human-approved, not auto-applied.

Vendor-facing schema is a narrower, separate contract. Internal changes that don't affect the vendor view don't require vendor notification. Changes that do require advance notice per whatever the contract says.

### 4.4 Dimension / Lookup Table Resolution *(added after DDL review)*

The original draft assumed `requests` had inline values for status, category, type, etc. The real schema has six FK columns instead: `req_status_id` → `request_status`, `req_priority_id` → `request_priority`, `req_type_id` → `request_type`, `req_cat_id` → `help_categories`, `req_for_id` → `request_for`, `req_islead_id` → `request_isleadvol`. Two options:

- **(a) Resolve at extraction time.** Join against lookup tables and write the resolved label into the lake row. Analysts, the RAG agent, and vendors get human-readable values without touching the operational DB. Downside: if a label is renamed later, historical rows keep the old value unless re-scrubbed.
- **(b) Ship the lookup tables into the lake separately.** Consumers join at query time. Keeps the resolution in one place, but every Athena query and every RAG ingestion step needs a join. Vendors would need the lookup tables too, which adds governance surface.

**Recommendation:** (a), resolve at extraction time, and additionally snapshot the lookup tables into the lake on a slowly-changing schedule for audit and rebuilding purposes. Keeps the read path simple. Needs sign-off at design review - flagged in Section 10.

## 5. PII and Privacy

PII leaking to a third-party vendor is a legal liability - Rao's framing was "we will be sued." Everything in this section follows from that. The pipeline isn't trying to be convenient; it's trying to make a leak structurally unlikely.

### 5.1 Consumer Threat Model

| Consumer | Trust | PII tolerance | Access |
|---|---|---|---|
| Internal analytics | High | Low - privacy hygiene matters but a miss isn't legally catastrophic | Athena, internal IAM |
| Internal RAG agent | High | Same as analytics; a model trained on un-redacted text can leak that content in outputs | Reads scrubbed lake |
| Third-party vendors | External | Zero - contractual and legal | Restricted serving layer (Section 5.4) |

Internal consumers read from the same scrubbed lake as vendors. They get a slightly less rich view in exchange for not maintaining two separate pipelines. If an internal use case genuinely needs un-scrubbed data, it gets a separate locked-down path - not built here.

### 5.2 Column-Level Treatment

*Updated against the received DDL for `virginia_dev_saayam_rdbms.request`.*

| Column | Treatment | Rationale |
|---|---|---|
| `req_id` | Pass through | Opaque formatted string. No PII. |
| `req_user_id` | **HMAC-SHA256 hash → `req_user_id_hashed`; drop raw value** | Even as an opaque ID, it's a stable cross-table identifier. Hashing with a KMS-managed salt makes it non-reversible while still supporting unique-requester counts and cross-partition joins. See Section 10, item 17 for the pepper rotation problem. |
| `req_for_id`, `req_islead_id`, `req_cat_id`, `req_type_id`, `req_priority_id`, `req_status_id` | Pass through (resolved to label per Section 4.4) | Category/dimension data. Not PII. |
| `req_loc` | **Coarsen to city/state → `location_bucket`; drop raw value** | Free text, but sample data shows values at city/state granularity already ("Ashburn, VA", "Charlotte", "North Carolina") - string parsing is enough, no NLP needed. Street-level detail is dropped if present. Geographic demand analysis works at this level. |
| `iscalamity` | Pass through | Boolean. Not PII. |
| `req_subj` | **Scrub via free-text redaction (Section 5.3)** | Sample data confirms it contains personal names and specific need context. Same pipeline as `req_desc`. |
| `req_desc` | **Scrub via free-text redaction (Section 5.3)** | Highest-risk field. Sample data confirms names (e.g., "Rashmi Purandare"), medical conditions, financial circumstances, immigration status. Also the field vendors are most likely to want. |
| `req_doc_link` | **Drop → emit `has_document` boolean** | Links point to uploaded documents - proof-of-need photos, ID scans. Redaction doesn't touch linked binary content. Boolean preserves analytics utility without exposing the path. |
| `audio_req_desc` | **Drop → emit `has_audio_description` boolean** | Voice is biometric PII. Boolean preserves the analytics signal. |
| `submission_date`, `last_update_date`, `serviced_date` | Pass through | Operational timestamps. Not PII. |

**Not on `request`** (were assumed in the original draft): `requester_name`, `requester_phone`, `requester_email`, `street_address`, `postcode`, `latitude`, `longitude`, `submitted_ip`. Identity fields live on `users`. If we ever join `users` into this pipeline, this section needs to be redone against those columns. Separately, `request_guest_details` has `req_fname`, `req_lname`, `req_email`, `req_phone` for guest users - explicitly out of scope here; see Section 10, item 16.

**Allowlist, not denylist.** The scrubber enumerates exactly which columns to emit and how. New columns added upstream don't appear in scrubbed output until someone explicitly adds them to the allowlist after a sensitivity review. Denylists fail open (forget a column = leak). Allowlists fail closed (forget a column = it's missing, someone notices, it gets fixed).

### 5.3 Free-Text Scrubbing

`req_desc` and `req_subj` go through full NLP-based redaction. `req_loc` goes through deterministic city/state parsing - sample data confirms it's already at a safe granularity, so entity detection isn't needed there. The redaction ruleset needs to be tuned per field; what catches PII in an open-ended need description won't necessarily catch it in a one-line location string.

Sample data confirms `req_desc` contains:
- Personal names (requester and family members)
- Phone numbers in varied formats
- Street addresses, landmarks, neighborhoods
- Medical details, financial details, immigration status, safety-sensitive situations
- Email addresses, social media handles

No automated scrubber catches everything. We use four layers:

**Layer 1: Automated redaction.** AWS Comprehend PII detection (or Google DLP - see Section 10, item 8) runs against each free-text field during Stage 2. Detected entities are replaced with type tags (`[NAME]`, `[PHONE]`, `[ADDRESS]`, etc.). Confidence threshold is configurable; default conservative - lower threshold means more redaction, which is the safer direction.

**Layer 2: Pattern-based scrubbing.** Regex rules for formats Comprehend misses - international phone numbers, country-specific ID formats common in Saayam's user base. Maintained as a versioned ruleset alongside the scrubber code.

**Layer 3: Quality gate.** A sample (default 1%, configurable) of scrubbed free-text records goes to a human-review queue before the corresponding partition is published to the vendor layer. Reviewers flag missed PII; flagged batches are quarantined and re-scrubbed before republishing. The sample rate and queue tooling are open questions (Section 10, item 9).

**Layer 4: Contractual.** Vendor contracts include best-effort scrubbing language, indemnification limits, and no-re-identification clauses. The technical layers reduce the probability of a miss; the contract bounds the liability when a miss happens anyway.

Being honest about residual risk: even with all four layers, the miss rate is above zero. The engineering posture is - if PII turns up in vendor data, it's a P0: quarantine the batch, root-cause the miss, improve the layers.

Worth raising explicitly at design review: **should free text be in the vendor product at all?** Aggregated or derived data (counts by category, embeddings, topic models) carries dramatically less legal risk than raw text. That's a business decision for Rao, not a technical one - but it's worth asking, especially now that `req_desc` and `req_subj` both go through NLP redaction with a known nonzero miss rate.

### 5.4 Third-Party Vendor Serving

**We're proposing Option C: periodic scrubbed extracts to per-vendor S3 buckets.**

Three options were discussed with Rao:

| Option | Pros | Cons |
|---|---|---|
| A: Direct S3 read in Saayam's account | Simple, no extra pipeline | Vendor sees the live lake - any scrubber miss is immediately exposed, no quality gate |
| B: Controlled query interface (Athena workgroup, API) | Per-vendor metering, row/column-level control | Ongoing cost scales with vendor query volume, more attack surface |
| C: Periodic scrubbed extracts to per-vendor buckets | Natural quality gate before each extract publishes, per-vendor isolation, easy to revoke | Vendors see stale data (last extract, not live), extra storage cost |

We're recommending C because the Layer 3 quality gate fits naturally at the extract step. A batch that fails sampling review gets quarantined before any vendor sees it. With A or B, a scrubber miss is exposed immediately with no human in the loop. The extra storage and the staleness are an acceptable trade.

**How it works:**
- One S3 bucket per vendor: `s3://saayam-vendor-<vendor_id>-prod/`.
- Cross-account access via bucket policy + IAM role assumption from the vendor's AWS account. No shared credentials.
- Scheduled daily job reads the scrubbed lake, applies any vendor-specific filters (some vendors may license a subset of the data), runs the Layer 3 sampling review, and writes Parquet to the vendor bucket if the batch passes.
- A vendor data dictionary (separate deliverable - not this design doc) describes the published schema, partition layout, update cadence, and PII guarantees. Versioned. Vendors sign on against a specific version.
- Per-vendor CloudTrail data events on the bucket. Revoking a vendor is one IAM policy change.

### 5.5 Encryption and Access Control

- **Encryption at rest.** SSE-KMS, customer-managed keys, one key per bucket (raw-staging, lake, vendor-facing). Key policies restrict decrypt to the specific roles that need it.
- **Bucket policies.** Deny by default; grant via IAM. Public access blocked. Bucket-owner-enforced object ownership.
- **Lake Formation** on the internal lake for column-level grants, if a specific internal user needs access beyond the default scrubbed view (requires explicit elevation with an audit trail).
- **Vendor buckets** via cross-account IAM assume-role. No shared credentials, no Saayam employee needing access.
- **Audit.** S3 access logging on all buckets. CloudTrail data events on raw-staging and vendor buckets (highest sensitivity). Athena query history retained 90 days minimum.
- **Erasure.** Erasure requests go through the soft-delete path; next scrubber run drops the row from the lake, next vendor extract drops it from vendor buckets. SLA: 7 days, gated by the next scheduled extract cycle. Legal may want this tighter - see Section 10, item 11.

## 6. Alternatives Considered

### 6.1 Kinesis Firehose Streaming

App emits change events; Firehose writes Parquet to S3.

- **Pros.** Minute-scale freshness. No polling.
- **Cons.** Requires app changes to emit events - cross-team dependency not currently in scope. Updates and late edits complicate the dedupe story. PII scrubbing still has to happen somewhere, and Firehose isn't a scrubber. Adds Kinesis cost.
- **Why not.** Real-time freshness is a non-goal. We'd be adding infrastructure and cross-team work for no benefit in this context.

### 6.2 Native DB Export + Nightly Full Snapshots

Daily managed export of the full `requests` table to S3.

- **Pros.** Operationally trivial. Each snapshot is consistent.
- **Cons.** Cost grows linearly with table size, every day. At 10× scale that's prohibitive. Answering "what changed yesterday" means diffing two large snapshots.
- **Why not.** Cost doesn't scale. We do use this approach for the one-time historical backfill, where the tradeoffs flip.

### 6.3 Third-Party ETL (Fivetran / Airbyte)

- **Pros.** Fastest path to first row in the lake. Vendor handles incremental, retries, schema drift.
- **Cons.** Per-row pricing is hostile to a monotonically growing table. PII scrubbing is outside the tool - we'd be paying to move raw PII into our lake and then scrubbing it ourselves. Vendor lock-in on a core pipeline.
- **Why not.** Cost trajectory plus the PII positioning. Worth reconsidering if engineering capacity becomes the binding constraint.

### 6.4 Single-Stage Pipeline (Scrub Inside Extractor)

Early drafts folded scrubbing into the extractor as a transformation step.

- **Pros.** Fewer S3 buckets, simpler diagram.
- **Cons.** No auditability - can't diff raw vs. scrubbed. No re-scrub capability if rules change. No quality gate between scrub and vendor exposure. Extractor bugs and scrubber bugs look identical and have very different blast radii.
- **Why not.** The zero-PII vendor bar requires the structural separation between raw and scrubbed. This is the most load-bearing architectural decision in the doc.

## 7. Failure Modes and Observability

### 7.1 Failure Modes

| Failure | What happens | Mitigation |
|---|---|---|
| Extractor crashes mid-write | Partial files in raw staging only; lake untouched | Watermark not advanced. Next run replays the same window. |
| Watermark update fails after write | Same window re-extracted next run | Idempotent; duplicates collapse in compaction. |
| Read replica behind / unavailable | Freshness SLA at risk | Alert if no rows when source count says there should be some. Alert if no successful run for 3+ hours. |
| Source schema change | Scrubber sees unknown column, refuses to emit it | Schema diff alert fires. New column stays out of scrubbed output until reviewed and allowlisted. This is intentional. |
| Scrubber bug - PII in lake | Internal PII exposure | Layer 3 sampling catches a fraction; secondary automated post-publish PII scan. P0 on detection. |
| Scrubber bug - PII in vendor bucket | Legal liability | Layer 3 gate must pass before vendor extract publishes. Quarantine + immediate vendor notification per contract. P0 on detection. |
| Duplicate rows from retry | Same row appears twice in a partition | Daily compaction deduplicates on `(request_id, max(updated_at))`. |
| Partial Glue partition registration | Some partitions queryable, some not | Partition projection - partitions are virtual, no registration latency. |
| Vendor extract job fails | Vendor sees stale data | Alert at 2× cadence. Vendor SLA is written to accommodate this. |

### 7.2 Observability

CloudWatch metrics, unified dashboard:

- Rows extracted / scrubbed / published per stage per run
- PII tokens detected per scrubber run, broken out by type. A sudden drop means the scrubber is broken; a sudden spike means something changed in source data.
- Sample-review queue depth and approval/rejection rate
- Run duration P50/P95/P99 per stage
- Watermark lag
- Read replica lag
- Compaction stats
- Per-vendor extract success/failure, last-publish timestamp, bytes delivered
- Athena query count and bytes scanned per workgroup (internal vs. vendor, separate metering)

**Alert thresholds:**

| Severity | Condition |
|---|---|
| Low | Single run failure - auto-retry in flight |
| Low | Watermark lag > 3 hours |
| Medium | 3 consecutive failures, or watermark lag > 6 hours |
| Medium | Schema diff detected |
| Medium | Sample-review queue exceeds configured threshold |
| High | Scrubber allowlist violation - refused to publish |
| High | PII detected on automated post-publish scan |
| High | Vendor extract published without passing sampling gate |
| High | Row-count reconciliation mismatch beyond tolerance |

PII-related highs need fast escalation. Everything else waits for business hours.

## 8. Cost Estimate

*Placeholder numbers - row count still pending from Pallavi. Engine confirmed as PostgreSQL, which doesn't change any line item.*

**Assumptions:**

- Current: 50M rows, ~150K new/day, ~300K updates/day, ~2 KB raw / ~400 bytes Parquet+Snappy per row.
- 10×: 500M rows, 1.5M new/day, 3M updates/day.
- 20 internal analyst queries/day current (200 at 10×), 5 GB / 30 GB avg scan.
- 3 vendors at current scale (10 at 10×), each pulling daily extracts.
- `us-east-1` pricing.

| Component | Current (~/mo) | 10× (~/mo) | Notes |
|---|---|---|---|
| S3 Standard (0–30d) | $2 | $15 | |
| S3 Standard-IA (30–180d) | $4 | $35 | |
| S3 Glacier Instant Retrieval (180d–2yr) | $5 | $45 | |
| S3 Glacier Deep Archive (2yr–10yr) | $5 | $50 | |
| Raw staging (30d retention) | $1 | $10 | |
| Per-vendor buckets | $3 | $30 | Replicated extracts |
| S3 requests (PUT/GET/POST) | $3 | $25 | Higher than single-stage due to scrubber + vendor extract |
| Athena scans (internal) | $5 | $90 | |
| Comprehend / DLP for PII detection | $15 | $150 | Pay per character analyzed - dominant new line item |
| Lambda / Fargate compute | $10 | $80 | Higher than single-stage due to scrubber |
| Step Functions | $2 | $10 | |
| Glue Data Catalog | $1 | $1 | |
| KMS | $2 | $10 | More keys than single-stage |
| CloudWatch | $3 | $15 | |
| **Total** | **~$60/mo** | **~$565/mo** | |

Still well under the $2K target at 10×. Comprehend is the dominant new cost compared to a simpler single-stage design - at very large scale it becomes worth considering a self-hosted redaction model, but not yet.

Not in the table: the operational DB storage savings from eventually deleting cold rows. That likely dwarfs the lake cost. Quantification pending DB unit cost from Pallavi.

## 9. Rollout Plan

**Phase 0: Prerequisites**

- Pallavi delivers schema, row count, DB engine details. *DDL for `virginia_dev_saayam_rdbms.request` received and incorporated; engine confirmed PostgreSQL. Row count, growth rate, exact version, and read replica status still pending.*
- Confirm read replica exists or stand one up.
- Confirm `last_update_date` is set on every INSERT and UPDATE. DDL shows only a `BEFORE INSERT` trigger. Add a `BEFORE UPDATE` trigger if not confirmed - don't depend on every app code path remembering.
- Provision four S3 buckets, KMS keys, IAM roles (`RequestArchiveExporterRole`, `DataEngineeringRawArchiveReadRole`, `DataAnalyticsCuratedReadRole`, `AthenaQueryExecutionRole`), Lake Formation.
- Populate Parameter Store with retention, lifecycle, and SLA values.
- Privacy and legal review of the scrubbing approach (Section 5.3). `req_doc_link` and `audio_req_desc` resolved as boolean derivations. `req_loc` resolved as city/state coarsening. Both need legal sign-off.
- Confirm `to_public` column with Pallavi (Section 10, item 15).
- Establish KMS-managed HMAC salt for `req_user_id` hashing and document the pepper rotation policy (Section 10, item 17).

**Phase 1: Collection Shadow (Weeks 1–2)**

- Extractor runs hourly on a subset, writing to raw staging only. No scrubber, no lake, no vendors.
- Goal: prove extraction is correct, measure run duration, reconcile row counts against source.

**Phase 2: Scrubber Validation (Weeks 3–4)**

- Scrubber runs against shadow raw staging, writing to a `shadow-lake/` prefix.
- Manual review of scrubbed output. Iterate on Comprehend confidence threshold, regex rules, allowlist.
- Validate the quality gate sampling pipeline end-to-end.
- No vendor exposure yet.

**Phase 3: Historical Backfill (Week 5)**

- One-time native DB export (Section 6.2) of the full `requests` table, run through the same scrubber.
- Lands as the historical partition set in the canonical lake.
- Reconcile total row count.

**Phase 4: Internal Cutover (Week 6)**

- Hourly extractor + scrubber switch from shadow to canonical lake.
- Internal analytics pointed at Athena. RAG agent team starts using the lake as a training source.
- Still no vendor exposure.

**Phase 5: Vendor Onboarding (Weeks 7+)**

- First vendor onboarded only after 2+ weeks of clean internal operation and explicit privacy/legal sign-off.
- Per-vendor bucket provisioning, IAM grants, sample-review gate live.
- Data dictionary v1.0 published.
- Additional vendors onboarded one at a time, each requiring fresh review.

**Phase 6: Operational DB Cleanup (Phase 5 + 4 weeks, gated)**

- After sustained clean operation, begin deleting closed cold rows from the operational DB in batches.
- This is the only irreversible step in the entire rollout.

**Rollback**

- Phases 1–4: trivial - delete prefixes, pause extractor. No operational impact.
- Phase 5: revoke vendor IAM grants. Vendors lose access; no Saayam impact.
- Phase 6: irreversible once rows are deleted. The gate before Phase 6 is the point of no return.

## 10. Open Questions

Tracked in the sub-issue. Resolve before or at design review.

1. ~~`requests` schema and PII column list.~~ **Received - DDL for `virginia_dev_saayam_rdbms.request` incorporated throughout.** Follow-ups still open:
   - Confirm whether `submission_date` / `last_update_date` / `serviced_date` are stored as UTC or local wall-clock. The DDL doesn't say - getting this wrong silently shifts every timestamp.
   - ~~`req_doc_link` / `audio_req_desc` treatment.~~ **Resolved:** boolean derivation. Confirmed across three independent design references. Needs legal sign-off but technical decision is closed.
   - Dimension/lookup table resolution strategy for the six FK columns (Section 4.4).
   - ~~Geographic analysis with free-text-only `req_loc`.~~ **Substantially resolved:** sample data shows city/state granularity already - string parsing is viable. Confirm this holds across the full production dataset.
2. **Row count and growth rate.** Blocking Pallavi. Cost table and Lambda/Fargate sizing both depend on this.
3. **DB version.** Engine confirmed PostgreSQL. Still need RDS vs. Aurora Postgres and major version. Blocking Pallavi.
4. **Read replica.** Does one exist, or do we stand one up? Blocking Pallavi.
5. **`last_update_date` on UPDATE.** Column exists; DDL shows no `BEFORE UPDATE` trigger. Confirm application code sets it reliably on every update path. Blocking Pallavi.
6. **Final vendor access model.** Draft proposes Option C. Confirm at design review.
7. **Free text in vendor product?** Raw `req_desc` / `req_subj` vs. aggregated/derived only. Business decision for Rao. Substantially changes legal exposure.
8. **PII redaction tool.** Defaulting to Comprehend for AWS ecosystem fit. Benchmark against Google DLP before final decision.
9. **Sample-review staffing.** Who reviews the Layer 3 queue, at what cadence, with what tooling?
10. **Iceberg vs. plain Parquet.** Starting on Parquet. Revisit at 6 months.
11. **Erasure SLA.** Draft proposes 7 days. Legal may need tighter.
12. **Athena workgroup scan limits.** Per-query and per-day caps to prevent runaway cost.
13. **Lookup table resolution strategy** (Section 4.4). Resolve at extraction time vs. ship separately vs. both. Needs sign-off at design review.
14. ~~**`req_doc_link` / `audio_req_desc` handling.**~~ **Resolved:** boolean derivation. Technical decision closed; legal sign-off pending.
15. **`to_public` column.** In mock dataset schema, absent from Pallavi's DDL. Confirm with Pallavi before implementation. Blocking Pallavi.
16. **`request_guest_details` scope.** Related table with `req_fname`, `req_lname`, `req_email`, `req_phone` for guest users. Include in this pipeline (with full PII treatment) or a separate design doc? Needs a call before any consumer tries to analyze guest vs. registered-user requests.
17. **HMAC pepper rotation policy.** If the KMS salt for `req_user_id_hashed` is ever rotated, old and new hashes are inconsistent and can't be joined across partitions. Options: (a) never rotate, (b) rotate and re-hash all historical partitions, (c) rotate with version suffix and key-version column. Needs a decision before implementation.
18. **Operational DB deletion grace period.** Proposals range from 7 to 90 days. Confirm at design review.

## 11. Notes for Generalizing to Other Tables

Out of scope here, but the design was built to generalize:

- The three-stage pattern (collection → scrubbing → serving) works for `volunteers`, `donations`, `matches`, and conversations.
- S3 layout (`s3://lake/<table>/year=/month=/day=/`) is the same across all tables.
- The extractor and scrubber are parameterized by source table, watermark column, partition column, and PII allowlist. Adding a table is a config change, not new code.
- The vendor data dictionary covers all licensed tables, not just `requests`.
- Conversations will need extra attention on free-text scrubbing - that table is mostly free text.

When other tables get their own design docs, this one is the cross-cutting reference for file format, partitioning convention, three-stage pipeline, PII framework, and vendor access model. Table-specific docs only need to cover what's actually different.
