import os

from volunteer_applications import generate_volunteer_applications
from user_skills import generate_user_skills
from utils import set_seed, write_csv

OUTPUT_DIR = "../mock_db"

def main() -> None:
    set_seed(42)
    
     # create folder if it doesn't exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    volunteer_rows = generate_volunteer_applications(count=2000)
    user_skill_rows = generate_user_skills(volunteer_rows)

    write_csv(f"{OUTPUT_DIR}/volunteer_applications.csv", volunteer_rows)
    write_csv(f"{OUTPUT_DIR}/user_skills.csv", user_skill_rows)

    print(f"Generated {len(volunteer_rows)} volunteer_applications rows")
    print(f"Generated {len(user_skill_rows)} user_skills rows")


if __name__ == "__main__":
    main()
