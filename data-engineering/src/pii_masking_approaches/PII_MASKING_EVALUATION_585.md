# Evaluation: masking personal details in request text (#585)

Part of the request archival pipeline (RDBMS → S3). `request.req_subj` and
`request.req_desc` are free text, so requesters can type phone numbers,
addresses and names that column-level rules cannot see. This document compares
ways of removing those details before a request is archived.

## Recommendation

1. **Now:** replace the pipeline's `SCRUB_PATTERNS` with **approach 4
   (improved rules)**. It uses only the Python standard library, adds about
   0.05 ms per request, needs no new AWS permission and costs nothing extra. On
   the holdout set it catches **77% of personal details instead of 19%**, and it
   did not change a single clean request in either set.
2. **Next:** names with no surrounding cue are the gap left (all 6 holdout
   misses are names). Once `comprehend:DetectPiiEntities` is granted, run
   `python evaluate.py --comprehend` on both sets. If Comprehend catches those
   names, add it as a second pass after approach 4. At 10,000 requests a month
   it costs about **$3/month** (free for the first 12 months up to ~16,600
   requests/month).
3. **Do not use Presidio** in a zip Lambda. It measured **315 MB before any
   language model**, over Lambda's 250 MB limit.
4. **Option if the team accepts a container-image Lambda:** approach 4 + the
   spaCy small model caught **25 of 26** holdout details (72 of 73 on the main
   set), with no AWS service and no per-call cost. The trade-offs are about
   280 MB of packages, ~4 ms per request, and a few extra false redactions.

## Approaches

