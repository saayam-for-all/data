import json
import re
import sqlite3
import csv
import os
from datetime import datetime, timedelta

SCHEMA_NAME = "virginia_dev_saayam_rdbms"
RealDictCursor = None



class DictLikeRow(dict):
    def __getitem__(self, key):
        if key == 0:
            return list(self.values())[0]
        return super().__getitem__(key)


class SQLiteCursorWrapper:
    def __init__(self, cursor):
        self._cursor = cursor
        
    def execute(self, query, params=None):
        clean_query = query.replace("%s", "?")
        
        # Intercept information_schema.columns queries
        if "information_schema.columns" in query:
            schema_name, table_name, column_name = params
            self._cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [row[1] for row in self._cursor.fetchall()]
            exists = 1 if column_name in columns else 0
            self._cursor.execute("SELECT ?", (exists,))
            return
            
        self._cursor.execute(clean_query, params or [])
        
    def fetchone(self):
        row = self._cursor.fetchone()
        return DictLikeRow(row) if row else None
        
    def fetchall(self):
        rows = self._cursor.fetchall()
        return [DictLikeRow(r) for r in rows]
        
    def close(self):
        self._cursor.close()


class SQLiteConnectionWrapper:
    def __init__(self, conn):
        self._conn = conn
        
    def cursor(self, cursor_factory=None):
        return SQLiteCursorWrapper(self._conn.cursor())
        
    def close(self):
        self._conn.close()
        
    def commit(self):
        self._conn.commit()
        
    def rollback(self):
        self._conn.rollback()


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
    base_dir = os.path.dirname(os.path.abspath(__file__))
    possible_paths = [
        base_dir,
        os.path.join(base_dir, '..', '..', 'database', 'mock_db'),
        os.path.join(base_dir, 'database', 'mock_db'),
        os.path.abspath(os.path.join(base_dir, '..', '..')),
    ]
    
    org_path = None
    state_path = None
    
    for path in possible_paths:
        p_org = os.path.join(path, 'organizations.csv')
        p_state = os.path.join(path, 'state.csv')
        if os.path.exists(p_org) and os.path.exists(p_state):
            org_path = p_org
            state_path = p_state
            break
            
    if not org_path:
        p_org = os.path.join(os.getcwd(), 'database', 'mock_db', 'organizations.csv')
        p_state = os.path.join(os.getcwd(), 'database', 'mock_db', 'state.csv')
        if os.path.exists(p_org) and os.path.exists(p_state):
            org_path = p_org
            state_path = p_state
            
    if not org_path:
        raise FileNotFoundError("Could not find mock files organizations.csv and state.csv in expected locations.")
        
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("ATTACH DATABASE ':memory:' AS virginia_dev_saayam_rdbms;")
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS virginia_dev_saayam_rdbms.state (
            state_id VARCHAR(50) PRIMARY KEY,
            country_id INT NOT NULL,
            state_name VARCHAR(100) NOT NULL,
            state_code VARCHAR(6)
        );
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS virginia_dev_saayam_rdbms.organizations (
            org_id VARCHAR(255) PRIMARY KEY,
            org_name VARCHAR(125) NOT NULL,
            street VARCHAR(255),
            city_name VARCHAR(100),
            state_id VARCHAR(50),
            zip_code VARCHAR(10),
            mission TEXT,
            web_url VARCHAR(255),
            phone VARCHAR(20),
            email VARCHAR(255),
            org_type VARCHAR(50),
            org_size VARCHAR(50),
            org_rating INTEGER,
            is_collaborator INT,
            created_at TEXT
        );
    """)
    
    # Load state.csv
    state_name_to_id = {}
    with open(state_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cursor.execute("""
                INSERT INTO virginia_dev_saayam_rdbms.state (state_id, country_id, state_name)
                VALUES (?, ?, ?)
            """, (row['state_id'], int(row['country_id']), row['state_name']))
            state_name_to_id[row['state_name']] = row['state_id']
            
    # Load organizations.csv
    now = datetime.now()
    with open(org_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            org_id = row['org_id']
            org_name = row['org_name']
            
            # Map org_type
            org_type = row.get('org_type')
            if org_type not in ('non_profit', 'for_profit'):
                org_type = "non_profit" if i % 3 != 0 else "for_profit"
                
            # Map size
            org_size = row.get('size')
            if org_size not in ('small', 'medium', 'large'):
                org_size = "small" if i % 3 == 1 else ("medium" if i % 3 == 2 else "large")
                
            # Map rating
            try:
                rating_val = int(row.get('rating', 0))
                org_rating = (rating_val % 5) + 1
            except (ValueError, TypeError):
                org_rating = 3
                
            # Map state
            state_code = row.get('state_code')
            state_id = state_name_to_id.get(state_code)
            if not state_id:
                state_id = str((i % 5) + 1)
                
            # Staggered fresh dates for created_at
            created_at = (now - timedelta(days=(i % 45))).isoformat()
            
            is_collaborator = 1 if i % 4 == 0 else 0
            
            cursor.execute("""
                INSERT INTO virginia_dev_saayam_rdbms.organizations (
                    org_id, org_name, street, city_name, state_id, zip_code, mission, 
                    web_url, phone, email, org_type, org_size, org_rating, is_collaborator, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                org_id, org_name, row.get('street'), row.get('city_name'), state_id, row.get('zip_code'),
                row.get('mission'), row.get('web_url'), row.get('phone'), row.get('email'),
                org_type, org_size, org_rating, is_collaborator, created_at
            ))
            
    conn.commit()
    return SQLiteConnectionWrapper(conn)



