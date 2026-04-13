import os
import json
import pandas as pd

from utils import GLOBAL_DATA, generate_value, set_seed, NUM_RECORDS
from user_skills import generate_user_skills
from volunteer_applications import generate_volunteer_applications


# OUTPUT FOLDER
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "mock_db")

os.makedirs(OUTPUT_DIR, exist_ok=True)


# ONLY THESE TABLES WILL RUN
TARGET_TABLES = {"user_skills", "volunteer_applications"}



# DETECTION
def is_user_skills(cols):
    names = {c["name"] for c in cols}
    return {"user_id", "cat_id"}.issubset(names)


def is_volunteer(cols):
    names = {c["name"] for c in cols}
    return {"user_id", "skill_codes", "application_status"}.issubset(names)


# MAIN
def main():
    set_seed(42)

    db_path = os.path.join(BASE_DIR, "db_info.json")

    with open(db_path) as f:
        schema = json.load(f)

    tables = schema["tables"]


    # PASS 1: BUILD BASE DATA (ONLY IF NEEDED)

    for table_name, table_def in tables.items():

        # SKIP EVERYTHING EXCEPT TARGET TABLES
        if table_name not in TARGET_TABLES:
            continue

        # build base rows (for relationship support)
        rows = [
            {
                col["name"]: generate_value(col["name"], col["type"])
                for col in table_def["columns"]
            }
            for _ in range(NUM_RECORDS)
        ]

        df = pd.DataFrame(rows)

        # store relationships if present
        if "user_id" in df.columns:
            GLOBAL_DATA["users"] = df["user_id"].astype(str).tolist()

        if "cat_id" in df.columns:
            GLOBAL_DATA["categories"] = df["cat_id"].astype(str).tolist()


    # PASS 2: GENERATE ONLY TARGET TABLE OUTPUTS
    for table_name, table_def in tables.items():

        if table_name == "user_skills":
            df = pd.DataFrame(generate_user_skills())

        elif table_name == "volunteer_applications":
            df = pd.DataFrame(generate_volunteer_applications())

        else:
            continue

        output_file = os.path.join(OUTPUT_DIR, f"{table_name}.csv")
        df.to_csv(output_file, index=False)

    print(f"Generated tables: {TARGET_TABLES}")
    print(f"Output Data Updated successfully to this path: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()