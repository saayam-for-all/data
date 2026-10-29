# Request archival to S3: approach and current state

Issue #416. Last updated 27 October 2026.

The pipeline described here is built and was demonstrated on 15 October. The
review that followed changed part of the design, and the remaining work is now
split into seven subtasks. This is the document to read before picking up any
of them.

---

## 1. What this pipeline does

It copies rows from the `requests` table in the application database into S3 on
a schedule. It is a copy, not a move. Nothing is removed from the database by
this pipeline.

The long-term intent matters for every design decision below: once old requests
start being deleted from the database, the file in S3 becomes the only copy.
That is why nothing is omitted from the export without a reason, why a row must
never be silently dropped, and why anything masked has to be right the first
time.

**The only statement this pipeline issues against an application table is
`SELECT`.** It does not insert, update, delete, truncate or alter anything in
the application schema, and it holds no locks on application tables. The two
tables it writes to are its own bookkeeping tables, created by the DBA for this
purpose.

---

## 2. What is built and verified

A Lambda function, deployed in the Saayam dev account, running against the real
dev database.

One run does this:

1. Reads the database credentials from Parameter Store.
2. Connects, and reads the watermark: the timestamp the previous run stopped at.
3. Selects only the rows changed since then, up to a bound five minutes in the
   past.
4. Applies the PII rules as part of that `SELECT`, so the masking happens inside
   the database rather than in the function.
5. Writes a gzipped CSV to S3 under `raw/requests/ingest_date=YYYY-MM-DD/`.
6. Only after S3 confirms the upload, advances the watermark and writes a row
   to the run log.

```
read watermark  ->  select new rows  ->  upload to S3  ->  advance watermark
 where we               PII applied        partitioned       and log the run
 stopped last           in SQL             by date
       ^                                        |
       +--------- a crash before this point ----+
                  leaves the watermark unmoved
```

The order is the whole design. Because the watermark moves last, a run that
dies partway through leaves it where it was, and the next run recomputes the
identical window and writes to the identical file name, overwriting rather than
duplicating.

### Two mechanics worth understanding before changing the extract

**The window is half-open: `(lo, hi]`.** The lower bound uses `>` and the upper
bound uses `<=`. A row whose timestamp falls exactly on a boundary therefore
belongs to exactly one run, never both and never neither.

**The upper bound is five minutes in the past, not now.** A row's
`last_updated_at` is set when the statement runs, but the row only becomes
visible to other sessions when the transaction commits, which is later. If a
run read up to `now()`, a row stamped just before that bound but committed just
after it would be invisible at read time and then permanently below the new
watermark. It would never be exported, and nothing would report an error. The
lag has to be longer than the longest write transaction in the application; five
minutes is a wide margin.

### What it has actually been observed doing

On 15 October a single request was filed in the app during the review. The next
run exported exactly that one row out of 196 then in the table, and the run
after that reported `nothing_to_do`. The run log holds the whole sequence: idle,
one row, idle, idle.

Recovery has also been observed for real, not just reasoned about. While the S3
gateway endpoint was misconfigured, uploads failed; those runs are in the log as
failures with their reasons, the watermark stayed where it was, and once the
network problem was fixed the next run picked up from the same point with
nothing lost and nothing duplicated.

---

## 3. What changed after the 15 October review

Rao reviewed the demo and asked for the following. None of it is in the code
yet; it is the content of the subtasks in section 4.

**One file, not six.** The current version exports six tables: `requests` plus
five lookup tables. It becomes a single data movement, `requests` only.

**No bare identifiers in the output.** Today a row in the file says
`req_status_id = 1`. It should say `Open`. So the lookup tables stop being
exports of their own and become joins inside the extract query. The export
changes from reading one table to reading several and combining them.

**Mask the request description.** `req_desc` is free text. This is the one
genuinely hard item and it has a subtask of its own, plus section 5 below.

**CSV stays.** No change to the file format for now.