def column_exists(cursor, table_name, column_name, schema_name=SCHEMA_NAME):
    query = """
        SELECT EXISTS (
            SELECT 1 
            FROM information_schema.columns 
            WHERE table_schema = %s 
              AND table_name = %s 
              AND column_name = %s
        );
    """
    try:
        cursor.execute(query, (schema_name, table_name, column_name))
        row = cursor.fetchone()
        return row[0] if row else False
    except Exception:
        return False


def get_time_filter_sql(time_filter, start_date, end_date, is_sqlite):
    if is_sqlite:
        if time_filter == "7D":
            return "o.created_at >= datetime('now', '-7 days')", []
        elif time_filter == "30D":
            return "o.created_at >= datetime('now', '-30 days')", []
        elif time_filter == "1Y":
            return "o.created_at >= datetime('now', '-1 year')", []
        elif time_filter == "CUSTOM":
            if start_date and end_date:
                return "o.created_at BETWEEN ? AND ?", [start_date, end_date]
            elif start_date:
                return "o.created_at >= ?", [start_date]
            elif end_date:
                return "o.created_at <= ?", [end_date]
        return "1=1", []
    else:
        if time_filter == "7D":
            return "o.created_at >= CURRENT_TIMESTAMP - INTERVAL '7 days'", []
        elif time_filter == "30D":
            return "o.created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'", []
        elif time_filter == "1Y":
            return "o.created_at >= CURRENT_TIMESTAMP - INTERVAL '1 year'", []
        elif time_filter == "CUSTOM":
            if start_date and end_date:
                return "o.created_at BETWEEN %s AND %s", [start_date, end_date]
            elif start_date:
                return "o.created_at >= %s", [start_date]
            elif end_date:
                return "o.created_at <= %s", [end_date]
        return "1=1", []


def get_trend_select_sql(group_by, is_sqlite):
    if is_sqlite:
        if group_by == "daily":
            return "strftime('%Y-%m-%d', o.created_at)"
        elif group_by == "weekly":
            return "date(o.created_at, 'weekday 0', '-6 days')"
        elif group_by == "monthly":
            return "strftime('%Y-%m', o.created_at)"
        elif group_by == "yearly":
            return "strftime('%Y', o.created_at)"
        return "strftime('%Y-%m', o.created_at)"
    else:
        if group_by == "daily":
            return "TO_CHAR(o.created_at, 'YYYY-MM-DD')"
        elif group_by == "weekly":
            return "TO_CHAR(DATE_TRUNC('week', o.created_at), 'YYYY-MM-DD')"
        elif group_by == "monthly":
            return "TO_CHAR(DATE_TRUNC('month', o.created_at), 'YYYY-MM')"
        elif group_by == "yearly":
            return "TO_CHAR(DATE_TRUNC('year', o.created_at), 'YYYY')"
        return "TO_CHAR(DATE_TRUNC('month', o.created_at), 'YYYY-MM')"


