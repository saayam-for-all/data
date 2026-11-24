# Issue #585 – PII masking evaluation: run it locally

## What you need
- Python 3.9+ and git. No other packages for approaches 1, 2 and 4 (stdlib only).
- For approach 3 only: `boto3` and AWS credentials (free-credit account) allowed to call `comprehend:DetectPiiEntities`.

## Run everything (approaches 1, 2, 4)
```bash
cd package
./run_all.sh                      # clones saayam-for-all/data to get users.csv
# or: ./run_all.sh /path/to/users.csv
```
You get a table of caught / partial / missed / false positives / µs per text for the dev set, the held-out set and all 84 texts, then the two extra false-positive probes.

## Approach 3 without AWS access
The team has no AWS access, so the Comprehend call is injected (`comprehend_pii.py`) and tested with a fake client:
```bash
python3 -m unittest discover -s tests -v     # 8 offline tests, no AWS
python3 run_comprehend.py --dry-run          # wiring check only, NOT a measurement
```
These prove the wrapper (offsets, merging, chunking, error fallback, language choice) is correct. They say nothing about
how accurate Comprehend is, so the approach 3 row stays "not measured" until someone runs the real call below.

## Add approach 3 (Comprehend) - real run
```bash
export AWS_ACCESS_KEY_ID=...  AWS_SECRET_ACCESS_KEY=...  AWS_REGION=us-east-1
RUN_COMPREHEND=1 ./run_all.sh
```
This sends the 84 texts to Comprehend (about 84 calls, well inside the free tier), saves spans to `out/comprehend_spans.json`, and re-runs the scorer so a `3_patterns_comprehend` row appears. The script prints mean/p95 API latency; that is the processing time for approach 3. If the IAM permission is missing you will get AccessDenied – ask for `comprehend:DetectPiiEntities`.

## Optional: confirm the Presidio size claim
```bash
CHECK_PRESIDIO=1 ./run_all.sh     # prints size in MB; Lambda limit is 250 MB unzipped
```

## Fill in the document
1. Open `PII_masking_evaluation.md`.
2. Section 3: paste the approach 3 row from the console output. Section 4: delete the "how to" and write what you measured.
3. Section 7: replace the scenario table's volume with the real monthly request count (units = requests x 3 if one call per request; price $0.0001 per unit; first 50,000 units/month free for 12 months).
4. Section 8: update the recommendation if Comprehend changes the picture (e.g. it catches the names approach 4 misses).
5. Attach the .md and `out/testset_labelled.csv` to issue #585.

## Make it better (recommended before shipping)
- Replace ~20 texts in `testset.py` with real anonymised request descriptions (keep labels as exact substrings) and re-run.
- Read `details_4_layered_no_deps.txt` for the misses; add cue phrases or rules in `detectors.py`, but do not tune on the held-out set or the score stops meaning anything.

## Files
- `testset.py` – labelled texts (DEV, HELDOUT). Each item: (text, [(pii_substring, TYPE)]); empty list = clean.
- `detectors.py` – approach 1 `detect_patterns`, 2 `detect_patterns_lookup`, 4 `detect_layered`, plus `redact()`. Lambda-safe (re, csv only).
- `comprehend_pii.py` – approach 3 with an injectable client (`detect_patterns_comprehend(text, client, fallback=None)`); `tests/test_comprehend_pii.py` – offline tests.
- `run_eval.py` – scorer and timer. `run_comprehend.py` – approach 3 real run / `--dry-run`. `fp_probe.py`, `fresh_probe.py` – extra false-positive checks.
- Using in Lambda: `rx = build_lookup_regex(load_name_lookup(users_csv))` once at cold start, then `redact(text, detect_layered(text, rx))` per row.