| # | Approach | How it works | Runs in zip Lambda |
|---|---|---|---|
| 1 | Pipeline patterns only (today) | The 5 regexes from `requests_archive/lambda_function.py` (#416 branch), copied unchanged | Yes |
| 2 | 1 + users-table lookup | Any word matching a first/middle/last name in `users` is masked | Yes |
| 3 | 1 + Amazon Comprehend | `DetectPiiEntities`, score ≥ 0.5, `DATE_TIME`/`AGE` ignored | Yes (boto3 is in the runtime), needs IAM permission |
| 4 | Improved rules | Wider patterns (international/spelled-out phones, obfuscated emails, street addresses, IDs, dates of birth, card checksum) + users-table names that are capitalised and not common words + name cues ("my name is", "my son", "Mr.", "ask for", "Thanks,", "Me llamo", "मेरा नाम") | Yes, standard library only |
| 5 | Improved patterns + spaCy `en_core_web_sm` (reference) | 4's patterns + the model's `PERSON` entities | **No**: needs a container image |

## Test sets

All text is made up. No request text or person from the real tables appears in it.

| Set | Requests | With personal details | Without | Labelled details | Purpose |
|---|---|---|---|---|---|
| Main (`data/test_set.jsonl`) | 72 | 50 | 22 | 73 | Built first. Approach 4 was tuned on it. |
| Holdout (`data/holdout_set.jsonl`) | 30 | 20 | 10 | 26 | Written **after approach 4's rules were frozen** and never used to change them. |

The sets cover phones in US, Indian, UK, Australian, French, UAE and Pakistani
formats, phones written as words or with spaced digits, normal and obfuscated
emails ("fatima dot alsayed at gmail dot com"), street addresses with unit
numbers, SSN, passport and licence numbers, a card number, a date of birth, a
profile URL, and names that are lower-case, Spanish, Yoruba, Irish, Japanese,
Polish and in Devanagari script. Clean requests include traps: names that are
also words ("hope", "may", "grace"), long reference numbers, street names
without a house number, and a public figure's name.

Each detail counts as **caught** when every letter or digit of it is masked,
**partly** when some is masked, and **missed** when none is.

## Results

### Holdout set (the honest estimate)

| Approach | Caught | Partly | Missed | Requests fully cleaned | Clean requests wrongly masked | False-positive masks | Time / request |
|---|---|---|---|---|---|---|---|
| 1. Pipeline only | 5/26 (19%) | 0 | 21 | 2/20 | 0/10 | 0 | 0.005 ms |
| 2. + users lookup | 8/26 (31%) | 1 | 17 | 4/20 | 0/10 | 0 | 0.009 ms |
| 3. + Comprehend | not run: no AWS permission yet | | | | | | |
| **4. Improved rules** | **20/26 (77%)** | 1 | 5 | 14/20 | **0/10** | **0** | 0.045 ms |
| 5. spaCy (reference) | 24/26 (92%) | 0 | 2 | 18/20 | 0/10 | 3 | 4.1 ms |
| 4 + 5 combined | 25/26 (96%) | 0 | 1 | 19/20 | 0/10 | 3 | ~4.2 ms |

### Main set

| Approach | Caught | Partly | Missed | Requests fully cleaned | Clean requests wrongly masked | False-positive masks | Time / request |
|---|---|---|---|---|---|---|---|
| 1. Pipeline only | 22/73 (30%) | 0 | 51 | 9/50 | 1/22 | 1 | 0.006 ms |
| 2. + users lookup | 42/73 (58%) | 5 | 26 | 25/50 | 4/22 | 6 | 0.011 ms |
| 3. + Comprehend | not run: no AWS permission yet | | | | | | |
| 4. Improved rules | 71/73 (97%) | 0 | 2 | 49/50 | 0/22 | 0 | 0.055 ms |
| 5. spaCy (reference) | 66/73 (90%) | 1 | 6 | 43/50 | 1/22 | 6 | 4.2 ms |
| 4 + 5 combined | 72/73 (99%) | 0 | 1 | 49/50 | 1/22 | 6 | ~4.3 ms |

Approach 4's main-set score is inflated because its rules were written while
looking at that set. Use the holdout number (77%).

Per-type counts, every miss, and the masked text of every request for every
approach are in `results/results.md` and `results/results_holdout.md`.

### What each approach gets wrong

- **1. Pipeline only.** It never catches a name or an address. It also misses
  phones outside the US 10-digit layout (+91, +44, +971, Australian,
  Pakistani), spelled-out numbers, obfuscated emails and passport numbers. Its
  card pattern has no checksum, so a 14-digit county reference number (C21) is
  masked as a card.
- **2. + users lookup.** It catches registered users' names, but nobody else's,
  and many requests mention family, neighbours or caseworkers who are not
  users. It masks ordinary words that are also someone's name: "hope", "may"
  and "grace" in C04, C06 and C07. Partial masks (first name hidden, surname
  left) are common.
- **4. Improved rules.** All of its holdout misses are names with no cue or a
  cue it does not know: "a single dad, Carlos Mendoza", "Mrs Okonkwo" (no dot),
  "My daughter is Mei Ling", "-Tom", "Child: Arjun Reddy, … Parent: Kavya
  Reddy" (half caught) and "baby Noah". Each fix is one more cue, but the list
  will never be complete, which is the limit of a rule-based approach.
- **5. spaCy small model.** It finds names without cues, but misses some that
  rules catch easily: "ask for Lakshmi", "Thanks, Maria", "(Aisha)", Devanagari
  and "Ana María López". It also masks "Martin Luther King Jr. Day" (C22).
  Because the two approaches fail on different names, combining them helps.

## Size check: Presidio and spaCy

Measured with `pip install --target <dir>` on Linux x86_64 (Lambda's
architecture), Python 3.13:

| Package set | Size on disk | Fits 250 MB zip Lambda? |
|---|---|---|
| `presidio-analyzer` + `presidio-anonymizer` 2.2.366 (no language model) | **315 MB** | No |
| `spacy` 3.8 alone | 264 MB | No |
| `en_core_web_sm` 3.8.0 model | 15 MB | (adds to the above) |

Presidio pulls in spaCy (120 MB), blis (39 MB), numpy (58 MB with its
libraries), phonenumbers (23 MB) and thinc (15 MB). Presidio also needs a
language model on top of that, and its default is the large English model.
This confirms the issue's statement: Presidio does not fit a zip Lambda. Any
spaCy-based option (approach 5) needs a container-image Lambda (10 GB limit),
which changes how the function is built and deployed.

## Cost per month

Approaches 1, 2 and 4 run inside the archive Lambda that already exists. At
0.05 ms per request the extra Lambda time is negligible: 100,000 requests add
about 5 seconds of compute a month.

Amazon Comprehend `DetectPiiEntities` costs $0.0001 per unit of 100 characters,
with a minimum of 3 units per call. The test requests average 76 characters
(subject + description), so one combined call per request costs the minimum
3 units ($0.0003).

| Requests / month | Units / request | Cost / month | Cost in first 12 months (50,000 free units / month) |
|---|---|---|---|
| 1,000 | 3 | $0.30 | $0 |
| 10,000 | 3 | $3.00 | $0 |
| 100,000 | 3 | $30.00 | $25.00 |

The dev export in `data-analytics/sql/requests.csv` has only 25 requests, so it
says nothing about production volume. The table therefore shows three volumes
to read against the real request count. Sending the subject and description as
two separate calls would double the cost, so the implementation should send
them together.

## Limitations

- **Synthetic, small test sets.** 99 labelled details across 102 requests. The
  numbers show differences between approaches, not exact production accuracy.
- **Comprehend was not run.** The adapter (`comprehend_adapter.py`) is written
  and unit-tested with a fake client. A live run needs the IAM permission. Its
  live responses are cached in `results/comprehend_cache.json`, so later
  re-scoring makes no AWS calls.
- **Comprehend PII detection is limited to English and Spanish** (Developer
  Guide, supported languages), so names in other scripts would still rely on
  approach 4's cues.
- **The users-table lookup** used the repo's dev export (`data-analytics/sql/users.csv`,
  ~2,900 rows, mostly empty names) plus the fictional `data/mock_users.csv`.
  In Lambda the names would be loaded once per cold start with
  `SELECT first_name, middle_name, last_name FROM users` (408 name parts loaded
  in ~9 ms here).
- **Partly masked text is still sensitive.** A surname left behind can still
  identify someone. Partial matches are counted separately so they are visible.

## How to reproduce

```bash
cd data-engineering/src/pii_masking_approaches
python data/build_test_set.py           # only after editing the test sets
python evaluate.py                      # main set  -> results/results.md
python evaluate.py --set holdout        # holdout   -> results/results_holdout.md
python evaluate.py --comprehend         # adds approach 3 (needs AWS credentials)

# Approach 5 (optional, reference only):
pip install spacy https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl

python -m pytest data-engineering/tests/test_pii_masking_approaches.py   # from repo root
```
