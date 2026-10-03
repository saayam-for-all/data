import json
import pandas as pd
import os
import unittest
from io import StringIO


def load_data(sql_dir):
    users_df = pd.read_csv(os.path.join(sql_dir, "users.csv"))
    volunteers_df = pd.read_csv(os.path.join(sql_dir, "volunteer_details.csv"))
    volunteers_df["last_updated_at"] = pd.to_datetime(volunteers_df["last_updated_at"])
    return users_df, volunteers_df


def get_volunteer_reviews(users_df, volunteers_df, page=1, page_size=5):
    merged = users_df[["user_id"]].merge(volunteers_df[["user_id", "last_updated_at"]], on="user_id", how="inner")
    merged = merged.sort_values("last_updated_at", ascending=False).reset_index(drop=True)

    total_records = len(merged)
    total_pages = max(1, (total_records + page_size - 1) // page_size)

    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    end = start + page_size
    page_data = merged.iloc[start:end]

    data = [
        {
            "user_id": row["user_id"],
            "updated_time": row["last_updated_at"].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "volunteer_review": "Review"
        }
        for _, row in page_data.iterrows()
    ]

    return {
        "statusCode": 200,
        "body": {
            "data": data,
            "pagination": {
                "current_page": page,
                "page_size": page_size,
                "total_records": total_records,
                "total_pages": total_pages
            }
        }
    }


def safe_error_response():
    return {
        "statusCode": 500,
        "body": {
            "data": [],
            "pagination": {
                "current_page": 1,
                "page_size": 5,
                "total_records": 0,
                "total_pages": 0
            }
        }
    }


class TestStewardVolunteerReview(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        users_csv = StringIO(
            "user_id,state_id,country_id,user_status_id,user_category_id,full_name\n"
            "SID-001,NULL,1,1,1,User One\n"
            "SID-002,NULL,1,1,1,User Two\n"
            "SID-003,NULL,1,1,1,User Three\n"
            "SID-004,NULL,1,1,1,User Four\n"
            "SID-005,NULL,1,1,1,User Five\n"
            "SID-006,NULL,1,1,1,User Six\n"
            "SID-007,NULL,1,1,1,User Seven\n"
        )
        volunteers_csv = StringIO(
            "user_id,terms_and_conditions,terms_accepted_at,govt_id_path1,govt_id_path2,"
            "path1_updated_at,path2_updated_at,availability_days,availability_times,"
            "created_at,last_updated_at\n"
            "SID-001,TRUE,2026-01-01,,,,,,,,2026-05-12 07:15:00\n"
            "SID-002,TRUE,2026-01-01,,,,,,,,2026-05-12 07:14:12\n"
            "SID-003,TRUE,2026-01-01,,,,,,,,2026-05-12 07:13:25\n"
            "SID-004,TRUE,2026-01-01,,,,,,,,2026-05-12 07:12:08\n"
            "SID-005,TRUE,2026-01-01,,,,,,,,2026-05-12 07:10:45\n"
            "SID-006,TRUE,2026-01-01,,,,,,,,2026-05-11 09:00:00\n"
        )
        cls.users_df = pd.read_csv(users_csv)
        cls.volunteers_df = pd.read_csv(volunteers_csv)
        cls.volunteers_df["last_updated_at"] = pd.to_datetime(cls.volunteers_df["last_updated_at"])

    def test_first_page(self):
        result = get_volunteer_reviews(self.users_df, self.volunteers_df, page=1, page_size=5)
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(len(result["body"]["data"]), 5)
        self.assertEqual(result["body"]["pagination"]["current_page"], 1)
        self.assertEqual(result["body"]["pagination"]["total_records"], 6)
        self.assertEqual(result["body"]["pagination"]["total_pages"], 2)

    def test_second_page(self):
        result = get_volunteer_reviews(self.users_df, self.volunteers_df, page=2, page_size=5)
        self.assertEqual(len(result["body"]["data"]), 1)
        self.assertEqual(result["body"]["pagination"]["current_page"], 2)

    def test_descending_order(self):
        result = get_volunteer_reviews(self.users_df, self.volunteers_df, page=1, page_size=6)
        data = result["body"]["data"]
        times = [d["updated_time"] for d in data]
        self.assertEqual(times, sorted(times, reverse=True))

    def test_review_action_present(self):
        result = get_volunteer_reviews(self.users_df, self.volunteers_df, page=1, page_size=5)
        for row in result["body"]["data"]:
            self.assertEqual(row["volunteer_review"], "Review")

    def test_user_id_present(self):
        result = get_volunteer_reviews(self.users_df, self.volunteers_df, page=1, page_size=5)
        for row in result["body"]["data"]:
            self.assertIn("user_id", row)
            self.assertTrue(row["user_id"].startswith("SID-"))

    def test_empty_result(self):
        empty_volunteers = pd.DataFrame(columns=self.volunteers_df.columns)
        empty_volunteers["last_updated_at"] = pd.to_datetime(empty_volunteers["last_updated_at"])
        result = get_volunteer_reviews(self.users_df, empty_volunteers, page=1, page_size=5)
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(result["body"]["data"], [])
        self.assertEqual(result["body"]["pagination"]["total_records"], 0)

    def test_custom_page_size(self):
        result = get_volunteer_reviews(self.users_df, self.volunteers_df, page=1, page_size=3)
        self.assertEqual(len(result["body"]["data"]), 3)
        self.assertEqual(result["body"]["pagination"]["page_size"], 3)
        self.assertEqual(result["body"]["pagination"]["total_pages"], 2)

    def test_page_beyond_total(self):
        result = get_volunteer_reviews(self.users_df, self.volunteers_df, page=99, page_size=5)
        self.assertEqual(result["body"]["pagination"]["current_page"], 2)

    def test_response_structure(self):
        result = get_volunteer_reviews(self.users_df, self.volunteers_df, page=1, page_size=5)
        self.assertIn("statusCode", result)
        self.assertIn("body", result)
        self.assertIn("data", result["body"])
        self.assertIn("pagination", result["body"])
        pagination = result["body"]["pagination"]
        self.assertIn("current_page", pagination)
        self.assertIn("page_size", pagination)
        self.assertIn("total_records", pagination)
        self.assertIn("total_pages", pagination)

    def test_no_matching_users(self):
        other_users = pd.DataFrame({"user_id": ["SID-999"], "full_name": ["Nobody"]})
        result = get_volunteer_reviews(other_users, self.volunteers_df, page=1, page_size=5)
        self.assertEqual(result["body"]["data"], [])
        self.assertEqual(result["body"]["pagination"]["total_records"], 0)

    def test_safe_error_response(self):
        result = safe_error_response()
        self.assertEqual(result["statusCode"], 500)
        self.assertEqual(result["body"]["data"], [])


def run_test_cases():
    sql_dir = os.path.join(os.path.dirname(__file__), "..", "sql")

    try:
        users_df, volunteers_df = load_data(sql_dir)
    except Exception as e:
        print(f"Error loading data: {e}")
        print(json.dumps(safe_error_response(), indent=2))
        return

    test_payloads = [
        {"label": "Page 1, 5 rows", "page": 1, "page_size": 5},
        {"label": "Page 2, 5 rows", "page": 2, "page_size": 5},
        {"label": "Page 1, 10 rows", "page": 1, "page_size": 10},
        {"label": "Page beyond total", "page": 99, "page_size": 5},
    ]

    results = {}

    for test in test_payloads:
        label = test["label"]
        response = get_volunteer_reviews(users_df, volunteers_df, test["page"], test["page_size"])
        request_payload = {"page": test["page"], "page_size": test["page_size"]}
        results[label] = {"request": request_payload, "response": response}

        print(f"\n=== {label} ===")
        print(f"Request: {json.dumps(request_payload, indent=2)}")
        print(f"Response: {json.dumps(response, indent=2)}")

    output_path = os.path.join(sql_dir, "steward_volunteer_review_test_results.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nTest results saved to {output_path}")


def main():
    print("=" * 60)
    print("RUNNING UNIT TESTS")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestStewardVolunteerReview)
    runner = unittest.TextTestRunner(verbosity=2)
    test_result = runner.run(suite)

    print("\n" + "=" * 60)
    print("RUNNING TEST CASES WITH MOCK DATA")
    print("=" * 60)

    run_test_cases()

    if test_result.wasSuccessful():
        print("\nAll unit tests passed.")
    else:
        print("\nSome unit tests failed.")


if __name__ == "__main__":
    main()
