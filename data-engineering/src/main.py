from fastapi import FastAPI, Depends, HTTPException, Security
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
import psycopg2
import os
import jwt
from typing import List
from dotenv import load_dotenv

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