def build_where_clause(filters, has_contributor_col, is_sqlite):
    placeholder = "?" if is_sqlite else "%s"
    where_parts = ["1=1"]
    params = []
    
    time_filter = filters.get("time_filter")
    start_date = filters.get("start_date")
    end_date = filters.get("end_date")
    
    time_sql, time_params = get_time_filter_sql(time_filter, start_date, end_date, is_sqlite)
    where_parts.append(time_sql)
    params.extend(time_params)
            
    if filters.get("org_type"):
        where_parts.append(f"o.org_type = {placeholder}")
        params.append(filters["org_type"])
        
    if filters.get("org_size"):
        where_parts.append(f"o.org_size = {placeholder}")
        params.append(filters["org_size"])
        
    if filters.get("state_id"):
        where_parts.append(f"o.state_id = {placeholder}")
        params.append(filters["state_id"])
        
    if filters.get("city_name"):
        where_parts.append(f"o.city_name = {placeholder}")
        params.append(filters["city_name"])
        
    if filters.get("org_rating") is not None:
        where_parts.append(f"o.org_rating = {placeholder}")
        params.append(int(filters["org_rating"]))
        
    if filters.get("is_collaborator") is not None:
        val = str(filters["is_collaborator"]).lower() in ("true", "1")
        val_to_append = 1 if is_sqlite and val else (0 if is_sqlite else val)
        where_parts.append(f"o.is_collaborator = {placeholder}")
        params.append(val_to_append)
        
    if filters.get("is_contributor") is not None:
        val = str(filters["is_contributor"]).lower() in ("true", "1")
        if has_contributor_col:
            val_to_append = 1 if is_sqlite and val else (0 if is_sqlite else val)
            where_parts.append(f"o.is_contributor = {placeholder}")
            params.append(val_to_append)
        else:
            if val:
                where_parts.append("(o.org_rating IS NOT NULL AND o.org_rating >= 4)")
            else:
                where_parts.append("(o.org_rating IS NULL OR o.org_rating < 4)")
                
    return " AND ".join(where_parts), params


