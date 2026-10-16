# Local verification — issue #422

Run date: October 16, 2026. Environment: Linux, Python 3.12.14.
This run was performed in the assistant's isolated checkout, not on Rohit's
Windows laptop. No production data, credentials, live model calls or AWS
deployment were used.

## Automated contract tests

Command:

```text
python -m unittest discover -s data-engineering/tests -p test_profanity_severity.py -v
```

Captured output (error log lines are expected in failure-path tests):

```text
test_both_categories_preserved_and_highest_wins (test_profanity_severity.HandlerTests.test_both_categories_preserved_and_highest_wins) ... ok
test_corrupt_database_is_error (test_profanity_severity.HandlerTests.test_corrupt_database_is_error) ... Profanity word-list lookup failed.
ok
test_database_builder_is_idempotent (test_profanity_severity.HandlerTests.test_database_builder_is_idempotent) ... ok
test_direct_and_dictionary_body_requests (test_profanity_severity.HandlerTests.test_direct_and_dictionary_body_requests) ... ok
test_invalid_requests_do_not_call_model (test_profanity_severity.HandlerTests.test_invalid_requests_do_not_call_model) ... ok
test_long_input_uses_batched_sql_queries (test_profanity_severity.HandlerTests.test_long_input_uses_batched_sql_queries) ... ok
test_malformed_model_response_returns_error (test_profanity_severity.HandlerTests.test_malformed_model_response_returns_error) ... Moderation model call or response validation failed.
ok
test_missing_database_is_error_not_normal_score (test_profanity_severity.HandlerTests.test_missing_database_is_error_not_normal_score) ... Profanity word-list lookup failed.
ok
test_missing_database_table_is_error (test_profanity_severity.HandlerTests.test_missing_database_table_is_error) ... Profanity word-list lookup failed.
ok
test_model_failure_returns_502_even_with_local_profanity (test_profanity_severity.HandlerTests.test_model_failure_returns_502_even_with_local_profanity) ... ok
test_normal_request (test_profanity_severity.HandlerTests.test_normal_request) ... ok
test_punctuation_only_does_not_generate_invalid_sql (test_profanity_severity.HandlerTests.test_punctuation_only_does_not_generate_invalid_sql) ... ok
test_singular_matching_keeps_original_word (test_profanity_severity.HandlerTests.test_singular_matching_keeps_original_word) ... ok
test_unicode_and_original_punctuation_reach_model (test_profanity_severity.HandlerTests.test_unicode_and_original_punctuation_reach_model) ... ok
test_word_list_and_model_profanity_are_merged (test_profanity_severity.HandlerTests.test_word_list_and_model_profanity_are_merged) ... ok
test_empty_ssm_secret_does_not_construct_model_client (test_profanity_severity.ModelBoundaryTests.test_empty_ssm_secret_does_not_construct_model_client) ... ok
test_fenced_json_is_supported (test_profanity_severity.ModelBoundaryTests.test_fenced_json_is_supported) ... ok
test_invalid_json_raises_and_closes_client (test_profanity_severity.ModelBoundaryTests.test_invalid_json_raises_and_closes_client) ... ok
test_missing_completion_raises (test_profanity_severity.ModelBoundaryTests.test_missing_completion_raises) ... ok
test_sdk_error_closes_client (test_profanity_severity.ModelBoundaryTests.test_sdk_error_closes_client) ... ok
test_ssm_value_is_extracted_and_user_text_is_separate (test_profanity_severity.ModelBoundaryTests.test_ssm_value_is_extracted_and_user_text_is_separate) ... ok
test_all_sixteen_flag_combinations (test_profanity_severity.SeverityTests.test_all_sixteen_flag_combinations) ... ok
test_detected_phrases_cannot_be_scored_normal (test_profanity_severity.SeverityTests.test_detected_phrases_cannot_be_scored_normal) ... ok
test_model_cannot_override_score_or_inject_extra_fields (test_profanity_severity.SeverityTests.test_model_cannot_override_score_or_inject_extra_fields) ... ok
test_rejects_invalid_model_shapes (test_profanity_severity.SeverityTests.test_rejects_invalid_model_shapes) ... ok

----------------------------------------------------------------------
Ran 25 tests in 0.105s

OK
```

The flag-combination test checks all 16 combinations inside one test method.

## SDK compatibility smoke check

Installed this Lambda's pinned requirements in an isolated virtual environment.
`pip check` returned `No broken requirements found.`

A separate smoke check used real boto3/Groq SDKs with botocore Stubber and
httpx MockTransport. SSM returned a synthetic key; Groq received a mocked HTTP
completion. It checked extraction of the SSM parameter value and produced score
3 from the synthetic threatening-content response. No external API was invoked.

```text
SDK smoke test: PASS (real boto3/Groq SDKs; stubbed SSM and mocked HTTP; no live API calls)
boto3: 1.43.114 groq: 1.7.0
Normal: {"severity_score": 0, "severity_categories": []}
Profanity: {"severity_score": 1, "severity_categories": [{"score": 1, "category": "profanity"}]}
Depressive: {"severity_score": 2, "severity_categories": [{"score": 2, "category": "depressive_suicidal"}]}
Suicidal: {"severity_score": 2, "severity_categories": [{"score": 2, "category": "depressive_suicidal"}]}
Threatening: {"severity_score": 3, "severity_categories": [{"score": 3, "category": "threatening"}]}
Mixed: {"severity_score": 3, "severity_categories": [{"score": 1, "category": "profanity"}, {"score": 2, "category": "depressive_suicidal"}, {"score": 3, "category": "threatening"}]}
```

## Limits

This validates the implementation and SDK interface, not the model's real
classification accuracy, IAM permissions, live SSM parameter, deployment package
or deployed Help Request integration. Destination tables and routing rules are
not defined in the issue, so this PR returns scores without database routing.
The score mapping and highest-score precedence are documented assumptions for
maintainer review.
