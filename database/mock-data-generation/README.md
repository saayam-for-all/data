# Mock Data Generation for Issue #119

This folder contains scripts to generate synthetic CSV data for:

- `request_comments`
- `volunteer_rating`

The script writes outputs to `database/mock_db/`.

## Script

- `generate_request_comments_volunteer_rating.py`

## Usage

Run from repository root:

```bash
python database/mock-data-generation/generate_request_comments_volunteer_rating.py
```

Optional arguments:

```bash
python database/mock-data-generation/generate_request_comments_volunteer_rating.py \
  --rows-request-comments 100 \
  --rows-volunteer-rating 100 \
  --seed 42 \
  --fallback-parent-id-count 100 \
  --db-info database/mock-data-generation/db_info.json \
  --output-dir database/mock_db
```

## Data Integrity Behavior

- If `database/mock_db/request.csv` exists with `req_id`, generated rows reference valid request IDs.
- If `database/mock_db/users.csv` exists with `user_id`, generated rows reference valid user IDs.
- If parent CSVs are missing, the script generates fallback ID pools (`1..N`) to keep foreign keys consistent.

## Output Files

- `database/mock_db/request_comments.csv`
- `database/mock_db/volunteer_rating.csv`