def handle_overview(cursor, filters, has_contributor_col, is_sqlite):
    where_clause, params = build_where_clause(filters, has_contributor_col, is_sqlite)
    
    true_val = 1 if is_sqlite else "TRUE"
    false_val = 0 if is_sqlite else "FALSE"
    
    if has_contributor_col:
        contrib_true_expr = f"o.is_contributor = {true_val}"
        contrib_false_expr = f"o.is_contributor = {false_val} OR o.is_contributor IS NULL"
    else:
        contrib_true_expr = "o.org_rating IS NOT NULL AND o.org_rating >= 4"
        contrib_false_expr = "o.org_rating IS NULL OR o.org_rating < 4"
        
    summary_query = f"""
        SELECT 
            COUNT(*) AS total_organizations,
            SUM(CASE WHEN o.org_type = 'non_profit' THEN 1 ELSE 0 END) AS non_profit_organizations,
            SUM(CASE WHEN o.org_type = 'for_profit' THEN 1 ELSE 0 END) AS for_profit_organizations,
            SUM(CASE WHEN o.is_collaborator = {true_val} THEN 1 ELSE 0 END) AS collaborator_organizations,
            SUM(CASE WHEN o.is_collaborator = {false_val} OR o.is_collaborator IS NULL THEN 1 ELSE 0 END) AS non_collaborator_organizations,
            SUM(CASE WHEN {contrib_true_expr} THEN 1 ELSE 0 END) AS contributor_organizations,
            SUM(CASE WHEN {contrib_false_expr} THEN 1 ELSE 0 END) AS non_contributor_organizations
        FROM virginia_dev_saayam_rdbms.organizations o
        WHERE {where_clause}
    """
    cursor.execute(summary_query, params)
    sum_row = cursor.fetchone()
    summary = {
        "total_organizations": int(sum_row["total_organizations"]) if sum_row and sum_row["total_organizations"] else 0,
        "non_profit_organizations": int(sum_row["non_profit_organizations"]) if sum_row and sum_row["non_profit_organizations"] else 0,
        "for_profit_organizations": int(sum_row["for_profit_organizations"]) if sum_row and sum_row["for_profit_organizations"] else 0,
        "collaborator_organizations": int(sum_row["collaborator_organizations"]) if sum_row and sum_row["collaborator_organizations"] else 0,
        "non_collaborator_organizations": int(sum_row["non_collaborator_organizations"]) if sum_row and sum_row["non_collaborator_organizations"] else 0,
        "contributor_organizations": int(sum_row["contributor_organizations"]) if sum_row and sum_row["contributor_organizations"] else 0,
        "non_contributor_organizations": int(sum_row["non_contributor_organizations"]) if sum_row and sum_row["non_contributor_organizations"] else 0,
    }
    
    group_by = filters.get("group_by")
    if not group_by:
        time_filter = filters.get("time_filter", "30D")
        group_by = "monthly" if time_filter in ("1Y", "ALL") else "daily"
        
    trend_select = get_trend_select_sql(group_by, is_sqlite)
    trend_query = f"""
        SELECT {trend_select} AS period, COUNT(*) AS count
        FROM virginia_dev_saayam_rdbms.organizations o
        WHERE {where_clause}
        GROUP BY 1
        ORDER BY 1 ASC
    """
    cursor.execute(trend_query, params)
    trend_rows = cursor.fetchall()
    activity_trend = [{"period": r["period"], "count": int(r["count"])} for r in trend_rows]
    
    type_query = f"""
        SELECT o.org_type, COUNT(*) AS count
        FROM virginia_dev_saayam_rdbms.organizations o
        WHERE {where_clause}
        GROUP BY o.org_type
    """
    cursor.execute(type_query, params)
    type_rows = cursor.fetchall()
    orgs_by_type = [{"org_type": r["org_type"], "count": int(r["count"])} for r in type_rows if r["org_type"] is not None]
    
    size_query = f"""
        SELECT o.org_size, COUNT(*) AS count
        FROM virginia_dev_saayam_rdbms.organizations o
        WHERE {where_clause}
        GROUP BY o.org_size
    """
    cursor.execute(size_query, params)
    size_rows = cursor.fetchall()
    orgs_by_size = [{"org_size": r["org_size"], "count": int(r["count"])} for r in size_rows if r["org_size"] is not None]
    
    loc_query = f"""
        SELECT 
            COALESCE(s.state_name, o.state_id, 'Unknown') AS state_name,
            COALESCE(o.city_name, 'Unknown') AS city_name,
            COUNT(*) AS count
        FROM virginia_dev_saayam_rdbms.organizations o
        LEFT JOIN virginia_dev_saayam_rdbms.state s ON o.state_id = s.state_id
        WHERE {where_clause}
        GROUP BY 1, 2
        ORDER BY count DESC
    """
    cursor.execute(loc_query, params)
    loc_rows = cursor.fetchall()
    orgs_by_location = [{
        "state_name": r["state_name"],
        "city_name": r["city_name"],
        "count": int(r["count"])
    } for r in loc_rows]
    
    collab_query = f"""
        SELECT o.is_collaborator, COUNT(*) AS count
        FROM virginia_dev_saayam_rdbms.organizations o
        WHERE {where_clause}
        GROUP BY o.is_collaborator
    """
    cursor.execute(collab_query, params)
    collab_rows = cursor.fetchall()
    collaborator_dist = []
    for r in collab_rows:
        val = r["is_collaborator"]
        if is_sqlite and val is not None:
            val = bool(val)
        collaborator_dist.append({
            "is_collaborator": val,
            "count": int(r["count"])
        })
        
    contrib_dist = []
    if has_contributor_col:
        contrib_query = f"""
            SELECT o.is_contributor, COUNT(*) AS count
            FROM virginia_dev_saayam_rdbms.organizations o
            WHERE {where_clause}
            GROUP BY o.is_contributor
        """
        cursor.execute(contrib_query, params)
        contrib_rows = cursor.fetchall()
        for r in contrib_rows:
            val = r["is_contributor"]
            if is_sqlite and val is not None:
                val = bool(val)
            contrib_dist.append({
                "is_contributor": val,
                "count": int(r["count"])
            })
    else:
        contrib_query = f"""
            SELECT 
                CASE WHEN o.org_rating IS NOT NULL AND o.org_rating >= 4 THEN {true_val} ELSE {false_val} END AS is_contributor,
                COUNT(*) AS count
            FROM virginia_dev_saayam_rdbms.organizations o
            WHERE {where_clause}
            GROUP BY 1
        """
        cursor.execute(contrib_query, params)
        contrib_rows = cursor.fetchall()
        for r in contrib_rows:
            val = r["is_contributor"]
            if val is not None:
                val = bool(int(val)) if is_sqlite or isinstance(val, (int, str)) else bool(val)
            contrib_dist.append({
                "is_contributor": val,
                "count": int(r["count"])
            })
            
    return {
        "organization_overview": {
            "summary": summary,
            "organization_activity_trend": activity_trend,
            "organizations_by_type": orgs_by_type,
            "organizations_by_size": orgs_by_size,
            "organizations_by_location": orgs_by_location,
            "collaborator_distribution": collaborator_dist,
            "contributor_distribution": contrib_dist
        }
    }


