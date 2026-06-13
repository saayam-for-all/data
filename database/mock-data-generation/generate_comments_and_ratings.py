import os

from request_comments import generate_request_comments
from volunteer_rating import generate_volunteer_rating
from utils import set_seed, write_csv, make_user_ids

OUTPUT_DIR = "output_csv_files"


def main() -> None:
    set_seed(42)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    user_ids = make_user_ids(100)
    request_ids = [f"REQ{1000 + i}" for i in range(100)]

    comment_rows = generate_request_comments(
        count=100, user_ids=user_ids, request_ids=request_ids,
    )
    rating_rows = generate_volunteer_rating(
        count=100, user_ids=user_ids, request_ids=request_ids,
    )

    write_csv(f"{OUTPUT_DIR}/request_comments.csv", comment_rows)
    write_csv(f"{OUTPUT_DIR}/volunteer_rating.csv", rating_rows)

    print(f"Generated {len(comment_rows)} request_comments rows")
    print(f"Generated {len(rating_rows)} volunteer_rating rows")


if __name__ == "__main__":
    main()
