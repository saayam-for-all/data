# Design Doc: Periodic Archival of `requests` Table to S3

**Status:** Draft for review
**Owner:** Prajakta
**Related issue:** #175


## 1. Problem Statement and Goals

### Why
The `requests` table grows monotonically and sits on the hot matching path. Most rows are rarely touched once a request is closed (`serviced_date` is set), but they remain in the operational database indefinitely. This causes three problems:

- Query performance on the matching path degrades as the table grows.
- Operational database storage cost scales poorly for data that is effectively cold.
- Analytics workloads (fulfillment SLAs, geographic demand, volunteer reach, donor reporting) cannot safely run against production without risking the live system.

### Goal
Build a periodic process that moves closed, aged-out request records from the operational database into S3, in a format that is queryable via Athena/Glue, while keeping the operational database lean and fast.

## 2. Requirements

 Which Data Moves, and How Often?

- **What gets moved:** Requests that are fully closed (the `serviced_date` column has a value) and are older than 90 days. 
- **How often:** Once a day, at night when traffic is low
- **How it works:** We only pull rows that are new or changed since the last time we ran — not the whole table every time. We track this using the `last_update_date` column, which tells us when a row was last touched. Think of it like a bookmark — each run picks up where the last one left off.
- **If someone edits an old row after it's already been moved:** We re-export it and overwrite the old copy in S3. No duplicates.
- **If someone deletes a row from the database:** We don't automatically delete it from S3. Still an open question — needs a team decision.
- **How long we keep it:** Around 10 years. All config values like this come from AWS Parameter Store, not hardcoded, so they can be changed without redeploying anything.

---

## 3. Proposed Architecture

How Does It Actually Work?

**The flow, step by step:**

Every day, a timer fires → kicks off a small program → that program reads new/changed rows from a copy of the database (not the live one, so it doesn't slow down the app) → saves them as files in S3 → updates a catalog so analysts can find and search the data → analysts query it through Athena (Amazon's query tool for S3 data).



**Why we made the choices we did:**

**Reading from a database copy (read replica), not the live database**
The live database is what runs the app. Running a big data export against it would slow things down for real users. The read replica is an exact copy that's only used for things like this  we can hammer it without affecting anyone.

**Running a simple daily SQL query instead of AWS DMS or CDC**
- AWS DMS is built to continuously sync two databases in real time. We only need to move data once a day  running DMS for that is like renting a full-time delivery driver to drop off one package a week.
- CDC (Debezium) captures every single change as it happens, in real time. Again — we don't need real time. Daily is fine.
- A simple SQL query does the job cleanly, is easy to debug, and costs way less.

**Saving files as Parquet instead of CSV**
Parquet stores data by column, not by row. When Athena searches through it, it only reads the columns it needs  not the whole file. This makes queries faster and cheaper. CSV reads the whole file every time regardless.

**Organising files by submission date**
We group files by the date a request was submitted. That date never changes once it's set, so a file will never need to move to a different folder. If we organised by status instead (open/closed), a row could change status and end up in the wrong folder.

**Storage lifecycle — where the data lives over time:**
- First 30 days in S3: stays readily accessible (Standard tier)
- After 30 days: moves to cheaper storage (Standard-IA — still accessible, just costs less)
- After 1 year: moves to Glacier (very cheap, takes a minute to retrieve — fine for old compliance data)
- After 10 years: gets deleted (tentative - may change)

---
## 4. Schema Handling

18 columns total. Database is PostgreSQL (exact version unknown — likely version 12 or newer based on the features it uses).

| Column | Type | What we do with it |
|---|---|---|
| `req_id` | string | Keep as-is — it's the unique ID for each request |
| `req_user_id` | string | Contains personal info — scramble it (see Section 5) |
| `req_for_id` | int | Contains personal info — scramble it |
| `req_islead_id` | int | Contains personal info — scramble it |
| `req_cat_id` | varchar(50) | Keep as-is |
| `req_type_id` | int | Keep as-is |
| `req_priority_id` | int | Keep as-is |
| `req_status_id` | int | Keep as-is |
| `req_loc` | string | Personal info — keep, but only city/state level |
| `iscalamity` | bool | Keep as-is |
| `req_subj` | string | Personal info — delete this column entirely |
| `req_desc` | string | Personal info — delete this column entirely |
| `req_doc_link` | string | Points to a document that may have personal info — delete |
| `audio_req_desc` | string | Personal info — delete this column entirely |
| `submission_date` | timestamp | Keep — used to organise the files |
| `serviced_date` | timestamp | Keep — tells us if a request is closed |
| `last_update_date` | timestamp | Keep — our bookmark for tracking what's new |
| `to_public` | bool | Keep as-is |

**If columns change in the future:**
- New column added: fine, old files just won't have it  that's expected
- Column removed: it stays in old files, just stops appearing in new ones
- Column type changes (e.g. number becomes text): needs a manual decision  too unpredictable to handle automatically

