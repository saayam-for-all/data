"""
Loads deterministic mock data for issue #586 verification into the local
Postgres+PostGIS container (saayam586), including:
  - 300 normal requests spread across 5 UTC days (so the archive partitions
    by day and we can test "no gaps" / "no duplicates" across runs).
  - lead_volunteer_id / beneficiary_id null ratios matching prod's real stats
    from the #573 schema audit (218/221 null lead_volunteer_id, 8/221 null
    beneficiary_id) so check 5's "broken reference survives" scenario is
    exercised against realistic nullability, not just a contrived row.
  - One row whose req_cat_id points at a help_categories row that does not
    exist. Prod enforces this FK, so to insert it locally we drop and later
    re-add the constraint, exactly as issue #586 instructs ("build a local
    copy of the schema, insert a request whose category points at nothing").
"""
import datetime
import os
import random

import psycopg2

random.seed(586)

conn = psycopg2.connect(host="localhost", port=55432, user="postgres", password="postgres", dbname="saayam")
conn.autocommit = False
cur = conn.cursor()

cur.execute("SET search_path TO virginia_dev_saayam_rdbms, public;")

# ---- lookup rows -----------------------------------------------------------
cur.execute("INSERT INTO help_categories (cat_id, cat_name, cat_desc) VALUES "
            "('1','Housing','Housing help'), ('2','Food','Food help'), ('3','Medical','Medical help') "
            "ON CONFLICT DO NOTHING;")
cur.execute("INSERT INTO request_for (req_for, req_for_desc) VALUES ('SELF','0'), ('OTHER','1') "
            "ON CONFLICT DO NOTHING;")
cur.execute("INSERT INTO request_isleadvol (req_islead, req_islead_desc) VALUES ('NO','0'), ('YES','1') "
            "ON CONFLICT DO NOTHING;")
cur.execute("INSERT INTO request_types (req_type, req_type_desc) VALUES ('IN_PERSON','0'), ('REMOTE','1') "
            "ON CONFLICT DO NOTHING;")
cur.execute("INSERT INTO request_priorities (req_priority, req_priority_desc) VALUES "
            "('LOW','0'), ('MEDIUM','1'), ('HIGH','2'), ('CRITICAL','3') ON CONFLICT DO NOTHING;")
cur.execute("INSERT INTO request_statuses (req_status, req_status_desc) VALUES "
            "('CREATED','0'), ('IN_PROGRESS','2'), ('RESOLVED','3') ON CONFLICT DO NOTHING;")

cur.execute("SELECT cat_id FROM help_categories ORDER BY cat_id;")
cat_ids = [r[0] for r in cur.fetchall()]
cur.execute("SELECT req_for_id FROM request_for ORDER BY req_for_id;")
for_ids = [r[0] for r in cur.fetchall()]
cur.execute("SELECT req_islead_id FROM request_isleadvol ORDER BY req_islead_id;")
islead_ids = [r[0] for r in cur.fetchall()]
cur.execute("SELECT req_type_id FROM request_types ORDER BY req_type_id;")
type_ids = [r[0] for r in cur.fetchall()]
cur.execute("SELECT req_priority_id FROM request_priorities ORDER BY req_priority_id;")
priority_ids = [r[0] for r in cur.fetchall()]
cur.execute("SELECT req_status_id FROM request_statuses ORDER BY req_status_id;")
status_ids = [r[0] for r in cur.fetchall()]

# ---- users ------------------------------------------------------------------
NUM_USERS = 40
user_ids = [f"SID-{i:08d}" for i in range(NUM_USERS)]
for uid in user_ids:
    cur.execute("INSERT INTO users (user_id) VALUES (%s) ON CONFLICT DO NOTHING;", (uid,))

# ---- requests ---------------------------------------------------------------
NUM_REQUESTS = 300
NUM_DAYS = 5
base_day = datetime.datetime(2026, 11, 10, 0, 0, 0)  # UTC, matches 'timestamp without time zone' convention

