# PII masking approaches (#585)

Compares ways of removing personal details from `req_subj` / `req_desc` before
requests are archived to S3. The findings and recommendation are in
[PII_MASKING_EVALUATION_585.md](PII_MASKING_EVALUATION_585.md).

| File | What it is |
|---|---|
| `pipeline_patterns.py` | Approach 1: the archive pipeline's current patterns, copied unchanged |
| `detectors.py` | Approaches 2, 4 and 5 (2 and 4 use the standard library only) |
| `comprehend_adapter.py` | Approach 3 (Amazon Comprehend) and the monthly cost calculation |
| `name_lookup.py` | Loads name parts from a `users` export |
| `evaluate.py` | Runs every approach on a test set and writes `results/` |
| `data/build_test_set.py` | Source of both labelled test sets (all text is made up) |
| `data/test_set.jsonl` | Main set: 72 requests, 50 with personal details, 22 without |
| `data/holdout_set.jsonl` | Holdout set: 30 requests written after approach 4 was frozen |
| `data/mock_users.csv` | Fictional registered users that the test texts mention |
| `results/` | Output of the last run, including the masked text of every request |

## Run it

Python 3.9+. No packages are needed for approaches 1, 2 and 4.

```bash
cd data-engineering/src/pii_masking_approaches
python evaluate.py                    # main set
python evaluate.py --set holdout      # holdout set
python evaluate.py --comprehend       # adds approach 3; needs AWS credentials with
                                      # comprehend:DetectPiiEntities
```

Approach 5 runs only when `spacy` and `en_core_web_sm` are installed. Otherwise
it is reported as "not run".

Tests (from the repo root):

```bash
python -m pytest data-engineering/tests/test_pii_masking_approaches.py
```
