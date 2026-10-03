import json
import os
import math
import boto3 
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

SCHEMA_NAME = "virginia_dev_saayam_rdbms"

def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body, default=str)
    }

def get_db_connection():
    # If running locally, emulate the connection via SQLite
    if os.environ.get("LOCAL_DEV") == "true":
        return get_local_db_connection()

    ssm = boto3.client("ssm", region_name="us-east-1")
    response = ssm.get_parameter(
        Name="/dev/saayam/db/Virginia/Analytics/user",
        WithDecryption=True
    )
    creds = json.loads(response["Parameter"]["Value"])
    db_name = creds["DATABASE NAME"]
    return psycopg2.connect(
        host=creds["HOST"],
        database=db_name,
        user=creds["USERNAME"],
        password=creds["PASSWORD"],
        port=creds["PORT"],
        sslmode="require"
    )

def lambda_handler(event, context):
    conn = None
    cursor = None
    
    # Payload parsing and type safety
    payload = event
    if isinstance(event, dict) and "body" in event:
        body = event["body"]
        if isinstance(body, str):
            try:
                payload = json.loads(body)
            except Exception:
                pass
        elif isinstance(body, dict):
            payload = body

    try:
        page = int(payload.get("page", 1)) if payload else 1
        page_size = int(payload.get("page_size", 5)) if payload else 5
    except (ValueError, TypeError):
        page = 1
        page_size = 5

    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 5

    try:
        conn = get_db_connection()
        if os.environ.get("LOCAL_DEV") == "true":
            cursor = conn.cursor()
        else:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

        # 1. Total records count
        count_query = f"""
            SELECT COUNT(*) 
            FROM {SCHEMA_NAME}.volunteer_applications va
            INNER JOIN {SCHEMA_NAME}.users u ON va.user_id = u.user_id
            WHERE va.application_status IN ('SUBMITTED', 'UNDER_REVIEW');
        """
        cursor.execute(count_query)
        count_row = cursor.fetchone()
        
        # Handle dict-like row vs tuple depending on cursor factory
        if isinstance(count_row, dict):
            total_records = count_row.get("count", 0) or list(count_row.values())[0]
        elif hasattr(count_row, "keys"):
            total_records = count_row[0]
        else:
            total_records = count_row[0] if count_row else 0

        # Math ceiling calculation for total pages
        total_pages = math.ceil(total_records / page_size) if total_records > 0 else 0

        # Limit and Offset calculation
        limit = page_size
        offset = (page - 1) * page_size

        # 2. Paginated rows query
        data_query = f"""
            SELECT va.user_id, va.last_updated_at
            FROM {SCHEMA_NAME}.volunteer_applications va
            INNER JOIN {SCHEMA_NAME}.users u ON va.user_id = u.user_id
            WHERE va.application_status IN ('SUBMITTED', 'UNDER_REVIEW')
            ORDER BY va.last_updated_at DESC
            LIMIT %s OFFSET %s;
        """
        
        # For SQLite local development connection
        if os.environ.get("LOCAL_DEV") == "true":
            # SQLite does not support %s formatting natively; wrapper handles it
            cursor.execute(data_query, (limit, offset))
        else:
            cursor.execute(data_query, (limit, offset))
            
        rows = cursor.fetchall()
        
        data = []
        for row in rows:
            user_id = row['user_id']
            last_updated_at = row['last_updated_at']
            
            # Format datetime safely to ISO-8601
            if isinstance(last_updated_at, str):
                try:
                    # Try to parse string to datetime if not done by driver
                    dt_obj = datetime.strptime(last_updated_at.split(".")[0], "%Y-%m-%d %H:%M:%S")
                    updated_time = dt_obj.strftime("%Y-%m-%dT%H:%M:%SZ")
                except ValueError:
                    try:
                        dt_obj = datetime.strptime(last_updated_at, "%Y-%m-%d %H:%M")
                        updated_time = dt_obj.strftime("%Y-%m-%dT%H:%M:%SZ")
                    except ValueError:
                        updated_time = last_updated_at
            elif isinstance(last_updated_at, datetime):
                updated_time = last_updated_at.strftime("%Y-%m-%dT%H:%M:%SZ")
            else:
                updated_time = str(last_updated_at)
                
            data.append({
                "user_id": user_id,
                "updated_time": updated_time,
                "volunteer_review": "Review"
            })

        response_body = {
            "data": data,
            "pagination": {
                "current_page": page,
                "page_size": page_size,
                "total_records": total_records,
                "total_pages": total_pages
            }
        }
        return build_response(200, response_body)

    except Exception as e:
        print(f"Error in steward_volunteer_review_api: {e}")
        error_body = {
            "data": [],
            "pagination": {
                "current_page": page,
                "page_size": page_size,
                "total_records": 0,
                "total_pages": 0
            },
            "error": "Internal Server Error"
        }
        return build_response(500, error_body)

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# ----------------- LOCAL DEV SQLITE WRAPPERS & SEED -----------------

