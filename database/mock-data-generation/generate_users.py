import os
import sys
import random

import pandas as pd

from utils import (
    BASE_DIR, OUTPUT_DIR,
    USER_CATEGORY_IDS, GENDERS, LANGUAGES, AUTH_PROVIDERS,
    fake, make_user_ids, past_datetime, datetime_after,
    fmt_ts, fmt_date, write_csv,
)


def load_states():
    path = os.path.join(BASE_DIR, 'state.csv')
    if not os.path.exists(path):
        print('Error: state.csv not found.')
        sys.exit(1)
    df = pd.read_csv(path)
    return df[['state_id', 'country_id']].dropna().to_dict('records')


def generate_users(count=100):
    print('Generating users.')
    states = load_states()
    user_ids = make_user_ids(count, start=1)
    rows = []

    for uid in user_ids:
        loc = random.choice(states)
        first = fake.first_name()
        last = fake.last_name()
        middle = fake.first_name() if random.random() > 0.6 else ''
        full = ' '.join(p for p in [first, middle, last] if p)
        last_upd = past_datetime(days_back=365)
        import datetime as dt
        wizard_upd = datetime_after(last_upd - dt.timedelta(days=30), max_minutes=43200)

        rows.append({
            'user_id': uid,
            'state_id': str(loc['state_id']),
            'country_id': int(loc['country_id']),
            'user_status_id': random.randint(1, 5),
            'user_category_id': random.choice(USER_CATEGORY_IDS),
            'full_name': full,
            'first_name': first,
            'middle_name': middle,
            'last_name': last,
            'primary_email_address': fake.unique.email(),
            'primary_phone_number': fake.phone_number()[:20],
            'addr_ln1': fake.street_address(),
            'addr_ln2': fake.secondary_address() if random.random() > 0.7 else '',
            'addr_ln3': '',
            'city_name': fake.city(),
            'zip_code': fake.postcode(),
            'last_location': f'{fake.latitude()},{fake.longitude()}',
            'last_update_date': fmt_ts(last_upd) + '+00',
            'time_zone': fake.timezone(),
            'profile_picture_path': f'/images/profiles/{fake.uuid4()}.jpg',
            'gender': random.choice(GENDERS),
            'language_1': random.choice(LANGUAGES[:5]),
            'language_2': random.choice(LANGUAGES[1:]),
            'language_3': 'None',
            'promotion_wizard_stage': random.randint(1, 4),
            'promotion_wizard_last_update_date': fmt_ts(wizard_upd) + '+00',
            'external_auth_provider': random.choice(AUTH_PROVIDERS),
            'dob': fmt_date(fake.date_of_birth(minimum_age=18, maximum_age=80)),
        })

    write_csv(os.path.join(OUTPUT_DIR, 'mock_users.csv'), rows)
    return pd.DataFrame(rows)