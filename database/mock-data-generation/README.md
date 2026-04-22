# Mock Data Generation

Generates synthetic CSV data for Saayam database tables for testing and development.

## Files

| File | Description |
|------|-------------|
| `generate_users.py` | Generates mock data for the `users` table |
| `generate_fraud_requests_notifications.py` | Generates mock data for `fraud_requests` and `notifications` tables |

## How to Run

```bash
python generate_users.py --count 500 --seed 42
python generate_fraud_requests_notifications.py --fraud 800 --notifications 30000 --seed 42
```

## Output

Files are written to `database/mock_db/`:

| File | Rows |
|------|------|
| `mock_users.csv` | 500 |
| `mock_fraud_requests.csv` | 800 |
| `mock_notifications.csv` | 30,000 |