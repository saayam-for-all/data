"""
generate_fraud_requests.py
==========================
Generates synthetic mock data for the `fraud_requests` table.

Schema:
    fraud_request_id  : integer (PK)
    user_id           : character varying(255) → FK to users
    request_datetime  : timestamp without time zone
    reason            : character varying(255)

Usage:
    python generate_fraud_requests.py [--rows 800] [--output fraud_requests.csv]

Dependencies:
    pip install faker pandas
"""

import argparse
import random
from datetime import datetime, timedelta

import pandas as pd
from faker import Faker

fake = Faker()
random.seed(42)
Faker.seed(42)

# ── Realistic fraud reason templates ──────────────────────────────────────────
FRAUD_REASONS = [
    "Multiple help requests submitted within a short time window",
    "User submitted duplicate requests with slightly altered details",
    "Request location does not match user's registered address",
    "Suspicious pattern: same request submitted from different accounts",
    "User flagged for providing inconsistent personal information",
    "Request details do not align with stated emergency severity",
    "Account created recently with immediate high-priority request",
    "User IP address flagged in multiple fraud reports",
    "Request submitted on behalf of non-existent third party",
    "Volunteer reported suspicious interaction during request fulfillment",
    "User profile picture found to be stock image",
    "Phone number linked to previously banned account",
    "Request category mismatch with provided supporting documents",
    "User contacted multiple volunteers simultaneously for the same request",
    "Automated pattern detection flagged abnormal submission frequency",
    "User submitted request outside of stated availability region",
    "Reported by another community member for misuse of platform",
    "Email address associated with previously flagged account",
    "Inconsistent language used across multiple requests",
    "Request marked fraudulent after volunteer verification visit",
]


def generate_user_ids(n=500):
    """Generate a pool of realistic user_ids (UUID-style, matching users table)."""
    return [f"usr-{fake.uuid4()[:8]}-{fake.uuid4()[:4]}" for _ in range(n)]


def generate_fraud_requests(num_rows: int, user_pool: list) -> pd.DataFrame:
    start_date = datetime(2022, 1, 1)
    end_date = datetime(2025, 3, 31)
    date_range = (end_date - start_date).days

    records = []
    for i in range(1, num_rows + 1):
        request_dt = start_date + timedelta(
            days=random.randint(0, date_range),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
            seconds=random.randint(0, 59),
        )
        records.append({
            "fraud_request_id": i,
            "user_id": random.choice(user_pool),
            "request_datetime": request_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "reason": random.choice(FRAUD_REASONS),
        })

    return pd.DataFrame(records)


def main():
    parser = argparse.ArgumentParser(description="Generate fraud_requests mock data")
    parser.add_argument("--rows", type=int, default=800, help="Number of rows to generate")
    parser.add_argument("--output", type=str, default="fraud_requests.csv", help="Output CSV file path")
    args = parser.parse_args()

    print(f"Generating {args.rows} rows for fraud_requests...")
    user_pool = generate_user_ids(500)
    df = generate_fraud_requests(args.rows, user_pool)
    df.to_csv(args.output, index=False)
    print(f"✅ Saved: {args.output}  ({len(df)} rows, {len(df.columns)} columns)")
    print(f"   Columns: {list(df.columns)}")


if __name__ == "__main__":
    main()
