import os

from volunteer_applications import generate_volunteer_applications
from user_skills import generate_user_skills
from users import generate_users
from request import generate_request
from request_comments import generate_request_comments
from volunteer_rating import generate_volunteer_rating
from utils import set_seed, write_csv

OUTPUT_DIR = "../mock_db"

def main() -> None:
    set_seed(42)
    
     # create folder if it doesn't exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    user_rows = generate_users(count=100)
    request_rows = generate_request(count=100)
    request_comments_rows = generate_request_comments(request_rows, user_rows, count=100)
    volunteer_rows = generate_volunteer_applications(count=100)
    volunteer_rating_rows = generate_volunteer_rating(user_rows, request_rows, count=100)
    user_skill_rows = generate_user_skills(volunteer_rows)

    write_csv(f"{OUTPUT_DIR}/volunteer_applications.csv", volunteer_rows)
    write_csv(f"{OUTPUT_DIR}/user_skills.csv", user_skill_rows)
    write_csv(f"{OUTPUT_DIR}/users.csv", user_rows)
    write_csv(f"{OUTPUT_DIR}/request.csv", request_rows)
    write_csv(f"{OUTPUT_DIR}/request_comments.csv", request_comments_rows)
    write_csv(f"{OUTPUT_DIR}/volunteer_rating.csv", volunteer_rating_rows)

    print(f"Generated {len(volunteer_rows)} volunteer_applications rows")
    print(f"Generated {len(user_skill_rows)} user_skills rows")
    print(f"Generated {len(user_rows)} users rows")
    print(f"Generated {len(request_rows)} request rows")
    print(f"Generated {len(request_comments_rows)} request_comments rows")
    print(f"Generated {len(volunteer_rating_rows)} volunteer_rating rows")

if __name__ == "__main__":
    main()
