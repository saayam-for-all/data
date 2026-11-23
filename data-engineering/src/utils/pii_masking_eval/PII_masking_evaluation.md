# Issue #585 – Evaluating PII masking for `req_subj` / `req_desc`

Status: approaches 1, 2 and 4 measured locally. **Approach 3 (Amazon Comprehend) is not measured**: the team has no AWS access (CONTRIBUTING.md), and running it needs credentials with `comprehend:DetectPiiEntities`. The Comprehend call is wrapped in `comprehend_pii.py` with the client injected and covered by offline tests, so someone with credentials can fill in the row with one command (section 4).

## 1. Test set

File: `testset_labelled.csv` (source of truth: `testset.py`; regenerate with `make_csv.py`).

| | Count |
|---|---|
| Texts | 84 (64 dev, 20 held-out) |
| Containing personal detail | 56 |
| Clean (no personal detail) | 28 (required: 15) |
| Labelled PII spans | 64 (25 names, 15 phones, 10 addresses, 8 emails, 4 ID numbers, 1 card, 1 DOB) |

Coverage: phones as `(480) 555-0142`, `480-555-0187`, `480.555.0123`, `+1 602 555 0166`, `6025550171`, `+91 98765 43210`, spelled out (`four eight zero five five five…`), and mixed (`602 five five five 0134`); emails including obfuscated ones (`john dot miller at gmail dot com`, `x [at] gmail [dot] com`); street addresses, a unit, a PO box and one spelled in words; SSN, Aadhaar, passport, card, DOB; names in English, Spanish (lowercase too), Vietnamese, Chinese, Arabic, Russian, Polish, Nigerian/Ghanaian, Marathi (Devanagari) and Korean (Hangul). Clean texts include traps: dollar amounts, times, dates, request IDs, "Social Security benefits" with no number, place and company names.

All values are invented. The users-table lookup was built from `data-analytics/sql/users.csv` (2,876 rows, but only 213 have a name; 954 usable tokens after dropping junk such as "asdf", "test", single letters).

**Honesty about the split.** The whole set was written before any detector code. Rules were then tuned only on the 64 dev texts. The 20 held-out texts were not used for tuning, with the exceptions listed in section 5. Treat dev numbers as optimistic and held-out numbers as the better estimate. All texts were written by one author (not taken from real requests), so they may not match how real requesters write; replacing a sample with real (anonymised) requests is the most valuable next check.

## 2. Approaches

| # | Approach | Implementation |
|---|---|---|
| 1 | Patterns only | Regex: email, phone (US and +cc), SSN, Aadhaar, Luhn-checked card, passport (with cue word), DOB (with cue word). Re-implemented from the issue text because the existing pipeline code was not in the repo. |
| 2 | Patterns + users lookup | 1, plus whole-word, case-insensitive match against name tokens from `users` (≥3 letters, junk removed). |
| 3 | Patterns + Amazon Comprehend | 1, plus `DetectPiiEntities`. **Not measured** (no AWS access). |
| 4 | Layered, stdlib only (proposed) | 1 and 2, plus: spoken-digit runs ("four eight zero…"), obfuscated emails, street/unit/PO-box/number-word addresses, and name cue phrases in EN/ES and Hindi/Marathi/Korean/Chinese/Arabic ("my name is", "this is", "mi nombre es", "my son X", Mr/Mrs/Dr, sign-offs). Cues are split into strong (one name token enough) and weak ("call", "help", "for"; need a two-token name). Imports: `re`, `csv` only. |

Scoring: a labelled span counts as caught if ≥80% of its characters fall inside detected spans. A PII text is **caught** if every span is caught, **partial** if some are, **missed** if none. A **false positive** is a clean text with any detection.

## 3. Results (all 84 texts: 56 with PII, 28 clean)

