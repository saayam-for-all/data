from fastapi import FastAPI, Depends, HTTPException, Security, Query
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
import psycopg2
import os
import jwt
from typing import List, Optional
from dotenv import load_dotenv

from src.utils.time_filters import resolve_date_range, date_range_clause, trend_bucket

# Load environment variables
load_dotenv()

app = FastAPI()

# Secret key for JWT
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key")

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Hardcoded User DB
USER_DB = {
    "admin_user": {"username": "admin_user", "role": "admin"},
    "volunteer_user": {"username": "volunteer_user", "role": "volunteer"},
    "requestor_user": {"username": "requestor_user", "role": "requestor"},
}

# DB connection
def get_db_connection():
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT"),
            database=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD")
        )
        return conn
    except Exception as e:
        print(f"❌ DB connection failed: {e}")
        return None

# Schema for the organizations table (env-configurable, no Parameter Store paths)
ORG_SCHEMA = os.getenv("ORG_ANALYTICS_SCHEMA", "virginia_dev_saayam_rdbms")
ORG_TABLE = f"{ORG_SCHEMA}.organizations"

# NOTE: org_size, rating, and registered_at are not confirmed against the live
# `organizations` table — no DDL/migration for it exists in this repo. They're
# assumed here based on the dashboard requirements in issue #228. Verify these
# column names against the real table (e.g. via information_schema.columns)
# and adjust below before this ships.
ORG_SIZE_COLUMN = "org_size"
ORG_RATING_COLUMN = "rating"
ORG_REGISTERED_AT_COLUMN = "registered_at"

# JWT token generation
def create_jwt_token(data: dict):
    return jwt.encode(data, SECRET_KEY, algorithm="HS256")

# Get current user from token
def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# Updated RBAC checker: allow multiple roles
def check_user_role(*allowed_roles: str):
    def role_checker(user: dict = Depends(get_current_user)):
        if user["role"] not in allowed_roles:
            raise HTTPException(status_code=403, detail="Not authorized")
        return user
    return role_checker

# ========================= Models =========================
class UserCategoryCount(BaseModel):
    user_category: str
    total_users: int

class VolunteerCount(BaseModel):
    total_volunteers: int

class VolunteerStatusSummary(BaseModel):
    status: str
    total_volunteers: int

class GeographicDistribution(BaseModel):
    country: str
    state: str
    total_requests: int

class SkillSummary(BaseModel):
    skill: str
    total_volunteers: int

class CountryUsers(BaseModel):
    country: str
    total_users: int

class EmergencyContactCoverage(BaseModel):
    users_with_emergency_contacts: int

# ---- Organization dashboards ----
class OrganizationSummary(BaseModel):
    total_organizations: int
    total_collaborators: int
    total_contributors: int

class OrganizationTypeCount(BaseModel):
    org_type: Optional[str]
    total_organizations: int

class OrganizationSizeCount(BaseModel):
    org_size: Optional[str]
    total_organizations: int

class OrganizationGeoDistribution(BaseModel):
    city: Optional[str]
    total_organizations: int

class OrganizationRegistrationTrend(BaseModel):
    period: str
    total_organizations: int

class OrganizationPerformanceSummary(BaseModel):
    average_rating: Optional[float]
    total_rated_organizations: int

class TopRatedOrganization(BaseModel):
    org_name: str
    org_type: Optional[str]
    rating: float

class OrganizationRatingByCategory(BaseModel):
    category: Optional[str]
    average_rating: Optional[float]
    total_organizations: int

# ========================= Authentication Endpoint =========================
@app.post("/token")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = USER_DB.get(form_data.username)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token_data = {"sub": user["username"], "role": user["role"]}
    access_token = create_jwt_token(token_data)
    return {"access_token": access_token, "token_type": "bearer"}

# ========================= Analytics Endpoints (Protected) =========================

# Admin only
@app.get("/analytics/total_requestors", response_model=List[UserCategoryCount], dependencies=[Depends(check_user_role("admin"))])
def get_total_users():
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="DB connection failed")
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT uc.user_category, COUNT(u.user_id) AS total_users
            FROM user_category uc
            LEFT JOIN users u ON u.user_category_id = uc.user_category_id
            GROUP BY uc.user_category
            ORDER BY total_users DESC;
        """)
        result = cur.fetchall()
        return [{"user_category": row[0], "total_users": row[1]} for row in result]
    finally:
        cur.close()
        conn.close()

# Admin and Volunteer
@app.get("/analytics/volunteer_count", response_model=VolunteerCount, dependencies=[Depends(check_user_role("admin", "volunteer"))])
def get_volunteer_count():
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="DB connection failed")
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(DISTINCT user_id) AS total_volunteers
            FROM volunteer_details;
        """)
        result = cur.fetchone()
        return {"total_volunteers": result[0]}
    finally:
        cur.close()
        conn.close()

