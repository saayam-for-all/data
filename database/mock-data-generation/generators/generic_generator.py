import random
from faker import Faker

fake = Faker()

def generate_table(table_name, table_schema, fk_store, num_rows=20):

    rows = []

    for i in range(num_rows):
        row = {}

        for col in table_schema["columns"]:
            col_name = col["name"]
            col_type = col["type"]

            # primary key
            if col_name == "id":
                row[col_name] = i + 1

            # foreign key
            elif col_name.endswith("_id"):
                ref_table = col_name.replace("_id", "")
                row[col_name] = fk_store.get_random_id(ref_table)

            # string
            elif col_type == "string":
                if "email" in col_name:
                    row[col_name] = fake.email()
                elif "name" in col_name:
                    row[col_name] = fake.name()
                else:
                    row[col_name] = fake.word()

            # int
            elif col_type == "int":
                row[col_name] = random.randint(1, 100)

            # date
            elif col_type == "date":
                row[col_name] = fake.date()

            else:
                row[col_name] = None

        rows.append(row)

    fk_store.add(table_name, rows)
    return rows