| Approach | Caught | Partial | Missed | Span recall | False positives (of 28 clean) | Time per text (mean / p95) |
|---|---|---|---|---|---|---|
| 1 Patterns only | 17 | 4 | 35 | 23/64 (36%) | 0 | 17 µs / 24 µs |
| 2 Patterns + users lookup | 19 | 4 | 33 | 25/64 (39%) | 0 | 158 µs / 214 µs (+35 ms one-off lookup load) |
| 3 Patterns + Comprehend | not measured | | | | | not measured |
| 4 Layered, no deps | 52 | 1 | 3 | 60/64 (94%) | 0 | 222 µs / 311 µs |

Held-out only (14 PII, 6 clean): approach 1 caught 4/14, approach 2 caught 4/14, approach 4 caught 12/14 (11/14 before the fix noted in section 5). No false positives in any approach.

Span recall by type (caught/total):

| Type | Total | 1 | 2 | 4 |
|---|---|---|---|---|
| Phone | 15 | 11 | 11 | 15 |
| Email | 8 | 6 | 6 | 8 |
| ID, card, DOB | 6 | 6 | 6 | 6 |
| Address | 10 | 0 | 0 | 9 |
| Name | 25 | 0 | 2 | 22 |

Timing is single-threaded CPython 3.13, mean over 300 runs per text, measured on a Windows laptop (`run_all.sh` under Git Bash). Lambda at low memory may be slower, but all three approaches stay far below 1 ms per text.

What the numbers say:
- Approach 1 is precise but only covers digit-format phones, plain emails and ID numbers. It misses every name, every address and all spelled-out numbers.
- Approach 2 adds only 2 name catches here, and those two names were put in the test set on purpose because they exist in `users`. The lookup only knows people who registered; the people in free text are often third parties (neighbour, parent, "ask for X"). It is also fragile: in this table 2,663 of 2,876 users have no first name, and what remains includes junk.
- Approach 4 misses: `Aarav Deshmukh is the point of contact…` (name with no cue), `Khadija Bint Rashid asked me to…` (name with no cue), `…7421 W Camelback Road Phoenix` (city after street not covered, so only 72% of the span is masked), and `ask for Maria` (a single name after a weak cue).

### Extra false-positive checks for approach 4
Cue rules are the risky part. Two probes of clean sentences written after the first run (`fp_probe.py`, `fresh_probe.py`):
- Probe A (22 sentences built to look like cues): the first version flagged 7 (`Contact Lenses`, `Call Center`, `Help Wanted`, `Thanksgiving`…). The strong/weak cue split was then added. After that 1/22 remains (`I'm Hungry and out of food` → "Hungry"). This probe was used for tuning, so it is not a fair score.
- Probe B (12 new clean sentences, not tuned on): 0 flagged. Same probe, 8 new PII sentences: 6 caught; missed `call me at 4 8 0 5 5 5 0 1 7 7` (all single digits as separate tokens) and `Mi hija Valentina necesita clases`.

Reasonable expectation on real data: names written without a cue will be missed, and some capitalised words after "I'm/this is" will be over-redacted. With 28 + 34 clean sentences a tight false-positive rate cannot be given.

## 4. Approach 3 (Comprehend) – status and how to complete the row

The team has no AWS access (per CONTRIBUTING.md), so the Comprehend call is wrapped in `comprehend_pii.py` with the client injected, and 8 offline unit tests (`tests/test_comprehend_pii.py`) cover offset handling, merging with regex spans, chunking of long text, AccessDenied/Throttling fallback and language choice. These tests use a fake client and say nothing about Comprehend's accuracy; the row stays *not measured* until someone with credentials runs it.

To complete it:
1. Use an AWS account with free credits and an IAM policy allowing `comprehend:DetectPiiEntities`.
2. Set `RUN_COMPREHEND=1` and run `./run_all.sh` (or `python3 run_comprehend.py out/comprehend_spans.json us-east-1`). It sends all 84 texts (Spanish-looking ones with `es`, the rest `en`, since Comprehend PII supports English and Spanish only) and prints mean and p95 API latency.
3. `python3 -I run_eval.py <path>/users.csv out out/comprehend_spans.json` adds a `3_patterns_comprehend` row, scored exactly like the others.
4. Expect network latency of tens to hundreds of ms per call versus well under 1 ms locally, and expect Hindi/Marathi/Korean names and unusual spellings to be at risk because those languages are unsupported. Both are expectations, not measurements.

