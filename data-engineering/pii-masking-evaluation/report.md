# Issue #585 — Evaluation of PII Masking Approaches

## Objective

Evaluate masking of personally identifiable information (PII) in
`requests.req_subj` and `requests.req_desc` before archival from
the relational database to Amazon S3.

## Approaches

1. Regex-based masking.
2. Regex masking plus users-table name lookup.
3. Regex masking plus Amazon Comprehend PII detection.

## Test Dataset

- 60 original synthetic requests: 40 containing PII and 20 clean.
- 69 extended requests: 49 containing PII and 20 clean.
- 56 exact PII annotations.
- Includes emails, phone numbers, addresses, names, multilingual
  names, spelled-out phone numbers, credit-card numbers, and SSNs.
- Six synthetic names in the mock users table.

All dataset examples are synthetic.

## Local Benchmark Results

| Metric | Regex | Regex + users lookup |
|---|---:|---:|
| PII values masked | 37/56 (66.1%) | 46/56 (82.1%) |
| PII values missed | 19/56 | 10/56 |
| Fully masked PII requests | 30 | 39 |
| Partially masked requests | 5 | 2 |
| False positives among 20 clean requests | 0 | 0 |
| Median processing time | 0.247 ms | 0.793 ms |

These results are from a small synthetic dataset, not a
production validation. The evaluation checks whether annotated
PII strings remain in the masked text. It does not establish
complete detection accuracy or comprehensive false-positive rates.

## Observations

- Regex is lightweight and fast for known formats.
- Users-table lookup improves masking of registered names.
- Unknown names and spelled-out PII remain important limitations.
- Regex + lookup masks nine more annotated PII values than regex
  alone but still misses ten.
- Credit-card and SSN examples are limited to specific formats.
- Neither local approach is sufficiently reliable for unattended
  archival of sensitive request descriptions.

## Amazon Comprehend

A mocked Comprehend response test passed, verifying that the
integration masks the entity returned by the simulated API.

No live AWS Comprehend calls were made because AWS access was
unavailable. Therefore actual detection accuracy, latency,
service cost, and false-positive behavior remain unmeasured.

The mocked result must not be interpreted as a real Comprehend
benchmark.

## Cost and Operational Considerations

- Regex: no per-request external API charge; compute and
  maintenance costs still apply.
- Regex + users lookup: adds database lookup or cached-name
  maintenance costs.
- Amazon Comprehend: variable usage charges based on the
  service's pricing units, plus any applicable AWS infrastructure
  costs. Estimate monthly cost from the actual request volume,
  description sizes, and current regional AWS pricing.
- Exact monthly costs cannot be calculated without workload
  assumptions and confirmed pricing.

## Presidio and AWS Lambda

Microsoft Presidio is an additional candidate for PII detection,
but its deployment footprint depends on recognizers, NLP models,
and dependencies selected.

Lambda compatibility, packaged artifact size, memory consumption,
cold-start time, and execution latency have not been measured.
A dependency/package-size test is required before recommending
Presidio for the archival Lambda.

## Provisional Recommendation

Prefer regex + users lookup over regex alone as a lightweight
baseline because it masked 46/56 annotated values versus 37/56.

Do not treat this baseline as production-ready. Before archiving
request descriptions, complete a live Comprehend comparison,
test realistic and adversarial descriptions, verify false
positives, evaluate costs, and establish an acceptable PII
leakage threshold.

Consider a hybrid approach only after these evaluations.

## Reproduction

Install dependencies:

    python -m pip install -r requirements.txt

Generate synthetic datasets:

    python generate_dataset.py

Run local evaluation:

    python evaluate.py

Run mocked Comprehend test:

    python test_comprehend.py

## Remaining Work

- Benchmark live Amazon Comprehend using AWS access.
- Record Comprehend catches, misses, false positives, and latency.
- Estimate monthly costs using expected request volumes.
- Test Presidio packaging and Lambda deployment feasibility.
- Obtain review of the recommended masking strategy.

Related to saayam-for-all/data Issue #585.
