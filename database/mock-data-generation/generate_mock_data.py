
import os
from request_comments import generate_request_comments
from volunteer_rating import generate_volunteer_rating
from volunteer_applications import generate_volunteer_applications
from user_skills import generate_user_skills
from utils import set_seed, write_csv

OUTPUT_DIR = "../mock_db"

def main() -> None:
    set_seed(42)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    volunteer_rows = generate_volunteer_applications(count=100)
    user_skill_rows = generate_user_skills(volunteer_rows)

    write_csv(f"{OUTPUT_DIR}/volunteer_applications.csv", volunteer_rows)
    write_csv(f"{OUTPUT_DIR}/user_skills.csv", user_skill_rows)

    request_comment_rows = generate_request_comments(count=100)
    write_csv(
        os.path.join(OUTPUT_DIR, "request_comments.csv"),
        request_comment_rows,
    )

    volunteer_rating_rows = generate_volunteer_rating(count=100)
    write_csv(
        os.path.join(OUTPUT_DIR, "volunteer_rating.csv"),
        volunteer_rating_rows,
    )

    print(f"Generated {len(volunteer_rows)} volunteer_applications rows")
    print(f"Generated {len(user_skill_rows)} user_skills rows")
    print(f"Generated {len(request_comment_rows)} request_comments rows")
    print(f"Generated {len(volunteer_rating_rows)} volunteer_rating rows")


if __name__ == "__main__":
    main()

   


