# Issue #585 - Comprehend measured, plus a second test set

This fills in the row PR #715 left open (approach 3, Amazon Comprehend) and
re-runs every approach against a second test set that the detector author did
not write.

Comprehend was run from AWS CloudShell against `comprehend:DetectPiiEntities`
in us-east-1. 144 texts, 144 calls, mean 40 ms, p95 44 ms.

## 1. Two test sets

- **theirs** - the 84 texts in PR #715 (`testset.py`), 56 with PII, 28 clean.
- **independent** - 60 new texts I wrote without reading the detector code
  (`indep_testset.py`), 40 with PII, 20 clean. Same format and same scorer,
  so the numbers are directly comparable. Names in English, Spanish, Hindi,
  Vietnamese, Chinese, Arabic, Swedish, Nigerian and Polish. 20 clean texts
  include traps: amounts, times, request ids, place names, "Call Center",
  "Help Wanted", "Thanksgiving".

I wrote a second set because a detector scored only on a test set its own
author wrote tells you how well the rules fit that set, not how they behave on
text nobody anticipated.

## 2. Results

Span recall, same scorer as PR #715 (a span counts as caught at >=80% character
coverage).

| Approach | theirs (84) | independent (60) | FP on clean |
|---|---|---|---|
| 1 patterns only | 35% | 41% | 0/28, 0/20 |
| 2 patterns + users lookup | 39% | 46% | 0/28, 1/20 |
| 4 layered (PR #715 proposal) | 93% | 78% | 0/28, 1/20 |
| 3 patterns + Comprehend, filtered | 95% | 97% | 2/28, 2/20 |
| 4 + Comprehend, filtered | **98%** | **97%** | **0/28, 1/20** |

"Filtered" means dropping the `DATE_TIME`, `AGE` and `ADDRESS` entity types.
See section 3.

The headline: approach 4 alone scores 93% on its own test set and 78% on mine.
Adding Comprehend removes that gap. The combination is the only option that
performs the same on both sets.

Eight of approach 4's nine misses on my set are names with no cue phrase, which
PR #715 documents as a known limit. On its own test set that costs 2 texts. On
mine it costs 6, because naming a third party without announcing it is the
ordinary way these requests get written: "Fatima Zahra cannot walk to the
clinic", "Hassan needs a winter coat", "Chen Wei's apartment flooded".

## 3. Why filter Comprehend's entity types

Unfiltered, Comprehend flags something on 11 of 28 and 8 of 20 clean texts.
Every one of those is `DATE_TIME` (19), `AGE` (6) or `ADDRESS` (5). Not one is
a name, phone, email or id number.

The `AGE` hits are misreadings: "family of 5", "sizes 6, 8 and 10", "under ten".
The `ADDRESS` hits are place names rather than residences: "Tempe",
"Maricopa County", "Mill Avenue", "Phoenix Sky Harbor".

Dropping `DATE_TIME` and `AGE` costs no recall at all. Also dropping `ADDRESS`
costs about 2 points, because approach 4's regexes already catch real street
addresses, and it removes the remaining false positives. For an archive, where
over-redaction destroys the analytical value of the data, that trade is worth
making.

## 4. Cost and fit for the Lambda

Comprehend bills $0.0001 per 100 characters with a 3-unit minimum, so about
$0.0003 per request, roughly $3 per month at 10,000 requests. The free tier
covers 50,000 units per month for the first year. Actual monthly request volume
is still unknown.

Latency is 40 ms per synchronous call against about 0.2 ms for the local rules.
That is irrelevant for a batch archive job and would matter for anything
interactive.

Package size is not a problem: `boto3` is already in the Lambda Python runtime
and `detectors.py` imports only `re` and `csv`, so this needs no layer and no
container image.

For a large backfill, `StartPiiEntitiesDetectionJob` processes S3 input in bulk
and avoids 15-minute Lambda timeouts. Worth using for the initial load and the
synchronous call for ongoing rows.

## 5. Three bugs found in PR #715

1. `call me` is in the strong-cue list and accepts a lowercase name, so
   **"call me back on 480-555-0198" redacts "back" as a person's name.**
   That phrasing is common in a help request and does not appear in their test
   set.
2. `two` is present as a name token in `users.csv`, so "two are under ten" is
   redacted. The junk filter strips "asdf" and "test" but not number words.
3. An email containing a known user's name is labelled `NAME` rather than
   `EMAIL`: `priya.nair@asu.edu` becomes `[NAME]`. The lookup span sorts first
   and `merge()` keeps the first label. The text is still protected, so this is
   not a leak, but the type is wrong, which matters if labels are ever used to
   decide what to keep.

## 6. The mock data cannot validate this

`data-analytics/sql/requests.csv` has 25 rows and the descriptions are
boilerplate recycled about eight ways ("Household requesting help understanding
paperwork"). There are no names, phones or addresses in it at all, and all four
approaches correctly detect nothing. That is why every submission on this issue
had to invent its own test set, and it is the main thing standing between this
evaluation and a confident decision. A sample of real, anonymised request text
would settle it.

## 7. Recommendation

Approach 4 plus Comprehend, filtered to drop `DATE_TIME`, `AGE` and `ADDRESS`.
Approach 4 handles addresses, formats and spelled-out numbers locally;
Comprehend handles names, which is where the local rules fall down on text they
were not tuned for.

Fix the three bugs above before this becomes the Lambda.

Replacement strategy (what a detected span is swapped for) is a separate
decision from detection and is not covered here.

## 8. How to reproduce

From this directory, with AWS credentials allowed to call
`comprehend:DetectPiiEntities`, alongside the PR #715 files:

    python3 run_everything.py      # Comprehend on both sets, scores everything
    python3 rescore.py             # the entity-type filter comparison

`run_everything.py --no-aws` runs the local approaches only.
