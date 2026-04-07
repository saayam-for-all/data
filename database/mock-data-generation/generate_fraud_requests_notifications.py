import os
import random

import pandas as pd

from utils import (
    OUTPUT_DIR,
    FRAUD_REASONS,
    NOTIFICATION_TYPE_IDS, NOTIFICATION_CHANNEL_IDS,
    NOTIFICATION_STATUSES, NOTIFICATION_MESSAGES,
    past_datetime, datetime_after, fmt_ts, write_csv,
)


def generate_fraud_requests(users_df, count=100):
    print('Generating fraud requests.')
    user_ids = users_df['user_id'].tolist()
    rows = []

    for i in range(1, count + 1):
        rows.append({
            'fraud_request_id': i,
            'user_id': random.choice(user_ids),
            'request_datetime': fmt_ts(past_datetime(days_back=90)),
            'reason': random.choice(FRAUD_REASONS),
        })

    write_csv(os.path.join(OUTPUT_DIR, 'mock_fraud_requests.csv'), rows)
    return pd.DataFrame(rows)


def generate_notifications(users_df, count=100):
    print('Generating notifications...')
    user_ids = users_df['user_id'].tolist()
    rows = []

    for i in range(1, count + 1):
        created_at = past_datetime(days_back=180)
        type_id = random.choice(NOTIFICATION_TYPE_IDS)
        message = random.choice(NOTIFICATION_MESSAGES.get(type_id, ['You have a new notification.']))

        rows.append({
            'notification_id': i,
            'user_id': random.choice(user_ids),
            'type_id': type_id,
            'channel_id': random.choice(NOTIFICATION_CHANNEL_IDS),
            'message': message,
            'status': random.choice(NOTIFICATION_STATUSES),
            'created_at': fmt_ts(created_at),
            'last_update_date': fmt_ts(datetime_after(created_at, max_minutes=1440)),
        })

    write_csv(os.path.join(OUTPUT_DIR, 'mock_notifications.csv'), rows)
    return pd.DataFrame(rows)