**The location is fine as it is,** from a privacy point of view. Rao is
comfortable keeping `req_loc`. Separately, it is stored as PostGIS EWKB hex and
is unreadable in the file, which is a usability problem rather than a privacy
one, and worth fixing.

**One concern closed itself.** The `to_public` flag turned out to belong to a
forum feature that does not exist yet, not to a privacy setting. No work needed.

**The function gets a `DE` prefix,** as suggested by Sugandha and team. Renaming
a Lambda means creating a new function, not editing the existing one, then
removing the old one once the new one is confirmed working.

---

## 4. The seven subtasks

| # | Issue | Task |
|---|---|---|
| 1 | #573 | Identify the columns that join to other tables |
| 2 | | Create a new Lambda to export one table instead of six |
| 3 | | Decode the location into readable coordinates |
| 4 | | Remove the superseded lookup-table exports from S3 |
| 5 | | Detect and mask PII in the free-text description |
| 6 | | Test the new pipeline end to end |
| 7 | #587 | Generate mock data for local development and testing |

Task 1 blocks task 2. Task 6 comes last. The rest can run in parallel.

**1. Identify the columns that join to other tables.** List every column in
`requests` that refers to another table, which table and column it matches on,
and how many requests hold a value that matches nothing. The count of
non-matching rows matters as much as the mapping, because those are the rows at
risk when the join is written. A committed schema file on #573 gives the
declared foreign keys so this can be verified rather than guessed.

**2. Create a new Lambda to export one table instead of six.** Export
`requests` only, with the referenced values joined in and written out as
readable words instead of identifiers. **Every join must be a `LEFT JOIN`.** An
inner join silently drops any request whose reference is null or broken, and the
row count looks small rather than wrong. In dev, 218 of 221 requests have a null
`lead_volunteer_id`, so an inner join on that column returns 3 rows and nothing
reports an error. In an archive that eventually becomes the only copy, a row
disappearing quietly is unrecoverable.

**3. Decode the location into readable coordinates.** `req_loc` comes out of the
database as `0101000020E6100000...`, which is PostGIS EWKB in hex. Anyone opening
the file in Athena or Excel sees a wall of hex. It should read as
`POINT(-74.006 40.7128)`. This is about the file being usable; Rao is content
with keeping the location itself.

**4. Remove the superseded lookup-table exports from S3.** The five lookup
tables currently have their own files in the bucket, plus their own watermark
and run-log rows. Once task 2 lands these are stale, and the risk is somebody
finding them later and assuming they are current.

**5. Detect and mask PII in the free-text description.** See section 5. This one
is weeks, not days, and is as much a set of decisions as a piece of code.

**6. Test the new pipeline end to end.** Check that the output matches the
source: same row counts, no row appearing twice, nothing missing between one run
and the next, masking applied, joins resolving, and a repeated run producing an
identical file. Best done by someone other than whoever wrote the code.

**7. Generate mock data for local development and testing.** Volunteers do not
have access to the live database, and no real request data leaves it. Realistic
generated data is what lets anyone work on tasks 2, 3, 5 and 6 locally.

---

## 5. Why task 5 is the large one

For a column like `creator_id` the rule can be "always hash this", because the
column's meaning is known in advance. A description is whatever a person typed,
so the only way to find personal details in it is to read the text and judge.
That is a different kind of problem.

The current code already has a pattern scrubber. It finds emails, phone numbers,
card numbers, SSNs and URLs, replaces each with a tag, and works. What no
pattern can do is find a name, in any language, because nothing distinguishes a
name from an ordinary word by shape.

The tools that do find names are measurably worse at it for non-English names.
One was tested here on thirteen names: it found all four Western ones and missed
three of the nine others, all three African. Thirteen cases is a small sample,
and the direction is what you would expect from models trained on English news
text, but it matters here because of who Saayam serves. If detection is weaker
on non-Anglo names, the people whose details end up permanently in the archive
are disproportionately the people the organisation exists to protect.

