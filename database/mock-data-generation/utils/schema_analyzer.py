def analyze_schema(schema):
    tables = schema["tables"]

    dependencies = {}

    for table_name, table_info in tables.items():
        dependencies[table_name] = []

        columns = table_info.get("columns", [])

        for col in columns:
            col_name = col.get("name", "").lower()

            # detect foreign keys
            if "id" in col_name and col_name != "id":
                dependencies[table_name].append(col_name.replace("_id", ""))

    return dependencies