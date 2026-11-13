# #585: Evaluating approaches for masking personal details in request text

`req_subj` and `req_desc` are free text, so people write phone numbers, emails, names and addresses into them. The column rules in the archive pipeline can't see inside a text field. This document compares ways to remove those details before the text is archived to S3.

All numbers below come from `evaluate.py` in this folder and can be re-run. Full tables and the redacted output for every request are in `results/results.md` and `results/results_holdout.md`.

## What was tested

| # | Approach | What it does |
|---|---|---|
| 1 | Patterns only (today) | The `SCRUB_PATTERNS` already in the archive Lambda (#416 branch): email, SSN, card, US phone, URL. Copied unchanged; a test checks the output is identical to the pipeline's `scrub_text()`. |
| 2 | Patterns + users-table names | 1, plus any capitalised word that is a first, middle or last name in the `users` table. |
| 3 | Patterns + Amazon Comprehend | 1, plus `DetectPiiEntities` on subject + description in one call. `DATE_TIME` and `AGE` are not redacted (e.g. "rent due 11/15"). |
| 4 | Improved patterns + names + cues (new) | Wider patterns (international and 7-digit phones, numbers spelled out in words, "name at gmail dot com", street addresses, PO boxes), users-table names with a filter for common English words ("Grace period", "Hope someone…", "May I…"), and names that come after a cue ("my name is", "this is", "Mr./Ms.", "my neighbor…", "Thanks,"), even if the person isn't a user. |

All four use only the Python standard library (3 also uses `boto3`, which the Lambda runtime already has), so none adds a package to the Lambda.

**The names list** for 2 and 4 is the repo's `data-analytics/sql/users.csv` (the dev users export, 2,875 rows) plus `data/mock_users.csv` (26 fictional people who appear in the test set as "registered users"). That gives 386 distinct name parts. In the Lambda this would be one `SELECT first_name, middle_name, last_name FROM users` per run, which takes about 20 ms to index.

## Test sets

Every text is made up: fictional people, 555 phone numbers and example email domains. Nothing is copied from the real `requests` table.

- **Main set: 70 requests.** 50 contain personal details and 20 don't, with 66 labelled details:
  - 35 names. 30 belong to registered users and 5 to people who aren't users (a mother, a neighbour, a landlord). 26 of the 35 are non-English: Vietnamese, Yoruba, Arabic, Spanish, Japanese, Irish, Thai, Zulu, Russian, Swedish and more. One is written all in lower case.
  - 15 phone numbers in 10 formats, including +91, +44, a 7-digit number, "408.555.0177", and two spelled out in words.
  - 6 emails, 2 of them written as "x dot y at gmail dot com" or "[at] … [dot]".
  - 7 addresses, including one with the house number in words, and 1 each of SSN, card number and personal profile URL.
  - The 20 clean requests are chosen to trip detectors: money and dates, 911, a laptop model number, a tracking number, a public URL, and words that are also names (Grace, Hope, May, Jordan).
- **Holdout set: 24 requests**, 16 with details (19 labelled) and 8 clean. **Approach 4 was built while looking at the main set, so its main-set score is optimistic.** I wrote the holdout set afterwards and did not change any approach after running it. Its numbers are the honest estimate of how 4 does on text it hasn't seen.

**Scoring.**
- Every occurrence of a labelled detail counts.
- **Caught** means every letter and digit of it was redacted. Partly redacted counts as **not caught**, because the rest leaks.
- **Clean texts wrongly redacted** counts the requests with no personal details where anything was redacted.
- **Time** is the median over 200 runs on one laptop core, per request (subject + description).

## Results

### Main set (66 details, 20 clean requests)

| Approach | Caught | Missed (incl. partial) | Requests fully cleaned | Clean requests wrongly redacted | Time per request |
|---|---|---|---|---|---|
| 1. Patterns only (today) | 16 (24%) | 50 | 10 / 50 | 2 / 20 | 0.016 ms |
| 2. Patterns + users names | 44 (67%) | 22 | 29 / 50 | 5 / 20 | 0.028 ms |
| 3. Patterns + Comprehend | *see "Still to run"* | | | | |
| 4. Improved + names + cues | 65 (98%) | 1 | 49 / 50 | 3 / 20 | 0.127 ms |

| Caught by type | Names | Phones | Emails | Addresses | Names of users | Names of non-users |
|---|---|---|---|---|---|---|
| 1 | 0/35 | 9/15 | 4/6 | 0/7 | 0/30 | 0/5 |
| 2 | 28/35 | 9/15 | 4/6 | 0/7 | 28/30 | 0/5 |
| 4 | 34/35 | 15/15 | 6/6 | 7/7 | 29/30 | 5/5 |

### Holdout set (19 details, 8 clean requests), written after approach 4

| Approach | Caught | Missed (incl. partial) | Requests fully cleaned | Clean requests wrongly redacted | Time per request |
|---|---|---|---|---|---|
| 1. Patterns only (today) | 5 (26%) | 14 | 2 / 16 | 0 / 8 | 0.015 ms |
| 2. Patterns + users names | 6 (32%) | 13 | 3 / 16 | 0 / 8 | 0.025 ms |
| 4. Improved + names + cues | 13 (68%) | 6 | 10 / 16 | 0 / 8 | 0.109 ms |

### What each approach misses

- **1. Patterns only.**
  - It catches no names and no addresses.
  - It misses international phones (+91, +44, +52), 7-digit numbers, numbers in words, and "at … dot com" emails.
  - It redacts public links (`https://www.211.org`) and part of a parcel tracking number.
- **2. Users-table names.**
  - It only knows registered users. Every third-party name was missed: 0 of 5 in the main set and 0 of 7 in the holdout, such as a mother, a neighbour or a caseworker. In the holdout most names were of non-users, so it barely helped (+1).
  - Names that are also English words cause false redactions: "**Grace** period", "**Hope** someone can help", "arrived from **Jordan**". Our `users` table also contains junk names like "Test", "asdf" and single letters. Single letters are skipped (minimum 3 characters).
- **4. Improved.**
  - On the holdout it missed a name after "Signed:" and one after "Contact person -", a possessive ("Lakshmi's house"), and a phone number written with a non-standard Unicode hyphen.
  - It only partly caught two addresses that had the unit before the street ("Unit 5, 210 W Santa Clara St"). The street part was redacted but "Unit 5" was left.
  - The only wrongly redacted clean texts were the same ones approach 1 has (public URL, tracking number), plus "Jordan" the country, because a user is named Jordan.
  - All of these are small, specific pattern fixes, and they're listed here rather than fixed so the holdout stays honest.

## Presidio

I confirmed it doesn't fit in a zip Lambda.
- `pip install presidio-analyzer presidio-anonymizer` (2.2.366, Python 3.13, Linux x86_64) is **~300 MB** on disk without `.pyc` files, and ~385 MB with them. That's before any language model: spaCy alone is 128 MB, `phonenumbers` 46 MB, and numpy ~70 MB.
- Its default model `en_core_web_lg` 3.8.0 is a **400 MB download and 424 MB unpacked**.
- Lambda allows **250 MB** unzipped for the function plus layers. Even without a model it's over the limit, so it would need a container-image Lambda. Approaches 1, 2 and 4 add 0 MB.

## Cost (per month)

- **Approaches 1, 2 and 4** cost nothing extra. They add 0.02 to 0.13 ms of Lambda time per request, and approaches 2 and 4 add one users query per run. That's ~13 ms for 100,000 requests, which is well under a cent.
- **Approach 3 (Comprehend `DetectPiiEntities`)** is $0.0001 per 100-character unit, with a minimum of 3 units per call. Test requests average 74 to 86 characters (subject + description), so almost every request is one call at the 3-unit minimum, **≈ $0.0003 per request**:

| Requests archived per month | Comprehend cost |
|---|---|
| 1,000 | $0.30 |
| 10,000 | $3.00 |
| 100,000 | $30.00 |

  - The dev database has about 800 requests in total today, so current volume costs cents.
  - New accounts get 50,000 free units per month (≈16,000 requests) for 12 months.
  - Longer descriptions cost more: each extra 100 characters over 300 adds $0.0001.
  - Pricing is from https://aws.amazon.com/comprehend/pricing and https://docs.aws.amazon.com/comprehend/latest/APIReference/API_DetectPiiEntities.html (checked Nov 2026).
- **Other costs of 3:**
  - It needs the `comprehend:DetectPiiEntities` IAM permission.
  - It adds a network call per request.
  - The raw text is sent to another AWS service.
  - The `DetectPiiEntities` API reference says to pass English (`en`) or Spanish (`es`) text. Non-English *names* inside English text are fine, but a description written in Hindi or Vietnamese may not be covered.

## Recommendation

**Use approach 4 in the archive pipeline.** It's the only one that improves a lot over today without new costs or dependencies.

- **Coverage.** On unseen text it caught 68% of details against 26% for today's patterns, and 10 of 16 requests came out fully clean against 2 of 16. It is the only free approach that catches addresses and names of people who aren't users.
- **No new costs or risks.** It's pure Python (0 MB, ~0.1 ms per request), needs no new IAM permission, and sends nothing outside the database and the Lambda.
- **Approach 2 isn't worth it alone.** A plain users-table lookup barely helps on unseen text (+1 detail), because most names in requests are of people who aren't users. It also redacts ordinary words like "Grace", "Hope" and "Will".
- **Fix first.** Before turning approach 4 on, fix the holdout misses listed above: possessives, "Signed:" and "Contact person" cues, the unit-before-street address form, and Unicode hyphens. Also drop junk names (Test, asdf…) from the lookup.
- **Comprehend as an extra layer.** Comprehend can be layered on top of approach 4 later, if the run below shows it catches clearly more names and addresses on the holdout. At current volume its cost is negligible; the real costs are the IAM permission, the external call, and the language limit.
- **No approach is perfect, approach 4 included.** If the archive must *never* contain personal details, the safe option is to not archive `req_desc` at all, or to archive it only in a restricted bucket.

## Still to run: approach 3 (Comprehend)

The code is ready, but this session's AWS user doesn't have `comprehend:DetectPiiEntities` yet (the issue says to raise this or use free credits). Once someone has the permission, run:

```bash
cd data-engineering/src/pii_masking_evaluation
python evaluate.py --comprehend live --region us-east-1                 # main set
python evaluate.py --comprehend live --region us-east-1 --set holdout   # holdout set
```

The responses are saved to `results/comprehend_responses.json`. After that, `python evaluate.py` re-scores approach 3 from that file without AWS, and the tables above get a row for approach 3. That's 94 calls: about $0.03, or free within the free tier.
