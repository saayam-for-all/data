from fastapi import FastAPI, Depends, HTTPException, Security, Query
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
import psycopg2
import os
import jwt
from typing import List, Optional
from dotenv import load_dotenv

from src.utils.time_filters import (
    resolve_date_range,
    date_range_clause,
    trend_bucket,
    resolve_group_by,
)

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

# Column names confirmed against the issue #228 sample data
# (data-analytics/sql/organizations.csv / organizations.csv attached to the issue):
# org_id, org_name, street, city_name, state_id, zip_code, mission, web_url,
# phone, email, org_type, org_size, org_rating, is_collaborator, is_contributor,
# created_at, last_updated_at.
# NOTE: is_contributor may not exist yet in the current dev database (per the
# issue's Database Note) — queries below tolerate it being NULL/absent-in-data
# rather than failing.
ORG_SIZE_COLUMN = "org_size"
ORG_RATING_COLUMN = "org_rating"
ORG_REGISTERED_AT_COLUMN = "created_at"
ORG_CONTRIBUTOR_COLUMN = "is_contributor"
ORG_STATE_TABLE = f"{ORG_SCHEMA}.states"

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

# ---- Organization Dashboard (single consolidated endpoint, issue #228) ----
class OrganizationDashboardFilters(BaseModel):
    """Body for POST /analytics/organizations. Mirrors the common filter
    structure already used by the Request/Volunteer/Beneficiary/KPI dashboards.
    """
    time_filter: str = "ALL"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    group_by: Optional[str] = None
    region: Optional[str] = "ALL"
    organization_type: Optional[str] = "ALL"

class OrgDashboardSummary(BaseModel):
    total_organizations: int
    total_collaborators: int
    total_contributors: int
    average_org_rating: Optional[float]

class OrgGrowthPoint(BaseModel):
    period: str
    total_organizations: int
    total_collaborators: int

class OrgByLocation(BaseModel):
    state_id: Optional[str]
    state_name: Optional[str]
    organization_count: int
    percentage: float

class OrgBySize(BaseModel):
    org_size: Optional[str]
    organization_count: int

class OrgCollaboratorVsContributor(BaseModel):
    type: str
    organization_count: int
    percentage: float

class OrgRatingDistributionItem(BaseModel):
    rating: int
    organization_count: int

class OrgTypeDistributionPoint(BaseModel):
    period: str
    for_profit: int
    non_profit: int
    total: int

class OrganizationDashboardResponse(BaseModel):
    summary: OrgDashboardSummary
    growth_trend: List[OrgGrowthPoint]
    organizations_by_location: List[OrgByLocation]
    organizations_by_size: List[OrgBySize]
    collaborator_vs_contributor: List[OrgCollaboratorVsContributor]
    rating_distribution: List[OrgRatingDistributionItem]
    organization_type_distribution: List[OrgTypeDistributionPoint]

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


def _region_filter(region: Optional[str], params: list) -> str:
    """Filters on the joined states table by state name or 2-letter code.
    'ALL' / None / '' means no region filter."""
    if not region or region.strip().upper() == "ALL":
        return ""
    params.append(region)
    params.append(region)
    return " AND (UPPER(s.state_name) = UPPER(%s) OR UPPER(s.state_id) = UPPER(%s))"


def _organization_type_filter(organization_type: Optional[str], params: list) -> str:
    """Filters on org_type, tolerant of formatting differences between the UI's
    snake_case values (non_profit/for_profit) and the stored values
    (Non-Profit/For-profit): both sides are normalized to UPPER_SNAKE_CASE."""
    if not organization_type or organization_type.strip().upper() == "ALL":
        return ""
    normalized = organization_type.strip().upper().replace("-", "_").replace(" ", "_")
    params.append(normalized)
    return (
        " AND UPPER(REPLACE(REPLACE(o.org_type, '-', '_'), ' ', '_')) = %s"
    )


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


# ---- Organization Dashboard (single consolidated endpoint, issue #228) ----
#
# One POST endpoint feeds all three Organization Dashboard tabs (Growth &
# Location / Size & Contribution / Ratings & Type), reusing the same
# time_filter + region + organization_type common-filter contract as the
# other dashboards.

