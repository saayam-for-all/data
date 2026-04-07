import os
import sys
import csv
import random
from datetime import datetime, timedelta
from typing import Any, Dict, List

import pandas as pd
from faker import Faker

fake = Faker()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, '..', 'mock_db')
os.makedirs(OUTPUT_DIR, exist_ok=True)


def seed_all(seed=42):
    random.seed(seed)
    Faker.seed(seed)


def load_csv(filename):
    path = os.path.join(BASE_DIR, filename)
    if not os.path.exists(path):
        print(f"Error: {filename} not found at {path}")
        sys.exit(1)
    return pd.read_csv(path)


NOTIFICATION_TYPES_DF = load_csv('notification_types.csv')
NOTIFICATION_CHANNELS_DF = load_csv('notification_channels.csv')
USER_CATEGORY_DF = load_csv('user_category.csv')

NOTIFICATION_TYPE_IDS = NOTIFICATION_TYPES_DF['type_id'].tolist()
NOTIFICATION_CHANNEL_IDS = NOTIFICATION_CHANNELS_DF['channel_id'].tolist()
USER_CATEGORY_IDS = USER_CATEGORY_DF['user_category_id'].tolist()

NOTIFICATION_STATUSES = ['PENDING', 'SENT', 'DELIVERED', 'READ', 'FAILED']

GENDERS = ['Male', 'Female', 'Non-Binary', 'Prefer not to say']

LANGUAGES = ['English', 'Spanish', 'Hindi', 'Mandarin', 'Arabic', 'French', 'None']

AUTH_PROVIDERS = ['Google', 'Apple', 'Facebook', 'None']

FRAUD_REASONS = [
    'Volunteer requested cash payment outside the platform.',
    'User submitted the same help request multiple times.',
    'Profile photo and government ID do not match.',
    'Suspicious login from an unrecognised device and location.',
    'Volunteer marked request complete without providing any help.',
    'User sent phishing links through in-app messaging.',
    'Duplicate account detected linked to same phone number.',
    'Request description contained misleading information.',
    'User attempted to collect personal data from other members.',
    'Automated activity pattern detected on this account.',
]

NOTIFICATION_MESSAGES = {
    1: [
        'Unusual sign-in detected on your account. Please verify it was you.',
        'Scheduled platform downtime tonight from 1 AM to 3 AM.',
        'Your password has not been changed in 90 days.',
        'Complete your profile to continue using the platform.',
    ],
    10: [
        'Your volunteer shift starts in 24 hours.',
        'The community event you signed up for is this Saturday.',
        'Please confirm your attendance for tomorrow session.',
        'Your appointment is in less than 12 hours.',
    ],
    11: [
        'New message from a beneficiary on your active request.',
        'A steward replied to your query.',
        'A volunteer responded to your help post.',
        'You have an unread message from a matched user.',
    ],
    12: [
        'Your volunteer application has been approved.',
        'We need more documents to proceed with your application.',
        'Your application is under review.',
        'Background verification completed.',
    ],
    13: [
        'You have clocked 25 volunteer hours.',
        'Badge unlocked: First Responder.',
        'You helped 5 people this month.',
        'One year on the platform, thank you.',
    ],
}


def past_datetime(days_back=180):
    return fake.date_time_between(start_date=f'-{days_back}d', end_date='now')


def datetime_after(base, max_minutes=2880):
    return base + timedelta(minutes=random.randint(1, max_minutes))


def fmt_ts(dt):
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def fmt_date(dt):
    return dt.strftime('%Y-%m-%d')


def make_user_ids(count, start=1):
    return [f'U{start + i}' for i in range(count)]


def write_csv(filepath, rows):
    if not rows:
        raise ValueError(f'No rows to write for {filepath}')
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f'Saved {os.path.basename(filepath)} ({len(rows)} rows)')