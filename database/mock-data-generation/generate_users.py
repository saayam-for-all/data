import json
import random
from faker import Faker

fake = Faker()

# Load schema
with open("db_info.json", "r") as f:
    schema = json.load(f)

users_table = schema["tables"]["users"]

rows = []

# change this if needed
NUM_ROWS = 20

for i in range(NUM_ROWS):
    row = {}

    for col in users_table["columns"]:
        col_name = col["name"]
        col_type = col["type"]

        # simple type mapping
        if "id" in col_name:
            row[col_name] = i + 1

        elif col_type == "string":
            if "email" in col_name:
                row[col_name] = fake.email()
            elif "name" in col_name:
                row[col_name] = fake.name()
            else:
                row[col_name] = fake.word()

        elif col_type == "int":
            row[col_name] = random.randint(1, 100)

        elif col_type == "date":
            row[col_name] = fake.date()

        else:
            row[col_name] = None

    rows.append(row)

# print result
for r in rows:
    print(r)