@app.post(
    "/analytics/organizations",
    response_model=OrganizationDashboardResponse,
    dependencies=[Depends(check_user_role("admin"))],
)
def get_organization_dashboard(filters: OrganizationDashboardFilters):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="DB connection failed")
    try:
        cur = conn.cursor()

        base_params: list = []
        where = _time_filter_params(
            filters.time_filter, filters.start_date, filters.end_date, ORG_REGISTERED_AT_COLUMN, base_params
        )
        where += _region_filter(filters.region, base_params)
        where += _organization_type_filter(filters.organization_type, base_params)

        # When the UI doesn't pass group_by explicitly, pick a sensible default
        # from the time_filter span (short windows -> daily, long ones -> monthly).
        _default_group_by_by_span = {
            "7D": "daily", "30D": "daily", "1Y": "monthly", "ALL": "monthly", "CUSTOM": "daily",
        }
        default_group_by = _default_group_by_by_span.get((filters.time_filter or "ALL").upper(), "monthly")
        bucket = resolve_group_by(filters.group_by, default=default_group_by)

        joined_table = f"{ORG_TABLE} o LEFT JOIN {ORG_STATE_TABLE} s ON o.state_id = s.state_id"

        # --- Summary KPI cards ---
        cur.execute(
            f"""
            SELECT
                COUNT(*) AS total_organizations,
                COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS total_collaborators,
                COUNT(*) FILTER (WHERE o.{ORG_CONTRIBUTOR_COLUMN} IS TRUE) AS total_contributors,
                AVG(o.{ORG_RATING_COLUMN}) AS average_org_rating
            FROM {joined_table}
            WHERE TRUE {where};
            """,
            base_params,
        )
        row = cur.fetchone()
        total_organizations = row[0] or 0
        summary = {
            "total_organizations": total_organizations,
            "total_collaborators": row[1] or 0,
            "total_contributors": row[2] or 0,
            "average_org_rating": round(float(row[3]), 2) if row[3] is not None else None,
        }

        # --- Tab 1.1: Growth trend (cumulative organizations & collaborators) ---
        cur.execute(
            f"""
            SELECT period,
                SUM(new_orgs) OVER (ORDER BY period) AS total_organizations,
                SUM(new_collabs) OVER (ORDER BY period) AS total_collaborators
            FROM (
                SELECT date_trunc(%s, o.{ORG_REGISTERED_AT_COLUMN}) AS period,
                    COUNT(*) AS new_orgs,
                    COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS new_collabs
                FROM {joined_table}
                WHERE TRUE {where}
                GROUP BY period
            ) sub
            ORDER BY period;
            """,
            [bucket] + base_params,
        )
        growth_trend = [
            {
                "period": row[0].isoformat(),
                "total_organizations": int(row[1]),
                "total_collaborators": int(row[2]),
            }
            for row in cur.fetchall()
        ]

        # --- Tab 1.2: Organizations by location (state) ---
        cur.execute(
            f"""
            SELECT s.state_id, s.state_name, COUNT(*) AS organization_count
            FROM {joined_table}
            WHERE TRUE {where}
            GROUP BY s.state_id, s.state_name
            ORDER BY organization_count DESC;
            """,
            base_params,
        )
        location_rows = cur.fetchall()
        location_total = sum(r[2] for r in location_rows) or 0
        organizations_by_location = [
            {
                "state_id": row[0],
                "state_name": row[1],
                "organization_count": row[2],
                "percentage": round(row[2] * 100.0 / location_total, 1) if location_total else 0.0,
            }
            for row in location_rows
        ]

        # --- Tab 2.3: Organizations by size ---
        cur.execute(
            f"""
            SELECT o.{ORG_SIZE_COLUMN}, COUNT(*) AS organization_count
            FROM {joined_table}
            WHERE TRUE {where}
            GROUP BY o.{ORG_SIZE_COLUMN}
            ORDER BY organization_count DESC;
            """,
            base_params,
        )
        organizations_by_size = [
            {"org_size": row[0], "organization_count": row[1]} for row in cur.fetchall()
        ]

        # --- Tab 2.4: Collaborator vs contributor ---
        cur.execute(
            f"""
            SELECT
                COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS collaborator_count,
                COUNT(*) FILTER (WHERE o.{ORG_CONTRIBUTOR_COLUMN} IS TRUE) AS contributor_count
            FROM {joined_table}
            WHERE TRUE {where};
            """,
            base_params,
        )
        cc_row = cur.fetchone()
        collaborator_count = cc_row[0] or 0
        contributor_count = cc_row[1] or 0
        cc_total = collaborator_count + contributor_count
        collaborator_vs_contributor = [
            {
                "type": "collaborator",
                "organization_count": collaborator_count,
                "percentage": round(collaborator_count * 100.0 / cc_total, 1) if cc_total else 0.0,
            },
            {
                "type": "contributor",
                "organization_count": contributor_count,
                "percentage": round(contributor_count * 100.0 / cc_total, 1) if cc_total else 0.0,
            },
        ]

        # --- Tab 3.5: Rating distribution (1-5 stars). NULL ratings excluded, never fail. ---
        cur.execute(
            f"""
            SELECT ROUND(o.{ORG_RATING_COLUMN})::int AS rating, COUNT(*) AS organization_count
            FROM {joined_table}
            WHERE o.{ORG_RATING_COLUMN} IS NOT NULL {where}
            GROUP BY rating
            ORDER BY rating;
            """,
            base_params,
        )
        rating_counts = {int(row[0]): row[1] for row in cur.fetchall() if row[0] is not None}
        rating_distribution = [
            {"rating": r, "organization_count": rating_counts.get(r, 0)} for r in range(1, 6)
        ]

        # --- Tab 3.6: For-profit vs non-profit over time (cumulative, stacked) ---
        cur.execute(
            f"""
            SELECT period,
                SUM(new_for_profit) OVER (ORDER BY period) AS for_profit,
                SUM(new_non_profit) OVER (ORDER BY period) AS non_profit
            FROM (
                SELECT date_trunc(%s, o.{ORG_REGISTERED_AT_COLUMN}) AS period,
                    COUNT(*) FILTER (WHERE UPPER(REPLACE(o.org_type, '-', '_')) = 'FOR_PROFIT') AS new_for_profit,
                    COUNT(*) FILTER (WHERE UPPER(REPLACE(o.org_type, '-', '_')) = 'NON_PROFIT') AS new_non_profit
                FROM {joined_table}
                WHERE TRUE {where}
                GROUP BY period
            ) sub
            ORDER BY period;
            """,
            [bucket] + base_params,
        )
        organization_type_distribution = [
            {
                "period": row[0].isoformat(),
                "for_profit": int(row[1]),
                "non_profit": int(row[2]),
                "total": int(row[1]) + int(row[2]),
            }
            for row in cur.fetchall()
        ]

        return {
            "summary": summary,
            "growth_trend": growth_trend,
            "organizations_by_location": organizations_by_location,
            "organizations_by_size": organizations_by_size,
            "collaborator_vs_contributor": collaborator_vs_contributor,
            "rating_distribution": rating_distribution,
            "organization_type_distribution": organization_type_distribution,
        }
    finally:
        cur.close()
        conn.close()
