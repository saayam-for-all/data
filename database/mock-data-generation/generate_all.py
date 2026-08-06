import json
import pandas as pd

from utils.fk_store import ForeignKeyStore
from utils.schema_analyzer import analyze_schema
from generators.generic_generator import generate_table

# load schema
with open("db_info.json", "r") as f:
    schema = json.load(f)

fk_store = ForeignKeyStore()

# analyze dependencies
dependencies = analyze_schema(schema)

tables = schema["tables"]

generated = {}

# STEP 1: generate all tables (simple order first)
for table_name, table_schema in tables.items():

    print(f"Generating {table_name}...")

    data = generate_table(
        table_name,
        table_schema,
        fk_store,
        num_rows=20
    )

    generated[table_name] = data

# STEP 2: save all CSVs
for table_name, rows in generated.items():
    df = pd.DataFrame(rows)
    df.to_csv(f"output/{table_name}.csv", index=False)

print("ALL TABLES GENERATED SUCCESSFULLY!")