# Admin and Volunteer
@app.get("/analytics/volunteer_status", response_model=List[VolunteerStatusSummary], dependencies=[Depends(check_user_role("admin", "volunteer"))])
def get_volunteer_status():
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="DB connection failed")
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COALESCE(us.user_status, 'Unknown') AS status, COUNT(DISTINCT vd.user_id) AS total_volunteers
            FROM volunteer_details vd
            LEFT JOIN users u ON vd.user_id = u.user_id
            LEFT JOIN user_status us ON u.user_status_id = us.user_status_id
            GROUP BY us.user_status;
        """)
        result = cur.fetchall()
        return [{"status": row[0], "total_volunteers": row[1]} for row in result]
    finally:
        cur.close()
        conn.close()

# Admin only
@app.get("/analytics/geographic_distribution", response_model=List[GeographicDistribution], dependencies=[Depends(check_user_role("admin"))])
def get_geo():
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="DB connection failed")
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT c.country_name, s.state_name, COUNT(u.user_id)
            FROM users u
            JOIN country c ON u.country_id = c.country_id
            JOIN state s ON u.state_id = s.state_id
            GROUP BY c.country_name, s.state_name
            ORDER BY COUNT(u.user_id) DESC;
        """)
        result = cur.fetchall()
        return [{"country": row[0], "state": row[1], "total_requests": row[2]} for row in result]
    finally:
        cur.close()
        conn.close()

# Admin and Volunteer
@app.get("/analytics/skills", response_model=List[SkillSummary], dependencies=[Depends(check_user_role("admin", "volunteer"))])
def get_skills():
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="DB connection failed")
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT TRIM(UNNEST(STRING_TO_ARRAY(skills, ','))) AS skill,
                   COUNT(*) AS total_volunteers
            FROM volunteer_details
            WHERE skills IS NOT NULL
            GROUP BY skill
            ORDER BY total_volunteers DESC;
        """)
        result = cur.fetchall()
        return [{"skill": row[0], "total_volunteers": row[1]} for row in result]
    finally:
        cur.close()
        conn.close()

# Admin only
@app.get("/analytics/country_users", response_model=List[CountryUsers], dependencies=[Depends(check_user_role("admin"))])
def get_country_users():
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="DB connection failed")
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT country, COUNT(user_id)
            FROM saayam_users
            GROUP BY country
            ORDER BY COUNT(user_id) DESC;
        """)
        result = cur.fetchall()
        return [{"country": row[0], "total_users": row[1]} for row in result]
    finally:
        cur.close()
        conn.close()

