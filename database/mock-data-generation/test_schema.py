import json

with open("db_info.json", "r") as f:
    schema = json.load(f)

print("Tables in schema:\n")

for table in schema["tables"]:
    print(table)