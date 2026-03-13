import psycopg2
from dotenv import load_dotenv
import json
import os

load_dotenv(r'C:\Users\saqui\Learning\SayamForAll\Data Engineering\data_repo\data\data-engineering\.env')

db_params = {
    "host": os.getenv('host'),
    "database": os.getenv('dbname'),
    "user": os.getenv('user'),
    "password": os.getenv('password'),
    "port": os.getenv('port') 
}

conn = psycopg2.connect(**db_params)

cur = conn.cursor()

cur.execute("""
    SELECT table_name 
    FROM information_schema.tables 
    WHERE table_schema = 'virginia_dev_saayam_rdbms'
""")

rows = cur.fetchall()

print(rows)


