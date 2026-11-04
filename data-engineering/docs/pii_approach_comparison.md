# Request description PII approach evaluation (#585)

## Test method

The same 60 synthetic request descriptions were evaluated by each
available detector: 40 contain labeled personal data and
20 are clean. The test corpus is checked into
`tests/fixtures/pii_request_descriptions.jsonl`; it includes English and
non-English names, addresses, email, multiple phone formats, digit-only and
spelled-out phone numbers, card/ID patterns, dates, and benign numeric text.
All names, addresses, contacts, and identifiers are fictional. This is a
sample-level measurement: a sample counts as caught if the method flags it
and as missed if it does not. A clean sample flagged by a method is a false
positive. Processing time is measured locally over one pass and excludes
process startup; live Comprehend timing includes each network call.

## Results

| Approach | Caught | Missed | False positives | Clean correct | Elapsed seconds | Samples/second |
|---|---:|---:|---:|---:|---:|---:|
| Patterns only (email, phone, card, SSN) | 18 | 22 | 0 | 20 | 0.000497 | 120714.2 |
| Patterns + mock users lookup | 28 | 12 | 0 | 20 | 0.000640 | 93688.9 |
| Amazon Comprehend PII API | Not measured | Not measured | Not measured | Not measured | Not measured | Not measured |

### Comprehend access status

Not run. Live PII detection requires AWS Comprehend permission, which was not available during this local-only evaluation.

No AWS credentials/IAM permission were available in this environment, so no
Comprehend accuracy or latency result is fabricated. Re-run with
`python -m scripts.benchmark_request_pii --comprehend --region us-east-1`
from `data-engineering/` after granting `comprehend:DetectPiiEntities`.

## Recommendation

Use pattern matching as the inexpensive first pass and add Amazon Comprehend
for names and address-like PII only after a live evaluation confirms its
recall and false-positive rate on the maintainer-provided corpus. The local
user-name lookup only recognizes names already in the users table: it misses
other names, may reveal user-table names in matching logic, and does not
identify addresses. Pattern matching alone cannot find names or addresses.
Do not treat this synthetic benchmark as proof of production quality.
Presidio is excluded per the task's Lambda package-size constraint; confirm
its deployed dependency footprint before reconsidering it.

## Cost estimate

The repository does not publish current monthly request volume, so a factual
current-volume total cannot be calculated. AWS pricing examples bill text
analysis by 100-character units; at the published $0.0001/unit example rate,
this corpus averages 56.1 characters per description. An
illustrative 10,000 descriptions/month at this corpus's
per-request rounded average costs approximately **$1.00/month**
before free-tier eligibility, taxes, and regional price differences. Replace
the volume assumption with actual archived request counts; the included
benchmark computes this using each request's rounded-up 100-character units.
This estimate does not include S3, Lambda, data transfer, or retries.

Source: [Amazon Comprehend pricing](https://aws.amazon.com/comprehend/pricing/)
(checked 2026-11-03).
