import random

def generate_lookup(table_name, fk_store, num_rows=10):

    data = []

    for i in range(num_rows):
        row = {
            "id": i + 1,
            "name": f"{table_name}_{i}"
        }
        data.append(row)

    fk_store.add(table_name, data)
    return data