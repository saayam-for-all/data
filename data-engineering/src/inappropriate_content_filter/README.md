# Help-request moderation severity (#422)

This adapts Vighnesh Sridhar's existing SQLite/Groq checker from
`vighneshsridhar-inappropriate_content_filter` (source branch commit
`f64ad0aac2cacc56ab8d137d8c7f3ef9a41bcb44`). The checker is absent from the
current `test` branch, so it is placed in the documented Lambda directory.
The original `bad-words.txt` is reused with trailing whitespace removed.

## Response contract

The handler accepts a JSON object containing string `subject` and `description`
fields, directly or in an API Gateway `body` (JSON string or dictionary).
At least one field must contain text.

Successful responses retain the existing flags and word lists:
`contains_profanity`, `1. profanity`, `contains_depressive_content`,
`contains_suicidal_content`, `2. Depressive/Suicidal Content`,
`contains_threatening_content`, and `3. Threatening Content`.
Normal results also retain `0. This is a normal request`.

The JSON response body adds:

| Score | Detected category |
|---|---|
| 0 | No category detected |
| 1 | Profanity |
| 2 | Depressive and/or suicidal content |
| 3 | Threatening content |

`severity_score` is the highest detected category number.
`severity_categories` contains every detected category in score order, e.g.:

```json
{
  "severity_score": 3,
  "severity_categories": [
    {"score": 1, "category": "profanity"},
    {"score": 3, "category": "threatening"}
  ]
}
```

This is an **implementation assumption for review**, derived from the original
numbered response labels and consistent with the approach described in PR #518.
The numbers encode routing categories; they are not clinical risk estimates.
Both depressive and suicidal flags remain available separately to callers.

## Failure behavior and routing boundary

- Invalid input: HTTP 400.
- Missing/corrupt SQLite database or failed lookup: HTTP 500.
- Failed SSM/Groq call or incomplete/invalid model output: HTTP 502.

Errors contain an `error` field and **no severity score**. A model failure must
not look like score 0 (normal) or an authoritative word-list-only result.
Callers must check the HTTP status before considering routing. Input text and
raw exceptions are not logged or returned.

No help-request database writes or routing destinations are added: #422's scope
asks for returned scores and does not define destination tables. This standalone
Lambda exposes the decision data; wiring a caller to a deployed endpoint and
confirming routing destinations remain integration work.

## Local tests (no credentials or SDK installation needed)

From the repository root:

```powershell
python -m unittest discover -s data-engineering/tests -p test_profanity_severity.py -v
```

Tests create synthetic temporary SQLite databases and mock SSM/Groq calls.
They validate handler behavior and scoring, not the real model's accuracy.
See `LOCAL_TEST_RESULTS.md` for the captured run.

## Runtime preparation (team leads)

1. Install this folder's `requirements.txt` into the Lambda package.
2. Build the word-list database before packaging:

```powershell
python data-engineering/src/inappropriate_content_filter/create_profane_words_db.py
```

3. Package `lambda_function.py`, dependencies, and the generated
   `profane_words.db` together. The database is generated, not committed.
4. Set the handler to `lambda_function.lambda_handler`.
5. Configure the following as needed:

| Environment variable | Default |
|---|---|
| `PROFANE_WORDS_DB` | `profane_words.db` beside the handler |
| `AWS_REGION` | `us-east-1` |
| `GROQ_SSM_PARAMETER` | `/dev/saayam/GenAI/groq/key` (existing checker path) |
| `GROQ_MODEL` | `openai/gpt-oss-120b` (existing checker model) |

The runtime needs access to that SSM parameter (and its KMS key, if applicable)
and network access to Groq. No AWS resources are created or deployed by this PR.
The parameter/model defaults are inherited from the existing code; their live
availability has not been verified. Maintainers should use the appropriate
environment-specific parameter and validate the live integration before release.
