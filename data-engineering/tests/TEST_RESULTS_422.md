# Test Results — Issue #422: Profanity severity scores and Help Request routing

**Module:** `src/inappropriate_content_filter/inappropriate_content_filter.py`
**Tests:** `tests/test_inappropriate_content_filter.py`
**Run:** 2026-10-20, Windows 11, Python 3.12.7, pytest 9.1.1

```
cd data-engineering
SECRET_KEY=test-secret python -m pytest tests/test_inappropriate_content_filter.py -v
```

## Score → route mapping under test

| Score | Label | `route_to` | `allow_active_matching` |
|---|---|---|---|
| 0 | Good Request | `request` | true |
| 1 | Foul Language | `fraud_requests` | false |
| 2 | Depressive or Suicidal | `fraud_requests` | false |
| 3 | Threatening | `fraud_requests` | false |

If more than one category is flagged, the highest score wins.

## What is mocked

- **Groq model call (`get_llm_flags`)**: patched to return fixed flags or to raise. No network or AWS access.
- **Word-list DB**: most tests build a two-word `profane_words.db` in a temp folder. `test_shipped_word_list_builds_and_scores` builds the DB from the real `bad-words.txt` with `create_profane_words_db()` and scores against it.

## Results

```
collecting ... collected 39 items

tests/test_inappropriate_content_filter.py::test_get_severity_score[flags0-0] PASSED
tests/test_inappropriate_content_filter.py::test_get_severity_score[flags1-1] PASSED
tests/test_inappropriate_content_filter.py::test_get_severity_score[flags2-2] PASSED
tests/test_inappropriate_content_filter.py::test_get_severity_score[flags3-2] PASSED
tests/test_inappropriate_content_filter.py::test_get_severity_score[flags4-3] PASSED
tests/test_inappropriate_content_filter.py::test_get_severity_score[flags5-2] PASSED
tests/test_inappropriate_content_filter.py::test_get_severity_score[flags6-3] PASSED
tests/test_inappropriate_content_filter.py::test_severity_labels_cover_all_scores PASSED
tests/test_inappropriate_content_filter.py::test_score_zero_routes_to_active_matching PASSED
tests/test_inappropriate_content_filter.py::test_flagged_scores_route_to_fraud_requests[1] PASSED
tests/test_inappropriate_content_filter.py::test_flagged_scores_route_to_fraud_requests[2] PASSED
tests/test_inappropriate_content_filter.py::test_flagged_scores_route_to_fraud_requests[3] PASSED
tests/test_inappropriate_content_filter.py::test_invalid_score_is_rejected[-1] PASSED
tests/test_inappropriate_content_filter.py::test_invalid_score_is_rejected[4] PASSED
tests/test_inappropriate_content_filter.py::test_invalid_score_is_rejected[True] PASSED
tests/test_inappropriate_content_filter.py::test_invalid_score_is_rejected[False] PASSED
tests/test_inappropriate_content_filter.py::test_invalid_score_is_rejected[1] PASSED
tests/test_inappropriate_content_filter.py::test_invalid_score_is_rejected[None] PASSED
tests/test_inappropriate_content_filter.py::test_invalid_score_is_rejected[1.5] PASSED
tests/test_inappropriate_content_filter.py::test_clean_request_goes_to_request_table PASSED
tests/test_inappropriate_content_filter.py::test_word_list_match_scores_foul_language PASSED
tests/test_inappropriate_content_filter.py::test_plural_word_is_matched PASSED
tests/test_inappropriate_content_filter.py::test_llm_profanity_is_merged_with_word_list PASSED
tests/test_inappropriate_content_filter.py::test_model_flags_route_to_fraud_requests[flags0-2-Depressive or Suicidal] PASSED
tests/test_inappropriate_content_filter.py::test_model_flags_route_to_fraud_requests[flags1-2-Depressive or Suicidal] PASSED
tests/test_inappropriate_content_filter.py::test_model_flags_route_to_fraud_requests[flags2-3-Threatening] PASSED
tests/test_inappropriate_content_filter.py::test_profanity_and_threat_routes_by_highest PASSED
tests/test_inappropriate_content_filter.py::test_llm_failure_still_uses_word_list PASSED
tests/test_inappropriate_content_filter.py::test_llm_failure_on_clean_text_is_marked_unchecked PASSED
tests/test_inappropriate_content_filter.py::test_missing_groq_key_falls_back_to_word_list PASSED
tests/test_inappropriate_content_filter.py::test_only_punctuation_does_not_crash PASSED
tests/test_inappropriate_content_filter.py::test_bad_input_returns_400[event0] PASSED
tests/test_inappropriate_content_filter.py::test_bad_input_returns_400[event1] PASSED
tests/test_inappropriate_content_filter.py::test_bad_input_returns_400[event2] PASSED
tests/test_inappropriate_content_filter.py::test_bad_input_returns_400[event3] PASSED
tests/test_inappropriate_content_filter.py::test_bad_input_returns_400[event4] PASSED
tests/test_inappropriate_content_filter.py::test_missing_db_returns_500 PASSED
tests/test_inappropriate_content_filter.py::test_response_keeps_cors_headers PASSED
tests/test_inappropriate_content_filter.py::test_shipped_word_list_builds_and_scores PASSED

============================= 39 passed in 0.34s ==============================
```

The full `tests/` suite (which also includes `test_organization_analytics.py`) passed: **48 passed**.

## Manual smoke test (real word list, no `GROQ_API_KEY`)

```
200 {'severity_score': 0, 'severity_label': 'Good Request', 'route_to': 'request', 'allow_active_matching': True, 'llm_checked': False}
200 {'severity_score': 1, 'severity_label': 'Foul Language', 'route_to': 'fraud_requests', 'allow_active_matching': False, 'llm_checked': False}
```

Inputs: "Groceries / Need help carrying groceries home" and "Help / this crap landlord won't fix the heater".

## Not covered

- **Live Groq call:** not run, because it needs `GROQ_API_KEY`. Scores 2 and 3 come from the model, so they are tested only through mocked model flags.
- **Deployed Lambda in AWS:** not tested.
