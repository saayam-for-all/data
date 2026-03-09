from dotenv import load_dotenv
load_dotenv()

import os
import pandas as pd
import pg8000


_db_conn = None


def get_db_connection():
    """Lazy DB connection — only connects when first called."""
    global _db_conn
    if _db_conn is None:
        _db_conn = pg8000.connect(
            host=os.getenv('HOST'),
            user=os.getenv('USERNAME'),
            password=os.getenv('PASSWORD'),
            database=os.getenv('DATABASE_NAME'),
            port=int(os.getenv('PORT', 5432)),
            ssl_context=True
        )
    return _db_conn


def get_orgs_from_db(location: str, category: str) -> pd.DataFrame:
    """Fetches organizations from Aurora PostgreSQL."""
    db_name = os.getenv('DATABASE_NAME')
    try:
        query = f"""
            SELECT org_name, city_name, phone, email, web_url, mission, source, org_type, is_collaborator
            FROM {db_name}.organizations
            WHERE mission = '{category}' AND city_name = '{location}'
        """
        df = pd.read_sql(query, get_db_connection())
        df["db_or_ai"] = "db"
        return df
    except Exception as e:
        if "is_collaborator" in str(e):
            # Fallback if column doesn't exist in DB yet
            fallback_query = f"""
                SELECT org_name, city_name, phone, email, web_url, mission, source, org_type
                FROM {db_name}.organizations
                WHERE mission = '{category}' AND city_name = '{location}'
            """
            df = pd.read_sql(fallback_query, get_db_connection())
            df["is_collaborator"] = False
            df["db_or_ai"] = "db"
            return df
        raise Exception(f'Database error: {str(e)}')