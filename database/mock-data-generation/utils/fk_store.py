import random

class ForeignKeyStore:
    def __init__(self):
        self.store = {}

    def add(self, table_name, data):
        self.store[table_name] = data

    def get_random_id(self, table_name, key="id"):
        if table_name not in self.store:
            return None

        return random.choice(self.store[table_name]).get(key)