import json
import re

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None
    RealDictCursor = None

try:
    from aws_lambda_powertools.utilities import parameters
except ImportError:
    class DummyParameters:
        @staticmethod
        def get_parameter(name, decrypt=True, max_age=None):
            raise NotImplementedError("aws_lambda_powertools parameters utility not available")
    parameters = DummyParameters

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
    creds = json.loads(parameters.get_parameter(
        "/dev/saayam/db/Virginia/Analytics/user",
        decrypt=True,
        max_age=3600
    ))
    db_name = creds["DATABASE NAME"]
    return psycopg2.connect(
        host=creds["HOST"],
        database=db_name,
        user=creds["USERNAME"],
        password=creds["PASSWORD"],
        port=creds["PORT"],
        sslmode="require"
    )


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
            result_body = handle_overview(cursor, filters, has_contributor_col, is_sqlite=False)
        elif dashboard_type == "performance":
            result_body = handle_performance(cursor, filters, has_contributor_col, is_sqlite=False)
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
    import unittest.mock as mock
    import sqlite3
    
    print("Setting up local SQLite mock database for offline verification...")
    
    # 1. Initialize SQLite Database
    local_conn = sqlite3.connect(":memory:")
    local_conn.row_factory = sqlite3.Row
    local_cursor = local_conn.cursor()
    
    # 2. Attach Mock Schema Database
    local_cursor.execute("ATTACH DATABASE ':memory:' AS virginia_dev_saayam_rdbms;")
    local_cursor.execute("""
        CREATE TABLE IF NOT EXISTS virginia_dev_saayam_rdbms.state (
            state_id VARCHAR(50) PRIMARY KEY,
            country_id INT NOT NULL,
            state_name VARCHAR(100) NOT NULL,
            state_code VARCHAR(6)
        );
    """)
    local_cursor.execute("""
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
    
    # 3. Populate state table
    local_cursor.execute("INSERT INTO virginia_dev_saayam_rdbms.state VALUES ('VA-001', 1, 'Virginia', 'VA');")
    local_cursor.execute("INSERT INTO virginia_dev_saayam_rdbms.state VALUES ('MD-002', 1, 'Maryland', 'MD');")
    
    # 4. Populate organizations table (30 mock organizations)
    # To test created_at time filters, some are created today, some 15 days ago, some 45 days ago.
    # Ratings range from 1 to 5, and some Nulls.
    from datetime import datetime, timedelta
    now = datetime.now()
    
    for i in range(1, 31):
        org_id = f"ORG-{i:03d}"
        name = f"Organization {i}"
        org_type = "non_profit" if i % 3 != 0 else "for_profit"
        city = "Richmond" if i % 2 == 0 else "Alexandria"
        state = "VA-001" if i % 2 == 0 else "MD-002"
        size = "small" if i % 3 == 1 else ("medium" if i % 3 == 2 else "large")
        rating = (i % 5) + 1 if i % 6 != 0 else None
        collab = 1 if i % 4 == 0 else 0
        
        # Staggered registration times
        if i <= 10:
            reg_date = (now - timedelta(days=i)).isoformat()
        elif i <= 20:
            reg_date = (now - timedelta(days=i + 5)).isoformat()
        else:
            reg_date = (now - timedelta(days=i + 20)).isoformat()
            
        local_cursor.execute("""
            INSERT INTO virginia_dev_saayam_rdbms.organizations (
                org_id, org_name, street, city_name, state_id, zip_code, mission, 
                web_url, phone, email, org_type, org_size, org_rating, is_collaborator, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            org_id, name, f"{100+i} Main St", city, state, f"2322{i%10}",
            "Helping people" if i % 2 == 0 else "Education support",
            f"http://org{i}.org", f"555-010{i%10}", f"info@org{i}.org",
            org_type, size, rating, collab, reg_date
        ))
    local_conn.commit()
    
    # 5. Define local Mock connection mapping
    class LocalMockCursor:
        def __init__(self, sqlite_cursor):
            self.cursor = sqlite_cursor
            
        def execute(self, query, params=None):
            # Convert %s placeholders to ? for SQLite compatibility
            clean_query = query.replace("%s", "?")
            self.cursor.execute(clean_query, params or [])
            
        def fetchone(self):
            row = self.cursor.fetchone()
            return dict(row) if row else None
            
        def fetchall(self):
            rows = self.cursor.fetchall()
            return [dict(r) for r in rows]
            
        def close(self):
            pass

    class LocalMockConnection:
        def __init__(self, sqlite_conn):
            self.conn = sqlite_conn
            
        def cursor(self, cursor_factory=None):
            return LocalMockCursor(self.conn.cursor())
            
        def close(self):
            pass

    # Wrapper lambda_handler that uses SQLite connection
    def local_lambda_handler(event, context):
        dashboard_type = event.get("dashboard_type", "overview")
        filters = {
            "time_filter": event.get("time_filter", "30D"),
            "start_date": event.get("start_date"),
            "end_date": event.get("end_date"),
            "org_type": event.get("org_type"),
            "org_size": event.get("org_size"),
            "state_id": event.get("state_id"),
            "city_name": event.get("city_name"),
            "org_rating": event.get("org_rating"),
            "is_collaborator": event.get("is_collaborator"),
            "is_contributor": event.get("is_contributor"),
            "group_by": event.get("group_by")
        }
        
        mock_cursor = LocalMockCursor(local_cursor)
        
        # organizations table doesn't have is_contributor locally yet, so passes False
        has_contributor_col = False 
        
        if dashboard_type == "overview":
            result_body = handle_overview(mock_cursor, filters, has_contributor_col, is_sqlite=True)
        elif dashboard_type == "performance":
            result_body = handle_performance(mock_cursor, filters, has_contributor_col, is_sqlite=True)
        else:
            return build_response(400, {"error": "Invalid dashboard_type"})
            
        return build_response(200, result_body)

    # 6. Verify Local Handler
    print("\n--- Testing: Overview Dashboard (30D) ---")
    res = local_lambda_handler({"dashboard_type": "overview", "time_filter": "30D"}, None)
    body = json.loads(res["body"])
    print(json.dumps(body, indent=2))
    assert res["statusCode"] == 200
    assert "organization_overview" in body
    assert body["organization_overview"]["summary"]["total_organizations"] > 0
    
    print("\n--- Testing: Performance Dashboard (30D) ---")
    res = local_lambda_handler({"dashboard_type": "performance", "time_filter": "30D"}, None)
    body = json.loads(res["body"])
    print(json.dumps(body, indent=2))
    assert res["statusCode"] == 200
    assert "organization_performance" in body
    assert body["organization_performance"]["summary"]["average_rating"] > 0
    
    print("\nLocal verification completed successfully!")