## 5. Corrections made after seeing results (for transparency)
- Dev-driven: obfuscated-email regex matched the wrong substring; unit keyword was case-sensitive.
- Probe-driven: strong/weak cue split (above).
- Held-out contamination: `Thanks, Elena Petrova` was missed because of a word-boundary bug in the cue regex; it was fixed when the cues were restructured, so the held-out score is 11/14 before and 12/14 after. The remaining held-out misses were deliberately left unfixed.
- Windows: file writes in `run_eval.py` now specify UTF-8 explicitly (the default cp1252 crashed on Hindi/Korean names).

## 6. Dependency check (Presidio)
`pip install presidio-analyzer` into an empty directory (Linux, Python 3.13) gives **299 MB unzipped before adding any spaCy language model** (spaCy 120 MB, blis 39 MB, numpy 30 MB + 28 MB libs, phonenumbers 23 MB). Adding a model on top only makes it larger. That independently supports the issue's claim that it exceeds Lambda's 250 MB unzipped limit and would force container images. Approach 4 imports only `re` and `csv`, so package size is a few tens of KB. (Reproduce with `CHECK_PRESIDIO=1 ./run_all.sh`.)

## 7. Monthly cost estimate
**Current monthly request volume: [FILL IN – not stated in the issue or visible in the repo; the mock `requests.csv` has 25 rows].** Until then, figures are for scenarios.

Assumptions: one text per request (`req_subj` + `req_desc`, under 300 characters) and one pass per month of new/archived rows.

| Requests per month | Approach 1/2/4 (Lambda) | Approach 3 Comprehend |
|---|---|---|
| 1,000 | under $0.01 | 3,000 units = $0.30 list, $0 within free tier |
| 10,000 | under $0.01 | 30,000 units = $3.00 list, $0 within free tier |
| 100,000 | about $0.01 | 300,000 units = $30 list, about $25 after the free tier |

Basis: Comprehend bills $0.0001 per 100 characters with a 3-unit (300-character) minimum per request, and a free tier of 50,000 units per API per month for the first 12 months (AWS pricing page). Calling it separately for subject and description doubles the units. Lambda: 128 MB, about 1 ms billed per call, at AWS's published per-GB-second rate; this is an estimate and rounds to cents. One-off backfills cost proportionally to row count.

## 8. Recommendation
Use **approach 4** (patterns + spoken-number/obfuscation handling + address rules + name cue phrases + users lookup) as the in-Lambda method. Reason: on this test set it caught 52 of 56 PII texts against 17–19 for approaches 1 and 2, with no false positives on 28 clean texts, in about 0.2 ms per text, with no dependencies and negligible cost.

It does not catch a name that appears with no cue phrase and is not in `users`, so it should not be called complete. Two options for the residual risk, to be decided by the team:
- Add Comprehend as an optional second pass (approach 3 on top of 4) only for texts where a conservative signal fires, such as a capitalised multi-word sequence, and measure it using section 4 before committing. At the scenarios above it costs at most tens of dollars per month.
- Or treat unmasked free text as sensitive: keep the archived bucket private and restrict access.

Do not use approach 2 alone: it adds almost nothing over patterns and depends on mock-quality user names. Do not adopt Presidio unless the team accepts container images.

Before shipping: re-run on a sample of real (anonymised) requests, since this test set is synthetic and written by one author.

## 9. Files
In `data-engineering/src/utils/pii_masking_eval/`: `testset.py`, `detectors.py` (approaches 1, 2, 4), `comprehend_pii.py` (approach 3 wrapper), `tests/test_comprehend_pii.py`, `run_eval.py`, `run_comprehend.py`, `fp_probe.py`, `fresh_probe.py`, `run_all.sh`, `make_csv.py`, `README.md`.
Generated by `run_all.sh` into `out/` (not committed): `results.json`, `redacted_samples.json`, `details_*.txt` (every miss and false positive). Attached to the issue: `testset_labelled.csv`.