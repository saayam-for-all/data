# PII masking evaluation (#585)

Compares four ways of removing personal details (names, phones, emails,
addresses…) from `req_subj` / `req_desc` before requests are archived to S3.
**The write-up and recommendation are in
[PII_MASKING_EVALUATION_585.md](PII_MASKING_EVALUATION_585.md).**

| File | What it is |
|---|---|
| `pipeline_patterns.py` | Approach 1: the archive pipeline's current patterns, copied unchanged |
| `detectors.py` | Approaches 1-4 (standard library only; Comprehend uses boto3) |
| `evaluate.py` | Runs all approaches on a test set and writes `results/` |
| `data/build_test_set.py` | Source of the labelled test sets (all made-up text) |
| `data/test_set.jsonl` | Main set: 70 requests, 50 with personal details, 20 without |
| `data/holdout_set.jsonl` | Holdout set: 24 requests written after approach 4, never used to tune it |
| `data/mock_users.csv` | Fictional users that the test texts mention |
| `results/` | Output of the last run (tables + redacted text for every request) |

## Run it

No packages needed beyond Python 3.9+ (and `boto3` only for Comprehend).

```bash
cd data-engineering/src/pii_masking_evaluation
python data/build_test_set.py          # only if you edit the test set
python evaluate.py                     # main set
python evaluate.py --set holdout       # holdout set

# Approach 3 needs AWS credentials with comprehend:DetectPiiEntities:
python evaluate.py --comprehend live
python evaluate.py --comprehend live --set holdout
```

The names lookup reads `data-analytics/sql/users.csv` from this repo plus
`data/mock_users.csv`; pass `--users <csv>` to use another export with
`first_name, middle_name, last_name` columns.

Tests: `python -m pytest data-engineering/tests/test_pii_masking_evaluation.py`
