# PII masking evaluation for request free text (Issue #585)

Status: **incomplete**. Approaches A and B are measured. Approach C (Amazon
Comprehend) is **NOT MEASURED** because no AWS credentials, IAM permission or
approval for billable calls were available. The recommendation below is
therefore provisional on Comprehend.

Related work: [Issue #585](https://github.com/saayam-for-all/data/issues/585),
draft [PR #659](https://github.com/saayam-for-all/data/pull/659), and the
existing scrubber from Issue #416 (`SCRUB_PATTERNS` in
`data-engineering/src/requests_archive/lambda_function.py` on branch
`hpant5_416_archive_datapipeline_rdbms_s3`, commit `97f1dff`, not merged).

Raw results: [`pii_masking_evaluation_585_results.json`](pii_masking_evaluation_585_results.json),
generated 2026-11-10 16:29 UTC.

## 1. Executive summary

- The existing pattern matching (Approach A) caught **16 of 47** PII texts in the
  synthetic test set and wrongly redacted **1 of 27** clean texts. It finds no
  names, no addresses, no non-US phone formats and no spelled-out numbers.
- Adding a full-name lookup against the `users` table (Approach B) raised this to
  **25 of 47** with no extra false positives. It only finds names that are in the
  table: 12 of 13 such names versus 0 of 9 names of people who are not users.
- Matching single first or last names (B, token mode) added one catch but
  wrongly redacted **6 of 27** clean texts ("Grace period", "Victoria Park",
  "We moved from Jordan"). Token mode is not recommended.
- Amazon Comprehend (Approach C) is **NOT MEASURED**. Only its price is known:
  USD 0.30, 3 and 30 per month for 1k, 10k and 100k requests (texts up to 300
  characters, one call per request). `DetectPiiEntities` supports English and
  Spanish only.
- A supplementary Approach D (wider patterns plus users lookup plus phrases like
  "my name is") caught **45 of 47** with no false positives on this set, but its
  rules were written by the same author as the test set. On an independent set
  written by another contributor (PR #659's fixture) it caught **31 of 40**,
  again with no false positives, against 14 of 40 for A.
- Every local approach took under 0.1 ms per text (median 9 to 61 µs on a
  laptop) and needs only the Python standard library.
- Recommendation: improve the patterns and add a full-name users lookup now
  (no new dependencies, no AWS cost). Decide on Comprehend only after an
  approved, measured run, because names of non-users with no cue phrase remain
  the main gap and that is what Comprehend would be expected to close.

## 2. Problem statement

`req_subj` and `req_desc` on the `requests` table are free text. Requesters type
phone numbers, emails, addresses and names into them, and column-level masking
cannot see inside a text field. Before archiving requests to S3, personal details
should be removed. Issue #585 asks for a measured comparison of three
approaches, so the implementation is built on something known to work:

1. Pattern matching only (already in the #416 archive Lambda).
2. Pattern matching plus a lookup against names in the `users` table.
3. Pattern matching plus Amazon Comprehend PII detection.

It also invites a better approach with equal or wider coverage, asks for
Presidio's size to be confirmed independently, and requires that nothing heavy
is imported, because detection will run as a method inside a Lambda.

## 3. Test dataset details

| Item | Value |
|---|---|
| File | `tests/fixtures/pii_evaluation/request_texts.jsonl` |
| Generator | `scripts/build_pii_evaluation_dataset.py` |
| Texts | 74 (47 with PII, 27 clean) |
| Labelled entities | 60: PERSON 22, PHONE 18, ADDRESS 9, EMAIL 5, NATIONAL_ID 3, CARD 2, URL 1 |
| Languages | English 61, Spanish 5, mixed 4, Hindi 2, French 1, Chinese 1 |
| Users fixture | `tests/fixtures/pii_evaluation/synthetic_users.csv`, 35 synthetic users |

Each record has an ID, the text, a `contains_pii` flag, the language, entity
types, tags, and exact character spans for every entity. For names, it also
records whether the person is in the users table. Tests check that every span
matches its text, that spans do not overlap, and that the committed files match
the generator output.

Coverage includes:
- **Phone numbers:** US numbers in six formats, plus UK, Indian, Mexican,
  Pakistani and Costa Rican numbers.
- **Spelled-out details:** two phone numbers written as words, and an obfuscated
  email ("name dot surname at example dot com").
- **Addresses:** US, French, Spanish, Indian and Costa Rican formats.
- **Names:** Indian, Chinese, Vietnamese, Mexican, Nigerian, Arabic, Russian,
  French, Ghanaian, Japanese, Persian and Pakistani names, including names with
  accents, a hyphen, and Devanagari and Chinese script.
- **Other:** texts with several entities, and humanitarian scenarios (food,
  shelter, medicine, rides, school supplies).

The 27 clean texts are mostly traps: dates, times, order and tracking numbers,
amounts, public URLs, place names, and words that are also first names
("Grace", "May", "Mark", "Victoria", "Jordan").

All data is synthetic. Emails use `example.com`, `example.org` and `example.net`,
card numbers are standard test numbers, and UK numbers use Ofcom drama ranges.

The PR #659 fixture (60 texts, 40 PII, 20 clean, document-level labels only) was
used as a **held-out set**. It was written by a different contributor and is read
from a local download (commit `cfcbf71`, SHA-256 `3eb1bfe7…32b5`); it is not
copied into this branch.

## 4. Three approaches evaluated

All approaches return character spans. Overlapping spans are merged (the longest
one decides the label, with ties broken by a fixed priority), and every approach
redacts the same way: each span becomes a `[LABEL]` tag such as `[PHONE]`.

| Key | Approach | Implementation |
|---|---|---|
| A | Existing patterns only | The five #416 regular expressions, copied verbatim. A test checks the span version redacts all 74 texts exactly as the existing sequential scrubber does (0 differences). |
| B | A + users name lookup | Builds a set of normalised full names from the users table (case and accents ignored) and matches 2–5 word sequences. Token mode also matches single first or last names when capitalised. |
| C | A + Amazon Comprehend | `DetectPiiEntities` adapter. The client is passed in, `boto3` is imported only when a client is created, DATE_TIME and AGE are ignored, and the minimum score is 0.5. **Not run.** |
| D | Supplementary | Wider phone, address, ID, card (Luhn check), social-profile URL and spelled-out number patterns; B's full-name lookup; and names following cues such as "my name is", "my grandmother", "soy" or "contact". |

Approach D was built because the issue invites a better approach. It is reported
separately and is not presented as one of the three required approaches.

Relation to PR #659: this evaluation does not copy its code. It reuses the #416
patterns that the issue says are already in the pipeline (PR #659 wrote new
ones), scores names separately for users and non-users (PR #659's lookup list
was the fixture's own names), adds entity-level metrics, and uses PR #659's
fixture as independent held-out data.

## 5. Benchmark methodology

- Every approach runs on the same 74 texts in one process.
- **Document level:** a text is "caught" if at least one span is found. True
  positive is a PII text caught, false negative is a PII text missed, false
  positive is a clean text wrongly redacted, true negative is a clean text left
  alone.
- **Entity level:** a gold entity is "detected" if any predicted span overlaps it
  and "fully redacted" if every character is covered. A predicted span that
  overlaps no gold entity is "spurious".
- **Latency:** time to detect and redact one text, measured with
  `time.perf_counter_ns`. 2 warm-up passes, then 50 timed passes over 74 texts
  (3,700 samples per approach). p95 is nearest-rank.
- **Initialisation:** timed separately (regex compilation and name index build)
  and excluded from per-text latency.
- **Scaling:** the name index was built from 1k, 10k and 100k generated users
  (seed 585), measuring build time, peak memory (`tracemalloc`) and lookup time.
- **Environment:** Python 3.12.7 on macOS 26.3.1, Apple Silicon (arm64). Laptop
  numbers are not Lambda numbers.
- Accuracy is deterministic; repeated runs give identical results (tested).

## 6. Comparison table

Synthetic set (74 texts: 47 PII, 27 clean):

| Approach | Caught | Missed | Clean wrongly redacted | Precision | Recall | F1 | Entity recall | Median µs | p95 µs |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A. Existing patterns | 16 | 31 | 1 | 0.941 | 0.340 | 0.500 | 0.300 | 9.3 | 13.0 |
| B. + users lookup (full names) | 25 | 22 | 1 | 0.962 | 0.532 | 0.685 | 0.500 | 27.6 | 38.0 |
| B. + users lookup (token mode) | 26 | 21 | 6 | 0.812 | 0.553 | 0.658 | 0.550 | 28.2 | 39.0 |
| C. + Amazon Comprehend | NOT MEASURED | | | | | | | | |
| D. Supplementary (optimistic) | 45 | 2 | 0 | 1.000 | 0.957 | 0.978 | 0.950 | 60.5 | 83.3 |

Held-out PR #659 set (60 texts: 40 PII, 20 clean, document level only):

| Approach | Caught | Missed | Clean wrongly redacted | Recall |
|---|---:|---:|---:|---:|
| A | 14 | 26 | 0 | 0.350 |
| B (full names) | 14 | 26 | 0 | 0.350 |
| B (token mode) | 19 | 21 | 0 | 0.475 |
| C | NOT MEASURED | | | |
| D | 31 | 9 | 0 | 0.775 |

None of the held-out names are in the synthetic users table, so B's full-name
lookup adds nothing there. This is the "requester names someone who is not a
user" case. Token mode's five extra catches come from first names that happen to
match synthetic users.

## 7. Accuracy and false-positive analysis

Entities detected out of the labelled total (synthetic set):

| Type | Total | A | B full | B token | D |
|---|---:|---:|---:|---:|---:|
| PERSON | 22 | 0 | 12 | 14 | 19 |
| PHONE | 18 | 10 | 10 | 10 | 18 |
| ADDRESS | 9 | 0 | 0 | 1 | 9 |
| EMAIL | 5 | 4 | 4 | 4 | 5 |
| NATIONAL_ID | 3 | 1 | 1 | 1 | 3 |
| CARD | 2 | 2 | 2 | 2 | 2 |
| URL | 1 | 1 | 1 | 1 | 1 |
| **Total detected** | 60 | 18 | 30 | 33 | 57 |
| Fully redacted | 60 | 17 | 29 | 29 | 56 |
| Spurious spans | | 1 | 1 | 6 | 0 |

Names in the users table: B found 12 of 13. Names not in the table: B full found
0 of 9, B token 2 of 9, D 7 of 9.

Findings by category (texts flagged out of texts with that tag):

| Category | Texts | A | B full | B token | D |
|---|---:|---:|---:|---:|---:|
| International phone | 7 | 1 | 1 | 1 | 7 |
| Spelled-out numbers | 3 | 0 | 0 | 0 | 3 |
| Non-English text | 9 | 0 | 2 | 2 | 5 |
| Third-party names | 9 | 3 | 3 | 4 | 8 |
| Mixed language | 4 | 2 | 2 | 2 | 3 |
| Name-like words (clean, should be 0) | 5 | 0 | 0 | 5 | 0 |

False positives:
- **A and B full** redact a public link in C20 (`https://www.example.org/relief`),
  because the existing URL pattern removes every link.
- **B token** also redacts "May" (C11), "Grace" (C12), "Victoria" (C13),
  "Jordan" (C14) and "Mark" (C24), because these are users' first names.
- **D** has none on either set; it only redacts social-profile links.

Remaining misses for D:
- Synthetic set: a Chinese name with no spaces between words (P24), a name at
  the start of a sentence with no cue (P26), and a Hinglish name after "Mera naam"
  (P47; the text is still caught through its phone number). The Spanish address
  in P31 is only partly redacted: "2º izquierda, Madrid" stays visible.
- Held-out set: 7 of 9 misses are names of non-users at the start of a sentence
  with no cue ("Priya Nair needs a ride…"). One is "I am called Samira El-Amin",
  a cue D does not know. One is "passport ID is AB1234567", a wording D's ID
  rule does not accept. D was not changed after scoring the held-out set.

The drop for D from 0.957 recall on its own set to 0.775 on the held-out set
shows how optimistic the author-written set is. Treat 0.775 as the more
realistic figure for D.

## 8. Latency comparison

Per text, detection plus redaction, 3,700 samples each:

| Approach | Init (ms) | Mean µs | Median µs | p95 µs | Max µs | 50 passes total (s) |
|---|---:|---:|---:|---:|---:|---:|
| A | 0.18 | 9.5 | 9.3 | 13.0 | 28.7 | 0.036 |
| B full | 0.73 | 28.3 | 27.6 | 38.0 | 56.5 | 0.106 |
| B token | 0.73 | 28.9 | 28.2 | 39.0 | 68.6 | 0.108 |
| D | 2.69 | 65.4 | 60.5 | 83.3 | 3,880.2 | 0.243 |
| C | NOT MEASURED | | | | | |

D's maximum is a single outlier; its median and p95 are representative. B's
initialisation includes reading the 35-row users CSV. The full benchmark,
including the scaling test, ran in 6.6 s.

Name index scaling (generated users):

| Users | Index build (s) | Peak memory (MB) | Lookup median µs | Lookup p95 µs |
|---:|---:|---:|---:|---:|
| 1,000 | 0.052 | 0.7 | 17.5 | 24.4 |
| 10,000 | 0.494 | 4.0 | 17.0 | 23.7 |
| 100,000 | 5.184 | 29.0 | 17.6 | 25.4 |

Lookup time does not grow with table size because it is a set lookup. Build
time grows linearly.

Not measured: time to query the names from the database (no database access was
used), Comprehend latency, and timings on Lambda hardware.

## 9. Cost estimates

Measured inputs: synthetic texts are 12–102 characters (mean 67.6), so every
Comprehend call bills the 3-unit minimum.

Prices (US East, on-demand, AWS Price List API):
- Comprehend `DetectPiiEntities`: USD 0.0001 per 100-character unit for the
  first 10M units per month, minimum 3 units per call (offer file 2026-09-11).
- Lambda: USD 0.0000166667 per GB-second on x86 (offer file 2026-10-30).

Assumptions (not measured):
- "Current volume" is not stated in the issue, so 1k, 10k and 100k requests per
  month are shown.
- Each request's subject and description fit in 300 characters. Sent together,
  that is one call; sent separately, two.
- Lambda memory is 512 MB.
- Comprehend's waiting time is 50, 100 or 200 ms.
- Free tiers are not subtracted (AWS lists 50K Comprehend units per month;
  eligibility depends on the account).

| Requests per month | Comprehend, 1 call | Comprehend, 2 calls | Lambda wait for Comprehend at 50 / 100 / 200 ms | Local A, B or D Lambda compute |
|---:|---:|---:|---:|---:|
| 1,000 | $0.30 | $0.60 | $0.0004 / $0.0008 / $0.0017 | < $0.0001 |
| 10,000 | $3.00 | $6.00 | $0.004 / $0.008 / $0.017 | < $0.0001 |
| 100,000 | $30.00 | $60.00 | $0.04 / $0.08 / $0.17 | < $0.0001 |

Local compute uses the laptop's mean latency. D at 100k requests is
USD 0.00005; even if Lambda were 10 times slower it would stay under
USD 0.001. Longer texts cost proportionally more with Comprehend: a
1,000-character description is 10 units (USD 0.001) per call. The approved
Comprehend benchmark itself would cost about 74 texts × 2 passes × 3 units =
444 units, or USD 0.04.

## 10. Lambda feasibility

- **Limits:** a Lambda deployment package may be 50 MB zipped and 250 MB
  unzipped including layers; container images may be up to 10 GB.
- **Approaches A, B and D:** the `src/pii_evaluation` modules import only the
  Python standard library (checked by a test). `boto3` is imported only inside
  the Comprehend client factory, and the Lambda Python runtime already includes
  it. The package adds no dependencies.
- **Users lookup:** the name index needs the users' names inside the Lambda. At
  100k users, building it took 5.2 s and 29 MB on the laptop. For a batch archive
  run this happens once per invocation. Querying the database for names, or
  pre-building the index, was not measured.
- **Comprehend:** needs the `comprehend:DetectPiiEntities` IAM permission, which
  the issue says the team does not have yet. Text is limited to 100 KB per call.
  The API supports only `en` and `es`, so the Hindi, French, Chinese and mixed
  texts (8 of 74 here) would have to be sent as English or skipped.
- **Presidio (size measured; accuracy not evaluated):** on macOS arm64 with
  Python 3.12, `presidio-analyzer` and `presidio-anonymizer` 2.2.366 plus their
  dependencies took **189 MB** installed, without any language model. The largest
  parts were `phonenumbers` 46 MB, `numpy` 33 MB and `spacy` 29 MB.
  - The default model `en_core_web_lg` 3.8.0 is a **400.7 MB** download
    (HTTP `content-length` 400,658,291 bytes), more than the 250 MB unzipped
    limit on its own. Its installed size was not measured because the disk
    filled up.
  - The small model `en_core_web_sm` 3.8.0 took 15 MB installed, giving about
    204 MB in total, which is under the limit but leaves little room.
  - Linux Lambda wheels were not measured.
  - This supports the issue's claim that Presidio with its default model does
    not fit a zip Lambda; the exact 374 MB figure was not reproduced.

## 11. Limitations

- **Comprehend is not measured.** No accuracy or latency numbers exist for
  Approach C.
- The synthetic set and Approach D were written by the same author, so D's
  synthetic-set numbers are optimistic. The held-out set reduces this bias but is
  small (60 texts) and labelled only at document level.
- 74 and 60 texts are small samples: one text changes recall by about two
  percentage points.
- The users table is synthetic (35 rows); the real name distribution is unknown.
- The name lookup does not split Chinese, Japanese or Thai text into words, does
  not handle misspelt names, and can match a user whose name is also a common
  word if their full name appears.
- Latency is from a laptop, not Lambda. Database query time is not measured.
- The Comprehend adapter sends one language code per run.
- Redaction removes the whole span; it does not keep a reversible mapping.

## 12. Recommendation and justification

**Provisional, pending a measured Comprehend run:**

1. Do not rely on Approach A alone. It missed 31 of 47 PII texts on the
   synthetic set and 26 of 40 on the held-out set, and it misses every name and
   address.
2. Add the users full-name lookup (B, full-name mode only). It added 9 caught
   texts with no new false positives and costs about 18 µs per text. Do not use
   token mode: it wrongly redacted 6 of 27 clean texts.
3. Extend the patterns using D's rules (international and spelled-out phones,
   addresses, keyword-cued IDs, Luhn-checked cards, and leaving public links
   alone). On independent data D raised recall from 0.35 to 0.775 with no false
   positives, needs no dependencies, and costs nothing beyond Lambda time.
4. Run Approach C on the same data once the IAM permission and spending are
   approved (about USD 0.04). Adopt it only if it finds names of non-users
   without cue phrases (the held-out set's main gap) without wrongly redacting
   clean texts, and if English and Spanish coverage is acceptable. At 100k
   requests per month it would cost about USD 30–60.

Presidio is not recommended for a zip Lambda: it is 189 MB before a model, and
its default model is a 400.7 MB download.

## 13. Reproduction instructions

From `data-engineering/` with the repository virtual environment:

```bash
# Regenerate the fixtures (they should not change)
../venv/bin/python -m scripts.build_pii_evaluation_dataset

# Tests
../venv/bin/python -m pytest tests -q

# Benchmark without AWS (Comprehend reported as NOT MEASURED)
../venv/bin/python -m scripts.benchmark_pii_detection \
    --output docs/pii_masking_evaluation_585_results.json

# Optional held-out set from PR #659, downloaded outside the repository
curl -sSo /tmp/pr659_heldout.jsonl \
  https://raw.githubusercontent.com/LohithVattikuti/data/cfcbf7119a7a9eb39c31955cbbc467277f17583c/data-engineering/tests/fixtures/pii_request_descriptions.jsonl
../venv/bin/python -m scripts.benchmark_pii_detection \
    --external-dataset /tmp/pr659_heldout.jsonl \
    --output docs/pii_masking_evaluation_585_results.json
```

Approach C only after approval (billable, about 444 units), with `boto3`
installed locally and credentials allowing `comprehend:DetectPiiEntities`:

```bash
../venv/bin/python -m scripts.benchmark_pii_detection --comprehend \
    --allow-billable-aws-calls --region us-east-1 --comprehend-language en
```

Without `--allow-billable-aws-calls` the script refuses to run Comprehend.

## 14. Acceptance criteria checklist

Issue #585 criteria:

| Criterion | Status |
|---|---|
| At least 50 descriptions, each marked for personal detail | Done: 74 texts, each with a flag and entity spans |
| At least 15 with no personal detail | Done: 27 clean texts |
| Includes non-English names | Done: 22 names from over ten backgrounds, including Devanagari and Chinese script |
| All three approaches run against the same test set | **Incomplete:** A and B run; C NOT MEASURED |
| Processing time recorded for each approach | **Incomplete:** A, B and D recorded; C NOT MEASURED |
| Catches, misses and false positives counted for each | **Incomplete:** A, B and D counted; C NOT MEASURED |
| Recommendation stated with reason | Done, provisional on Comprehend |
| Document attached to the issue | **Not done:** nothing has been committed, pushed or posted |

Additional items from the issue:

| Item | Status |
|---|---|
| Monthly cost estimate | Done for Comprehend and Lambda compute at assumed volumes; current volume unknown |
| Presidio size confirmed independently | Partly done: 189 MB without model and 400.7 MB model download measured on macOS; Linux not measured |
| No heavy imports in Lambda code | Done: standard library only, checked by a test |
| Better approach tested | Done: Approach D, flagged as optimistic, checked on held-out data |
