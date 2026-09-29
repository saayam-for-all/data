"""
Local mock DB for Phase 2 testing of application_analytics_request.

Builds an in-memory SQLite database that mirrors the relevant subset of the
Saayam Virginia PostgreSQL schema (request, users, country, help_categories)
so the Lambda can be tested without real DB credentials.

Run directly to see a quick demo:
    python mock_local_db.py
"""

import sqlite3
from datetime import datetime, timedelta
import random


def build_mock_db():
    """Return a sqlite3.Connection populated with mock Saayam-shaped data."""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()

    # ── Schema (subset matching Saayam_Table.column.names_data.xlsx) ──
    cur.executescript("""
        CREATE TABLE country (
            country_id INTEGER PRIMARY KEY,
            country_name TEXT,
            country_code TEXT
        );
        CREATE TABLE help_categories (
            cat_id INTEGER PRIMARY KEY,
            cat_name TEXT,
            cat_desc TEXT
        );
        CREATE TABLE users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            primary_email_address TEXT,
            country_id INTEGER,
            FOREIGN KEY(country_id) REFERENCES country(country_id)
        );
        CREATE TABLE request (
            req_id INTEGER PRIMARY KEY,
            req_user_id INTEGER,
            req_cat_id INTEGER,
            req_subj TEXT,
            req_desc TEXT,
            submission_date TIMESTAMP,
            FOREIGN KEY(req_user_id) REFERENCES users(user_id),
            FOREIGN KEY(req_cat_id) REFERENCES help_categories(cat_id)
        );
    """)

    # ── Reference data ──
    countries = [
        (1, "United States", "US"),
        (2, "India", "IN"),
        (3, "United Kingdom", "GB"),
        (4, "Canada", "CA"),
        (5, "Australia", "AU"),
        (6, "Germany", "DE"),
    ]
    categories = [
        (1, "Education", "Educational support"),
        (2, "Healthcare", "Medical assistance"),
        (3, "Food", "Food and groceries"),
        (4, "Shelter", "Housing assistance"),
        (5, "Employment", "Job search help"),
    ]
    cur.executemany("INSERT INTO country VALUES (?, ?, ?)", countries)
    cur.executemany("INSERT INTO help_categories VALUES (?, ?, ?)", categories)

    # ── Users (50, distributed across countries) ──
    random.seed(42)
    users = [
        (i, f"User {i}", f"user{i}@test.com", random.choice([c[0] for c in countries]))
        for i in range(1, 51)
    ]
    cur.executemany("INSERT INTO users VALUES (?, ?, ?, ?)", users)

    # ── Requests: 500 spread across the last 18 months ──
    now = datetime.now()
    requests = []
    for i in range(1, 501):
        days_ago = random.randint(0, 540)
        sub_date = now - timedelta(days=days_ago, hours=random.randint(0, 23))
        requests.append((
            i,
            random.randint(1, 50),
            random.randint(1, 5),
            f"Subject {i}",
            f"Description {i}",
            sub_date.isoformat(sep=" "),
        ))
    cur.executemany("INSERT INTO request VALUES (?, ?, ?, ?, ?, ?)", requests)

    conn.commit()
    return conn


def build_empty_db():
    """Same schema, no data — for empty-DB tests."""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE country (country_id INTEGER PRIMARY KEY, country_name TEXT, country_code TEXT);
        CREATE TABLE help_categories (cat_id INTEGER PRIMARY KEY, cat_name TEXT, cat_desc TEXT);
        CREATE TABLE users (user_id INTEGER PRIMARY KEY, full_name TEXT, primary_email_address TEXT, country_id INTEGER);
        CREATE TABLE request (req_id INTEGER PRIMARY KEY, req_user_id INTEGER, req_cat_id INTEGER, req_subj TEXT, req_desc TEXT, submission_date TIMESTAMP);
    """)
    conn.commit()
    return conn


if __name__ == "__main__":
    conn = build_mock_db()
    cur = conn.cursor()

    print("=== Sample requests ===")
    for row in cur.execute("SELECT req_id, req_user_id, req_cat_id, submission_date FROM request LIMIT 5"):
        print(row)

    print("\n=== Counts ===")
    print("Total requests:", cur.execute("SELECT COUNT(*) FROM request").fetchone()[0])
    print("Total users:   ", cur.execute("SELECT COUNT(*) FROM users").fetchone()[0])
    print("Total countries:", cur.execute("SELECT COUNT(*) FROM country").fetchone()[0])
    print("Total categories:", cur.execute("SELECT COUNT(*) FROM help_categories").fetchone()[0])