def handle_performance(cursor, filters, has_contributor_col, is_sqlite):
    where_clause, params = build_where_clause(filters, has_contributor_col, is_sqlite)
    
    true_val = 1 if is_sqlite else "TRUE"
    false_val = 0 if is_sqlite else "FALSE"
    
    summary_query = f"""
        SELECT 
            AVG(o.org_rating) AS average_rating,
            SUM(CASE WHEN o.org_rating IS NOT NULL THEN 1 ELSE 0 END) AS rated_organizations,
            SUM(CASE WHEN o.org_rating IS NULL THEN 1 ELSE 0 END) AS unrated_organizations,
            SUM(CASE WHEN o.org_rating = 5 THEN 1 ELSE 0 END) AS five_star_organizations
        FROM virginia_dev_saayam_rdbms.organizations o
        WHERE {where_clause}
    """
    cursor.execute(summary_query, params)
    sum_row = cursor.fetchone()
    summary = {
        "average_rating": round(float(sum_row["average_rating"]), 2) if sum_row and sum_row["average_rating"] is not None else 0.0,
        "rated_organizations": int(sum_row["rated_organizations"]) if sum_row and sum_row["rated_organizations"] else 0,
        "unrated_organizations": int(sum_row["unrated_organizations"]) if sum_row and sum_row["unrated_organizations"] else 0,
        "five_star_organizations": int(sum_row["five_star_organizations"]) if sum_row and sum_row["five_star_organizations"] else 0,
    }
    
    dist_query = f"""
        SELECT o.org_rating, COUNT(*) AS count
        FROM virginia_dev_saayam_rdbms.organizations o
        WHERE {where_clause} AND o.org_rating IS NOT NULL
        GROUP BY o.org_rating
        ORDER BY o.org_rating ASC
    """
    cursor.execute(dist_query, params)
    dist_rows = cursor.fetchall()
    rating_distribution = [{"org_rating": int(r["org_rating"]), "count": int(r["count"])} for r in dist_rows]
    
    top_rated_query = f"""
        SELECT o.org_id, o.org_name, o.org_rating, o.org_type, o.org_size
        FROM virginia_dev_saayam_rdbms.organizations o
        WHERE {where_clause} AND o.org_rating IS NOT NULL
        ORDER BY o.org_rating DESC, o.org_name ASC
        LIMIT 10
    """
    cursor.execute(top_rated_query, params)
    top_rows = cursor.fetchall()
    top_rated_organizations = [{
        "org_id": r["org_id"],
        "org_name": r["org_name"],
        "org_rating": int(r["org_rating"]),
        "org_type": r["org_type"],
        "org_size": r["org_size"]
    } for r in top_rows]
    
    collab_top_query = f"""
        SELECT o.org_id, o.org_name, o.org_rating, o.org_type, o.org_size
        FROM virginia_dev_saayam_rdbms.organizations o
        WHERE {where_clause} AND o.is_collaborator = {true_val} AND o.org_rating IS NOT NULL
        ORDER BY o.org_rating DESC, o.org_name ASC
        LIMIT 10
    """
    cursor.execute(collab_top_query, params)
    collab_rows = cursor.fetchall()
    top_collaborator_organizations = [{
        "org_id": r["org_id"],
        "org_name": r["org_name"],
        "org_rating": int(r["org_rating"]),
        "org_type": r["org_type"],
        "org_size": r["org_size"]
    } for r in collab_rows]
    
    if has_contributor_col:
        contrib_top_query = f"""
            SELECT o.org_id, o.org_name, o.org_rating, o.org_type, o.org_size
            FROM virginia_dev_saayam_rdbms.organizations o
            WHERE {where_clause} AND o.is_contributor = {true_val} AND o.org_rating IS NOT NULL
            ORDER BY o.org_rating DESC, o.org_name ASC
            LIMIT 10
        """
    else:
        contrib_top_query = f"""
            SELECT o.org_id, o.org_name, o.org_rating, o.org_type, o.org_size
            FROM virginia_dev_saayam_rdbms.organizations o
            WHERE {where_clause} AND o.org_rating IS NOT NULL AND o.org_rating >= 4
            ORDER BY o.org_rating DESC, o.org_name ASC
            LIMIT 10
        """
    cursor.execute(contrib_top_query, params)
    contrib_rows = cursor.fetchall()
    top_contributor_organizations = [{
        "org_id": r["org_id"],
        "org_name": r["org_name"],
        "org_rating": int(r["org_rating"]),
        "org_type": r["org_type"],
        "org_size": r["org_size"]
    } for r in contrib_rows]
    
    type_query = f"""
        SELECT o.org_type, AVG(o.org_rating) AS average_rating
        FROM virginia_dev_saayam_rdbms.organizations o
        WHERE {where_clause} AND o.org_rating IS NOT NULL
        GROUP BY o.org_type
    """
    cursor.execute(type_query, params)
    type_rows = cursor.fetchall()
    ratings_by_organization_type = [{
        "org_type": r["org_type"],
        "average_rating": round(float(r["average_rating"]), 2) if r["average_rating"] is not None else 0.0
    } for r in type_rows if r["org_type"] is not None]
    
    size_query = f"""
        SELECT o.org_size, AVG(o.org_rating) AS average_rating
        FROM virginia_dev_saayam_rdbms.organizations o
        WHERE {where_clause} AND o.org_rating IS NOT NULL
        GROUP BY o.org_size
    """
    cursor.execute(size_query, params)
    size_rows = cursor.fetchall()
    ratings_by_organization_size = [{
        "org_size": r["org_size"],
        "average_rating": round(float(r["average_rating"]), 2) if r["average_rating"] is not None else 0.0
    } for r in size_rows if r["org_size"] is not None]
    
    return {
        "organization_performance": {
            "summary": summary,
            "rating_distribution": rating_distribution,
            "top_rated_organizations": top_rated_organizations,
            "top_collaborator_organizations": top_collaborator_organizations,
            "top_contributor_organizations": top_contributor_organizations,
            "ratings_by_organization_type": ratings_by_organization_type,
            "ratings_by_organization_size": ratings_by_organization_size
        }
    }


