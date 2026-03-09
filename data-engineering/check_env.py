import os
from dotenv import load_dotenv

# Load the .env file
load_dotenv()

# Get the variables
host = os.getenv("HOST")
db_name = os.getenv("DATABASE_NAME") # Matching your helpers.py logic

print("--- Environment Check ---")
if host:
    print(f"✅ SUCCESS: Found HOST = {host}")
else:
    print("❌ ERROR: HOST not found in .env")

if db_name:
    print(f"✅ SUCCESS: Found DATABASE_NAME = {db_name}")
else:
    print("❌ ERROR: DATABASE NAME not found in .env")