Redaction also fails in the other direction, and permanently. In testing, a
sentence containing a reference number formatted like a phone number was
redacted, which destroyed the only useful content in it. Once rows are deleted
from the database there is no way to get that back.

So three things need deciding, not just building:

1. **What does the detection.** Patterns alone, a lookup against our own user
   names, or a service like Amazon Comprehend. Presidio is the obvious library
   but it does not fit: the package measures 374MB against Lambda's 250MB
   unzipped limit, so it would force a move to container images.
2. **Whether an unredacted copy is kept** somewhere restricted, so a detection
   bug can be fixed later rather than discovered too late. Recommendation: yes.
3. **Where the scrubbing happens.** Cleaning the text when the request is
   submitted is better than cleaning it when the row is archived: the live
   database is clean too, nothing is lost to a false positive, and the archive
   inherits the fix. Worth putting to the GenAI team as the first option rather
   than the fallback.

The most useful early contribution to this task is not code. It is writing
fifty or so realistic request descriptions with personal details embedded the
way people actually write them, and labelling which ones should be caught.
Without that set, none of the three options above can be measured. It needs
judgement about how people write rather than engineering, which makes it a good
first piece for whoever joins.

---

## 6. Still outstanding outside the team

Not blocking the subtasks, but blocking the pipeline running unattended:

- **Scheduler role trust policy.** The EventBridge Scheduler role does not yet
  trust `scheduler.amazonaws.com`, so scheduled invocation fails. Manual
  invocation works.
- **SSM interface endpoint, or a NAT.** Without a route from the VPC to
  Parameter Store, the deployment currently passes the database credentials in
  as a Lambda environment variable. That is evaluation only: an environment
  variable is plaintext to anyone with `lambda:GetFunctionConfiguration`, a much
  wider group than can decrypt a SecureString.
- **`ssm:PutParameter`,** so the hash salt can live in Parameter Store as a
  SecureString instead of an environment variable. The ID hashes are
  pseudonyms, not anonymised values, and with only tens of users in a
  predictable ID format an unsalted or publicly-salted hash is recoverable by
  enumeration in well under a second.

---

## 7. Where the code is

| What | Path |
|---|---|
| Lambda | `data-engineering/src/requests_archive/` |
| Deploy script | `data-engineering/scripts/deploy/deploy_requests_archive.sh` |
| State table DDL | `data-engineering/infrastructure/db/requests_archive/001_archive_state_tables.sql` |

`README.md` in the Lambda folder covers the layout, the three state-store
backends, how to deploy and invoke it, and the two things in this schema that
will bite anyone changing the extract.

The code for the new approach belongs to subtask 2 and is a new function, not
an edit of this one.

## 8. The other implementation of this issue

`data-engineering/infrastructure/db/requests_s3_archive/` is a separate
implementation of #416, added on 5 October, which performs the same export from
inside Postgres using `pg_cron` and `aws_s3.query_export_to_s3` rather than
from a Lambda. It keeps its own bookkeeping tables in an `archive` schema,
separate from the two above.

The two have not been reconciled and I am not assuming which should win. The
differences that matter to whoever decides:

- It exports `SELECT * FROM public.requests` with no masking, so every column
  including `req_desc` and the three user IDs goes to S3 raw. The masking Rao
  asked for on 15 October would have to be added.
- It targets `public.requests`. The live dev database uses
  `virginia_dev_saayam_rdbms`.
- It needs an IAM role attached to the RDS instance, the `aws_s3` extension and
  `pg_cron` enabled in the DB parameter group. None of those are in place.
- Running inside the database avoids the VPC endpoint, SSM routing and
  scheduler trust-policy problems entirely, which were most of the two weeks
  spent getting the Lambda deployed. That is a real advantage.

This needs a decision from Rao or Sugandha rather than being settled by which
PR merges first.