rows = []
for i in range(NUM_REQUESTS):
    req_id = f"REQ-{i:06d}"
    day_offset = i % NUM_DAYS
    ts = base_day + datetime.timedelta(days=day_offset, seconds=random.randint(0, 86399))

    creator_id = random.choice(user_ids)
    # prod stats (see data-analytics/testing #573 audit): ~98.6% null lead_volunteer_id, ~3.6% null beneficiary_id
    lead_volunteer_id = None if random.random() < 0.986 else random.choice(user_ids)
    beneficiary_id = None if random.random() < 0.036 else random.choice(user_ids)

    rows.append((
        req_id, creator_id, beneficiary_id, lead_volunteer_id,
        random.choice(cat_ids), random.choice(for_ids), random.choice(islead_ids),
        random.choice(type_ids), random.choice(priority_ids), random.choice(status_ids),
        f"Request {i}", f"Description for request {i}",
        None, None, None,  # req_doc_link, audio_req_desc, deletion_reason
        None, None,  # req_loc, created_loc (kept simple; FK integrity is what's under test, not geometry)
        random.random() < 0.05,  # iscalamity
        random.random() < 0.5,  # to_public
        ts, None, ts,
    ))

cur.executemany(
    """
    INSERT INTO requests (
        req_id, creator_id, beneficiary_id, lead_volunteer_id,
        req_cat_id, req_for_id, req_islead_id, req_type_id, req_priority_id, req_status_id,
        req_subj, req_desc, req_doc_link, audio_req_desc, deletion_reason,
        req_loc, created_loc, iscalamity, to_public, submission_date, serviced_date, last_updated_at
    ) VALUES (%s,%s,%s,%s, %s,%s,%s,%s,%s,%s, %s,%s,%s,%s,%s, %s,%s,%s,%s,%s,%s,%s)
    """,
    rows,
)

# ---- the broken-reference row (check 5) -------------------------------------
# Prod enforces req_cat_id -> help_categories; drop it locally just long enough
# to insert one row pointing at a category id that was never created, per the
# issue's own instructions, then restore the constraint so every OTHER insert
# stays protected by it.
cur.execute("""
    SELECT conname FROM pg_constraint
    WHERE conrelid = 'virginia_dev_saayam_rdbms.requests'::regclass
      AND confrelid = 'virginia_dev_saayam_rdbms.help_categories'::regclass;
""")
fk_name = cur.fetchone()[0]
cur.execute(f"ALTER TABLE requests DROP CONSTRAINT {fk_name};")

broken_ts = base_day + datetime.timedelta(days=2, hours=5)
cur.execute(
    """
    INSERT INTO requests (
        req_id, creator_id, beneficiary_id, lead_volunteer_id,
        req_cat_id, req_for_id, req_islead_id, req_type_id, req_priority_id, req_status_id,
        req_subj, req_desc, req_doc_link, audio_req_desc, deletion_reason,
        req_loc, created_loc, iscalamity, to_public, submission_date, serviced_date, last_updated_at
    ) VALUES (%s,%s,%s,%s, %s,%s,%s,%s,%s,%s, %s,%s,%s,%s,%s, %s,%s,%s,%s,%s,%s,%s)
    """,
    (
        "REQ-BROKENREF", user_ids[0], None, None,
        "99-does-not-exist", for_ids[0], islead_ids[0], type_ids[0], priority_ids[0], status_ids[0],
        "Broken category reference", "req_cat_id points at a category row that was never created",
        None, None, None, None, None, False, False, broken_ts, None, broken_ts,
    ),
)

cur.execute(f"""
    ALTER TABLE requests ADD CONSTRAINT {fk_name}
    FOREIGN KEY (req_cat_id) REFERENCES help_categories(cat_id)
    NOT VALID;
""")
# NOT VALID: re-protects every future insert without re-checking (and failing on) the
# broken row we just inserted on purpose. New rows are still fully enforced.

conn.commit()
print(f"loaded {NUM_REQUESTS} normal requests + 1 broken-reference request across {NUM_DAYS} days, "
      f"starting {base_day.isoformat()}Z")
cur.close()
conn.close()
