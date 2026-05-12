import os
import random
from datetime import datetime, timedelta

import pandas as pd
from faker import Faker

fake = Faker()

random.seed(42)
Faker.seed(42)


def load_lookup(lookup_dir, file_name):
    path = os.path.join(lookup_dir, file_name)

    if not os.path.exists(path):
        print(f"Missing lookup file: {file_name}")
        return pd.DataFrame()

    return pd.read_csv(path)


def get_id_values(df):
    if df.empty:
        return [1]

    id_cols = [
        col for col in df.columns
        if col.lower() == "id"
        or col.lower().endswith("_id")
    ]

    if id_cols:
        return df[id_cols[0]].dropna().tolist()

    return df.iloc[:, 0].dropna().tolist()


def random_datetime(start_year=2022, end_year=2026):
    start_date = datetime(start_year, 1, 1)
    end_date = datetime(end_year, 12, 31)

    diff = end_date - start_date

    return start_date + timedelta(
        days=random.randint(0, diff.days),
        seconds=random.randint(0, 86400)
    )