# Admin only
@app.get("/analytics/emergency_contacts", response_model=EmergencyContactCoverage, dependencies=[Depends(check_user_role("admin"))])
def get_emergency_contacts():
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="DB connection failed")
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(user_id)
            FROM user_additional_details
            WHERE secondary_email_1 IS NOT NULL OR secondary_phone_1 IS NOT NULL;
        """)
        result = cur.fetchone()
        return {"users_with_emergency_contacts": result[0] if result else 0}
    finally:
        cur.close()
        conn.close()

# ========================= Organization Analytics (Protected) =========================

def _common_org_filters(org_type: Optional[str], is_collaborator: Optional[bool], params: list) -> str:
    """Builds optional org_type / is_collaborator filter clauses, appending bind params."""
    clause = ""
    if org_type is not None:
        clause += " AND org_type = %s"
        params.append(org_type)
    if is_collaborator is not None:
        clause += " AND is_collaborator = %s"
        params.append(is_collaborator)
    return clause


def _time_filter_params(
    time_filter: str,
    start_date: Optional[str],
    end_date: Optional[str],
    date_column: str,
    params: list,
) -> str:
    start, end = resolve_date_range(time_filter, start_date, end_date)
    return date_range_clause(date_column, start, end, params)


# ---- Organization Overview Dashboard ----

@app.get(
    "/analytics/organizations/overview/summary",
    response_model=OrganizationSummary,
    dependencies=[Depends(check_user_role("admin"))],
)
def get_organization_overview_summary(
    time_filter: str = Query("ALL"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    org_type: Optional[str] = Query(None),
    is_collaborator: Optional[bool] = Query(None),
):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="DB connection failed")
    try:
        cur = conn.cursor()
        params: list = []
        where = _time_filter_params(time_filter, start_date, end_date, ORG_REGISTERED_AT_COLUMN, params)
        where += _common_org_filters(org_type, is_collaborator, params)
        cur.execute(
            f"""
            SELECT
                COUNT(*) AS total_organizations,
                COUNT(*) FILTER (WHERE is_collaborator IS TRUE) AS total_collaborators,
                COUNT(*) FILTER (WHERE is_collaborator IS NOT TRUE) AS total_contributors
            FROM {ORG_TABLE}
            WHERE TRUE {where};
            """,
            params,
        )
        row = cur.fetchone()
        return {
            "total_organizations": row[0] or 0,
            "total_collaborators": row[1] or 0,
            "total_contributors": row[2] or 0,
        }
    finally:
        cur.close()
        conn.close()


@app.get(
    "/analytics/organizations/overview/types",
    response_model=List[OrganizationTypeCount],
    dependencies=[Depends(check_user_role("admin"))],
)
def get_organization_types(
    time_filter: str = Query("ALL"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    is_collaborator: Optional[bool] = Query(None),
):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="DB connection failed")
    try:
        cur = conn.cursor()
        params: list = []
        where = _time_filter_params(time_filter, start_date, end_date, ORG_REGISTERED_AT_COLUMN, params)
        where += _common_org_filters(None, is_collaborator, params)
        cur.execute(
            f"""
            SELECT org_type, COUNT(*) AS total_organizations
            FROM {ORG_TABLE}
            WHERE TRUE {where}
            GROUP BY org_type
            ORDER BY total_organizations DESC;
            """,
            params,
        )
        result = cur.fetchall()
        return [{"org_type": row[0], "total_organizations": row[1]} for row in result]
    finally:
        cur.close()
        conn.close()


@app.get(
    "/analytics/organizations/overview/sizes",
    response_model=List[OrganizationSizeCount],
    dependencies=[Depends(check_user_role("admin"))],
)
def get_organization_sizes(
    time_filter: str = Query("ALL"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    org_type: Optional[str] = Query(None),
    is_collaborator: Optional[bool] = Query(None),
):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="DB connection failed")
    try:
        cur = conn.cursor()
        params: list = []
        where = _time_filter_params(time_filter, start_date, end_date, ORG_REGISTERED_AT_COLUMN, params)
        where += _common_org_filters(org_type, is_collaborator, params)
        cur.execute(
            f"""
            SELECT {ORG_SIZE_COLUMN}, COUNT(*) AS total_organizations
            FROM {ORG_TABLE}
            WHERE TRUE {where}
            GROUP BY {ORG_SIZE_COLUMN}
            ORDER BY total_organizations DESC;
            """,
            params,
        )
        result = cur.fetchall()
        return [{"org_size": row[0], "total_organizations": row[1]} for row in result]
    finally:
        cur.close()
        conn.close()


@app.get(
    "/analytics/organizations/overview/geographic",
    response_model=List[OrganizationGeoDistribution],
    dependencies=[Depends(check_user_role("admin"))],
)
def get_organization_geographic_distribution(
    time_filter: str = Query("ALL"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    org_type: Optional[str] = Query(None),
    is_collaborator: Optional[bool] = Query(None),
):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="DB connection failed")
    try:
        cur = conn.cursor()
        params: list = []
        where = _time_filter_params(time_filter, start_date, end_date, ORG_REGISTERED_AT_COLUMN, params)
        where += _common_org_filters(org_type, is_collaborator, params)
        cur.execute(
            f"""
            SELECT city_name, COUNT(*) AS total_organizations
            FROM {ORG_TABLE}
            WHERE TRUE {where}
            GROUP BY city_name
            ORDER BY total_organizations DESC;
            """,
            params,
        )
        result = cur.fetchall()
        return [{"city": row[0], "total_organizations": row[1]} for row in result]
    finally:
        cur.close()
        conn.close()


@app.get(
    "/analytics/organizations/overview/registration_trends",
    response_model=List[OrganizationRegistrationTrend],
    dependencies=[Depends(check_user_role("admin"))],
)
def get_organization_registration_trends(
    time_filter: str = Query("30D"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    org_type: Optional[str] = Query(None),
    is_collaborator: Optional[bool] = Query(None),
):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="DB connection failed")
    try:
        cur = conn.cursor()
        params: list = []
        where = _time_filter_params(time_filter, start_date, end_date, ORG_REGISTERED_AT_COLUMN, params)
        where += _common_org_filters(org_type, is_collaborator, params)
        bucket = trend_bucket(time_filter)
        cur.execute(
            f"""
            SELECT date_trunc(%s, {ORG_REGISTERED_AT_COLUMN}) AS period, COUNT(*) AS total_organizations
            FROM {ORG_TABLE}
            WHERE TRUE {where}
            GROUP BY period
            ORDER BY period;
            """,
            [bucket] + params,
        )
        result = cur.fetchall()
        return [{"period": row[0].isoformat(), "total_organizations": row[1]} for row in result]
    finally:
        cur.close()
        conn.close()


# ---- Organization Performance Dashboard ----

@app.get(
    "/analytics/organizations/performance/summary",
    response_model=OrganizationPerformanceSummary,
    dependencies=[Depends(check_user_role("admin"))],
)
def get_organization_performance_summary(
    time_filter: str = Query("ALL"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    org_type: Optional[str] = Query(None),
):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="DB connection failed")
    try:
        cur = conn.cursor()
        params: list = []
        where = _time_filter_params(time_filter, start_date, end_date, ORG_REGISTERED_AT_COLUMN, params)
        where += _common_org_filters(org_type, None, params)
        cur.execute(
            f"""
            SELECT AVG({ORG_RATING_COLUMN}), COUNT(*) FILTER (WHERE {ORG_RATING_COLUMN} IS NOT NULL)
            FROM {ORG_TABLE}
            WHERE TRUE {where};
            """,
            params,
        )
        row = cur.fetchone()
        return {
            "average_rating": float(row[0]) if row[0] is not None else None,
            "total_rated_organizations": row[1] or 0,
        }
    finally:
        cur.close()
        conn.close()


@app.get(
    "/analytics/organizations/performance/top_rated",
    response_model=List[TopRatedOrganization],
    dependencies=[Depends(check_user_role("admin"))],
)
def get_top_rated_organizations(
    time_filter: str = Query("ALL"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    org_type: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=100),
):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="DB connection failed")
    try:
        cur = conn.cursor()
        params: list = []
        where = _time_filter_params(time_filter, start_date, end_date, ORG_REGISTERED_AT_COLUMN, params)
        where += _common_org_filters(org_type, None, params)
        params.append(limit)
        cur.execute(
            f"""
            SELECT org_name, org_type, {ORG_RATING_COLUMN}
            FROM {ORG_TABLE}
            WHERE {ORG_RATING_COLUMN} IS NOT NULL {where}
            ORDER BY {ORG_RATING_COLUMN} DESC
            LIMIT %s;
            """,
            params,
        )
        result = cur.fetchall()
        return [{"org_name": row[0], "org_type": row[1], "rating": float(row[2])} for row in result]
    finally:
        cur.close()
        conn.close()


@app.get(
    "/analytics/organizations/performance/ratings_by_category",
    response_model=List[OrganizationRatingByCategory],
    dependencies=[Depends(check_user_role("admin"))],
)
def get_organization_ratings_by_category(
    time_filter: str = Query("ALL"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    is_collaborator: Optional[bool] = Query(None),
):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="DB connection failed")
    try:
        cur = conn.cursor()
        params: list = []
        where = _time_filter_params(time_filter, start_date, end_date, ORG_REGISTERED_AT_COLUMN, params)
        where += _common_org_filters(None, is_collaborator, params)
        cur.execute(
            f"""
            SELECT mission, AVG({ORG_RATING_COLUMN}), COUNT(*)
            FROM {ORG_TABLE}
            WHERE TRUE {where}
            GROUP BY mission
            ORDER BY AVG({ORG_RATING_COLUMN}) DESC NULLS LAST;
            """,
            params,
        )
        result = cur.fetchall()
        return [
            {"category": row[0], "average_rating": float(row[1]) if row[1] is not None else None, "total_organizations": row[2]}
            for row in result
        ]
    finally:
        cur.close()
        conn.close()
