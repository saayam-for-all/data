import json

with open("db_info.json", "r") as f:
    schema = json.load(f)

tables = schema.get("tables", {})

for table_name, table_info in tables.items():
    print("\n======================")
    print("TABLE:", table_name)
    print("======================")

    columns = table_info.get("columns", [])

    # Handle list format safely
    if isinstance(columns, list):
        for col in columns:
            print(f"{col.get('name')} -> {col.get('type')}")
    else:
        print(columns)