def lambda_handler(event, context):
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

    dashboard_type = payload.get("dashboard_type", "overview")
    
    filters = {
        "time_filter": payload.get("time_filter", "30D"),
        "start_date": payload.get("start_date"),
        "end_date": payload.get("end_date"),
        "org_type": payload.get("org_type"),
        "org_size": payload.get("org_size"),
        "state_id": payload.get("state_id"),
        "city_name": payload.get("city_name"),
        "org_rating": payload.get("org_rating"),
        "is_collaborator": payload.get("is_collaborator"),
        "is_contributor": payload.get("is_contributor"),
        "group_by": payload.get("group_by")
    }

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        has_contributor_col = column_exists(cursor, "organizations", "is_contributor")
        
        if dashboard_type == "overview":
            result_body = handle_overview(cursor, filters, has_contributor_col, is_sqlite=True)
        elif dashboard_type == "performance":
            result_body = handle_performance(cursor, filters, has_contributor_col, is_sqlite=True)
        else:
            return build_response(400, {"error": "Invalid dashboard_type. Expected 'overview' or 'performance'"})
            
        return build_response(200, result_body)
        
    except Exception as e:
        print(f"Error handling request: {e}")
        return build_response(500, {"error": "Internal Server Error", "message": str(e)})
        
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    print("Executing offline verification of lambda_handler using mock CSV files...")
    
    # 1. Test Overview Dashboard
    print("\n--- Testing: Overview Dashboard (30D) ---")
    event_overview = {"dashboard_type": "overview", "time_filter": "30D"}
    res_overview = lambda_handler(event_overview, None)
    body_overview = json.loads(res_overview["body"])
    print("Status Code:", res_overview["statusCode"])
    print(json.dumps(body_overview, indent=2))
    assert res_overview["statusCode"] == 200
    assert "organization_overview" in body_overview
    assert body_overview["organization_overview"]["summary"]["total_organizations"] > 0
    
    # 2. Test Performance Dashboard
    print("\n--- Testing: Performance Dashboard (30D) ---")
    event_perf = {"dashboard_type": "performance", "time_filter": "30D"}
    res_perf = lambda_handler(event_perf, None)
    body_perf = json.loads(res_perf["body"])
    print("Status Code:", res_perf["statusCode"])
    print(json.dumps(body_perf, indent=2))
    assert res_perf["statusCode"] == 200
    assert "organization_performance" in body_perf
    assert body_perf["organization_performance"]["summary"]["average_rating"] > 0
    
    print("\nLocal verification completed successfully!")
