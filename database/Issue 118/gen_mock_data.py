from __future__ import annotations

from pathlib import Path

from vol_appl import generate_volunteer_applications
from user_skill import generate_user_skills


BASE_DIR = Path(__file__).resolve().parent


def main() -> None:
    rows_input = input(
        "Enter number of volunteer application rows to generate [default 100]: "
    ).strip()

    seed_input = input(
        "Enter random seed [default 42]: "
    ).strip()

    row_count = int(rows_input) if rows_input else 100
    seed = int(seed_input) if seed_input else 42

    volunteer_applications_df = generate_volunteer_applications(
        row_count=row_count,
        seed=seed,
    )
    user_skills_df = generate_user_skills(volunteer_applications_df)

    volunteer_out = BASE_DIR / "volunteer_applications.csv"
    skills_out = BASE_DIR / "user_skills.csv"

    volunteer_applications_df.to_csv(volunteer_out, index=False)
    user_skills_df.to_csv(skills_out, index=False)

    print(f"\nSaved: {volunteer_out.name}")
    print(f"Saved: {skills_out.name}")
    print(f"volunteer_applications rows: {len(volunteer_applications_df)}")
    print(f"user_skills rows: {len(user_skills_df)}")


if __name__ == "__main__":
    main()