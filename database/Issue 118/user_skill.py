from __future__ import annotations

from datetime import timedelta

import pandas as pd


def generate_user_skills(volunteer_applications_df: pd.DataFrame) -> pd.DataFrame:
    rows = []

    for _, row in volunteer_applications_df.iterrows():
        user_id = int(row["user_id"])
        created_at = pd.to_datetime(row["created_at"])
        last_updated_at = pd.to_datetime(row["last_updated_at"])

        skill_codes = sorted(
            {
                int(x.strip())
                for x in str(row["skill_codes"]).split(",")
                if x.strip()
            }
        )

        for cat_id in skill_codes:
            rows.append(
                {
                    "user_id": user_id,
                    "cat_id": cat_id,
                    "created_date": created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "last_update_date": (
                        last_updated_at + timedelta(minutes=5)
                    ).strftime("%Y-%m-%d %H:%M:%S"),
                }
            )

    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset=["user_id", "cat_id"]).reset_index(drop=True)
    return df