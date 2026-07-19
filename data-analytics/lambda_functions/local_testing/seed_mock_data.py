"""Seed mock organizations data for local testing of the Organization Analytics API."""
import random
import psycopg2
from datetime import datetime, timedelta

random.seed(42)

DB = dict(host="localhost", database="saayam_local", user="saayam",
          password="saayam_local", port=5432)
SCHEMA = "virginia_dev_saayam_rdbms"

STATES = [
    ("ST-VA", 1, "Virginia", "VA"), ("ST-NY", 1, "New York", "NY"),
    ("ST-CA", 1, "California", "CA"), ("ST-TX", 1, "Texas", "TX"),
    ("ST-WA", 1, "Washington", "WA"), ("ST-NJ", 1, "New Jersey", "NJ"),
]
CITIES = {
    "ST-VA": ["Richmond", "Arlington", "Norfolk"],
    "ST-NY": ["Buffalo", "New York City", "Albany"],
    "ST-CA": ["San Jose", "Los Angeles", "Sacramento"],
    "ST-TX": ["Austin", "Dallas", "Houston"],
    "ST-WA": ["Seattle", "Tacoma"],
    "ST-NJ": ["Newark", "Jersey City"],
}
ORG_WORDS = ["Hope", "Bridge", "Unity", "Care", "Rise", "Nova", "Summit",
             "Beacon", "Anchor", "Harvest", "Lumen", "Pioneer"]
ORG_SUFFIX = ["Foundation", "Alliance", "Collective", "Labs", "Partners",
              "Network", "Trust", "Works", "Group", "Initiative"]

def main():
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()
    cur.execute(f"SET search_path TO {SCHEMA}")

    cur.execute("INSERT INTO country (country_id, country_name) VALUES (1, 'United States') ON CONFLICT DO NOTHING")
    for s in STATES:
        cur.execute("INSERT INTO state (state_id, country_id, state_name, state_code) "
                    "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING", s)

    now = datetime.utcnow()
    n = 120
    for i in range(n):
        name = f"{random.choice(ORG_WORDS)} {random.choice(ORG_SUFFIX)} {i+1}"
        state_id = random.choice(STATES)[0]
        city = random.choice(CITIES[state_id])
        org_type = random.choices(["non_profit", "for_profit"], weights=[0.7, 0.3])[0]
        org_size = random.choices(["small", "medium", "large"], weights=[0.5, 0.3, 0.2])[0]
        # ~20% unrated
        rating = None if random.random() < 0.2 else random.choices([1, 2, 3, 4, 5],
                 weights=[0.05, 0.10, 0.20, 0.35, 0.30])[0]
        is_collab = random.random() < 0.35
        is_contrib = random.random() < 0.55
        # registrations spread over the last 2 years, denser recently
        days_ago = int(random.betavariate(1.2, 3.0) * 730)
        created = now - timedelta(days=days_ago,
                                  hours=random.randint(0, 23),
                                  minutes=random.randint(0, 59))
        cur.execute(
            """INSERT INTO organizations
               (org_name, street, city_name, state_id, zip_code, mission, web_url,
                phone, email, org_type, org_size, org_rating, is_collaborator,
                is_contributor, created_at, last_updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (name, f"{random.randint(10,999)} Main St", city, state_id,
             f"{random.randint(10000,99999)}", "Serving the community.",
             "https://example.org", f"+1716555{random.randint(1000,9999)}",
             f"contact{i}@example.org", org_type, org_size, rating,
             is_collab, is_contrib, created, created))

    conn.commit()
    cur.execute("SELECT COUNT(*) FROM organizations")
    print(f"Seeded {cur.fetchone()[0]} organizations.")
    cur.close(); conn.close()

if __name__ == "__main__":
    main()