import sqlite3
import csv

class DictLikeRow(dict):
    def __getitem__(self, key):
        if key == 0 or key == 'count':
            return list(self.values())[0]
        return super().__getitem__(key)

class SQLiteCursorWrapper:
    def __init__(self, cursor):
        self._cursor = cursor
        
    def execute(self, query, params=None):
        clean_query = query.replace("%s", "?")
        self._cursor.execute(clean_query, params or [])
        
    def fetchone(self):
        row = self._cursor.fetchone()
        if row:
            # Map column names to values
            colnames = [col[0] for col in self._cursor.description]
            return DictLikeRow(dict(zip(colnames, row)))
        return None
        
    def fetchall(self):
        rows = self._cursor.fetchall()
        colnames = [col[0] for col in self._cursor.description]
        return [DictLikeRow(dict(zip(colnames, r))) for r in rows]
        
    def close(self):
        self._cursor.close()

class SQLiteConnectionWrapper:
    def __init__(self, conn):
        self._conn = conn
        
    def cursor(self):
        return SQLiteCursorWrapper(self._conn.cursor())
        
    def close(self):
        self._conn.close()

def get_local_db_connection():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    possible_paths = [
        os.path.abspath(os.path.join(base_dir, '..', 'sql')),
        os.path.abspath(os.path.join(base_dir, 'database', 'mock_db')),
        os.path.abspath(os.path.join(base_dir, '..', '..', 'database', 'mock_db')),
        os.path.abspath(os.path.join(base_dir, '..', '..', 'data-analytics', 'sql')),
    ]
    
    users_path = None
    applications_path = None
    
    for path in possible_paths:
        p_users = os.path.join(path, 'users.csv')
        p_apps = os.path.join(path, 'volunteer_applications.csv')
        if os.path.exists(p_users) and os.path.exists(p_apps):
            users_path = p_users
            applications_path = p_apps
            break

    if not users_path:
        raise FileNotFoundError("Could not locate users.csv and volunteer_applications.csv in fallback directories.")

    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    
    # Emulate schema via attached memory DB
    cursor.execute("ATTACH DATABASE ':memory:' AS virginia_dev_saayam_rdbms;")
    
    cursor.execute("""
        CREATE TABLE virginia_dev_saayam_rdbms.users (
            user_id VARCHAR(255) PRIMARY KEY,
            full_name VARCHAR(255)
        );
    """)
    
    cursor.execute("""
        CREATE TABLE virginia_dev_saayam_rdbms.volunteer_applications (
            user_id VARCHAR(255) PRIMARY KEY,
            application_status VARCHAR(50),
            last_updated_at TIMESTAMP
        );
    """)
    
    # Load users.csv
    with open(users_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cursor.execute("""
                INSERT INTO virginia_dev_saayam_rdbms.users (user_id, full_name)
                VALUES (?, ?)
            """, (row['user_id'], row.get('full_name', '')))
            
    # Load volunteer_applications.csv
    with open(applications_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cursor.execute("""
                INSERT INTO virginia_dev_saayam_rdbms.volunteer_applications (user_id, application_status, last_updated_at)
                VALUES (?, ?, ?)
            """, (row['user_id'], row['application_status'], row['last_updated_at']))
            
    conn.commit()
    return SQLiteConnectionWrapper(conn)

if __name__ == "__main__":
    os.environ["LOCAL_DEV"] = "true"
    
    print("--- Test Case 1: Page 1, Size 2 ---")
    event = {"body": json.dumps({"page": 1, "page_size": 2})}
    res = lambda_handler(event, None)
    print(json.dumps(res, indent=2))
    
    print("\n--- Test Case 2: Page 2, Size 2 ---")
    event = {"body": json.dumps({"page": 2, "page_size": 2})}
    res = lambda_handler(event, None)
    print(json.dumps(res, indent=2))
    
    print("\n--- Test Case 3: Empty Results (Invalid Status) ---")
    # To simulate empty result count, we execute with page=999
    event = {"body": json.dumps({"page": 999, "page_size": 5})}
    res = lambda_handler(event, None)
    print(json.dumps(res, indent=2))