**Note on timestamps:** The data doesn't have timezone information attached. I am, assuming UTC for now. Needs confirmation from the team.

---
## 5. PII and Privacy

This is EU data (Ireland region), so GDPR applies. 

| Column | Decision | Why |
|---|---|---|
| `req_user_id`, `req_for_id`, `req_islead_id` | Scramble (one-way hash) | We need to count things like "how many unique users did volunteer X help" — but we don't need to know *who* those users are. Scrambling the ID keeps the counting ability without revealing identity. Dropping it entirely would break those analytics. Keeping it raw would expose personal info to anyone who can run a query. |
| `req_loc` | Keep — city/state only | Geographic reporting (e.g. "which areas have highest demand") is one of the main reasons this archive exists. Dropping it defeats the purpose. We only need city/state — anything more specific than that is unnecessary. |
| `req_subj`, `req_desc`, `audio_req_desc` | Drop entirely | These are free-text fields where people write anything — names, medical situations, personal circumstances. There's no reliable way to automatically scan and remove personal details from free text. The category and type fields already cover what analytics needs. |
| `req_doc_link` | Drop | This is a link to an uploaded file that almost certainly contains personal info. Even if we scrub everything else, leaving this link in gives anyone with access a path to that personal data. |

**Access control:** The data is encrypted at rest (using AWS KMS keys). Anyone who accesses it gets read-only — no one can edit or delete directly from S3 outside of the pipeline itself. All access is logged.
*This section needs a sign-off from whoever is responsible for data compliance — not just engineering.*

## 6. Alternatives Considered

**AWS DMS (Database Migration Service)**
This is Amazon's tool for syncing databases. It's powerful but built for either one-time migrations or continuous live replication. We're doing neither  we just need a simple daily batch job. Using DMS would mean running and paying for a dedicated replication server around the clock, for a job that takes a few minutes once a day. Not worth it.

**Kinesis Firehose (real-time streaming)**
This is Amazon's tool for handling live data streams. To use it, you need a continuous stream of changes coming in  which would mean building a whole extra piece of infrastructure (CDC/Debezium) just to feed it. We don't need real-time, so we'd be building a lot of extra stuff for no benefit.

**Fivetran or Airbyte (off-the-shelf connectors)**
These are third-party tools that connect databases to data warehouses with minimal setup. The catch: they charge based on how much data you move costs go up as the table grows, which is the opposite of what we want. We'd also still need to write our own PII-scrubbing logic on top, so we're not saving as much engineering effort as it looks like upfront.

---
## 7. Failure Modes and Observability

**Partial failures (job crashes halfway through):**
Files are written to a temporary staging folder first. They only get moved to the real location if the entire batch finishes successfully. If the job crashes halfway, the staging files are just abandoned — the real data in S3 is untouched. Nothing half-baked ever gets seen by analysts.

**Running it again after a failure:**
The bookmark (watermark) only gets updated after a successful run. If a run fails, the next run starts from the same point — so nothing gets skipped or duplicated.

**Alerts:**
- If a scheduled run doesn't complete on time → alert fires
- If the data in S3 goes stale beyond the freshness limit → alert fires

**Who's responsible:** Data engineering team (needs explicit confirmation).

---

## 8. Cost Estimate

Region is confirmed as `eu-west-1` (Ireland).
Note: The only data available is a 290-row test file — not real production data. 
I'm not familiar enough with AWS cost estimation to give accurate numbers here, so I've left this section incomplete. 

## 9. Rollout Plan
We're doing this in stages — deliberately. 

1. **Test run first** — run the whole pipeline but write to a test S3 bucket only. Nothing in production changes. Verify the output looks right: right rows, right columns, PII correctly handled.
2. **Move the old data** — once the test run passes, do a one-time move of all the existing old data (everything already past the cutoff date) into the real S3 archive.
3. **Switch on the daily job** — from this point on, the pipeline runs every night automatically. Analysts can now query S3 via Athena instead of production.
4. **Retire any old process** — if there's an existing manual export or workaround someone's been using, shut it down once the new pipeline is confirmed working.
5. **Delete from the live database** — this is the last step and the only one that can't be undone. We only do this after the pipeline has been running stably for a while and has explicit sign-off.

---

## 10. Open Questions
1. **PostgreSQL version** — engine is confirmed PostgreSQL, likely version 12+, but exact version still unknown. 
2. ~~**AWS region**~~ — **needs to be confirm: `eu-west-1` (Ireland)**
3. **Exact retention duration** 
4. **Real row count and growth rate** — needed to complete the cost estimate (Section 8).
5. **What happens when a row gets deleted from the database** — does it also get deleted from the S3 archive, or do we keep it? 
6. **PII decisions sign-off** — Section 5 is a proposal, not a final call. Needs review from whoever owns data compliance.
7. **Scrambling user IDs — one-way or reversible?**
8. **Who owns this pipeline on-call?** — data engineering team assumed, but needs to be confirmed explicitly.
9. **Timezone on timestamps** — assuming UTC for now, needs confirmation.

