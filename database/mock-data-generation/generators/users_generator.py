import random
from faker import Faker

fake = Faker()

def generate_users(schema, fk_store, num_rows=20):

    users_table = schema["tables"]["users"]
    rows = []

    for i in range(num_rows):
        row = {}

        for col in users_table["columns"]:
            col_name = col["name"]
            col_type = col["type"]

            # primary key
            if "id" in col_name:
                row[col_name] = i + 1

            # foreign key handling
            elif "status" in col_name.lower():
                row[col_name] = fk_store.get_random_id("user_status")

            elif "category" in col_name.lower():
                row[col_name] = fk_store.get_random_id("user_category")

            # string fields
            elif col_type == "string":
                if "email" in col_name:
                    row[col_name] = fake.email()
                elif "name" in col_name:
                    row[col_name] = fake.name()
                else:
                    row[col_name] = fake.word()

            # int fields
            elif col_type == "int":
                row[col_name] = random.randint(1, 100)

            # date fields
            elif col_type == "date":
                row[col_name] = fake.date()

            else:
                row[col_name] = None

        rows.append(row)

    fk_store.add("users", rows)
    return rows