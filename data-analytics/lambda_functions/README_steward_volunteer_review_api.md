# Steward Dashboard – Review Volunteers API (issue #273)

AWS Lambda API that returns the volunteer applications waiting on a steward
review, for the Steward Dashboard "Review Volunteers" widget.

## Files
- `steward_volunteer_review_api.py` – Lambda handler
- `test_steward_volunteer_review_api.py` – local + cursor-based unit tests

## Table mapping
The issue asks to join the `users` and `volunteers` tables. There is no table
literally named `volunteers` in the schema (`saayam-for-all/database`); the
volunteer review queue is backed by **`volunteer_applications`**, whose
`application_status` enum (`STARTED`, `IN_REVIEW`, `ACCEPTED`, `REJECTED`)
carries the `IN_REVIEW` state a steward acts on. The API filters on
`application_status = 'IN_REVIEW'` and joins `users` on `user_id`.

## Request
```json
{ "page": 1, "page_size": 5 }
```

## Response
```json
{
  "statusCode": 200,
  "body": {
    "data": [
      { "user_id": "SID-00-000-000-001", "updated_time": "2026-05-12T07:15:00Z", "volunteer_review": "Review" }
    ],
    "pagination": { "current_page": 1, "page_size": 5, "total_records": 20, "total_pages": 4 }
  }
}
```
`updated_time` = `volunteer_applications.last_updated_at` (ISO-8601 UTC). Rows
are sorted newest-first. Empty queue returns `200` with `"data": []`. DB errors
return a safe `500` with an empty payload and no internal details.

## Configuration (no hardcoded creds or Parameter Store paths)
SSM parameter *paths* come from environment variables; a region is queried only
when its var is set:

| Env var | Example value |
| --- | --- |
| `VIRGINIA_DB_PARAM` | `/dev/saayam/db/Virginia/Analytics/user` |
| `IRELAND_DB_PARAM` | `/dev/saayam/db/Ireland/Analytics/user` |
| `AWS_REGION` | `us-east-1` (default) |

Both regions are queried, merged, sorted by `last_updated_at DESC`, then
paginated so the combined order is correct.

## Testing locally
```bash
cd data-analytics/lambda_functions
python  test_steward_volunteer_review_api.py     # no pytest needed
pytest  test_steward_volunteer_review_api.py -q  # or via pytest
```
The tests mock the DB layer (`connect_region`) with a fake cursor, so no live
database or AWS access is required. Do not deploy directly to AWS — submit via
pull request.
