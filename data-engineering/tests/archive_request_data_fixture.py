"""Throwaway local PostgreSQL with the #573 schema and synthetic requests.

PostGIS is not installed locally, so geometry columns are text and
public.ST_AsText is a pass-through stub. Everything else follows saayam_schema.sql.
"""

import contextlib
import os
import shutil
import socket
import subprocess
import tempfile

import psycopg2

SCHEMA = "virginia_dev_saayam_rdbms"

DDL = f"""
CREATE SCHEMA {SCHEMA};
CREATE FUNCTION public.ST_AsText(g text) RETURNS text LANGUAGE sql IMMUTABLE AS 'SELECT g';
SET search_path = {SCHEMA};

CREATE TABLE help_categories (cat_id varchar(50) PRIMARY KEY, cat_name varchar(100) NOT NULL,
    cat_desc varchar(150) NOT NULL, last_updated_at timestamp(6));
CREATE TABLE request_for (req_for_id serial PRIMARY KEY, req_for varchar(25) NOT NULL,
    req_for_desc varchar(125), last_updated_at timestamp(6));
CREATE TABLE request_isleadvol (req_islead_id serial PRIMARY KEY, req_islead varchar(15) NOT NULL,
    req_islead_desc varchar(100), last_updated_at timestamp(6));
CREATE TABLE request_types (req_type_id serial PRIMARY KEY, req_type varchar(25),
    req_type_desc varchar(125), last_updated_at timestamp(6));
CREATE TABLE request_priorities (req_priority_id serial PRIMARY KEY, req_priority varchar(25) NOT NULL,
    req_priority_desc varchar(125), last_updated_at timestamp(6));
CREATE TABLE request_statuses (req_status_id serial PRIMARY KEY, req_status varchar(25) NOT NULL,
    req_status_desc varchar(125), last_updated_at timestamp(6));
CREATE TABLE users (user_id varchar(255) PRIMARY KEY, full_name varchar(255),
    last_updated_at timestamp(6));

CREATE TABLE requests (
    req_id varchar(255) PRIMARY KEY,
    creator_id varchar(255) NOT NULL REFERENCES users(user_id),
    beneficiary_id varchar(255) REFERENCES users(user_id),
    lead_volunteer_id varchar(255) REFERENCES users(user_id),
    req_cat_id varchar(50) NOT NULL REFERENCES help_categories(cat_id),
    req_for_id integer NOT NULL REFERENCES request_for(req_for_id),
    req_islead_id integer NOT NULL REFERENCES request_isleadvol(req_islead_id),
    req_type_id integer NOT NULL REFERENCES request_types(req_type_id),
    req_priority_id integer NOT NULL REFERENCES request_priorities(req_priority_id),
    req_status_id integer NOT NULL REFERENCES request_statuses(req_status_id),
    req_subj varchar(125) NOT NULL, req_desc varchar(255) NOT NULL,
    req_doc_link text, audio_req_desc varchar(255), deletion_reason text,
    req_loc text, created_loc text, iscalamity boolean, to_public boolean DEFAULT false,
    submission_date timestamp, serviced_date timestamp, last_updated_at timestamp(6)
);

INSERT INTO help_categories VALUES ('1','Food','Food help','2026-01-01'),
    ('1.3','Groceries','Grocery help','2026-01-01'), ('2','Housing','Housing help','2026-01-01');
INSERT INTO request_for (req_for_id, req_for) VALUES (0,'SELF'),(1,'OTHER');
INSERT INTO request_isleadvol (req_islead_id, req_islead) VALUES (0,'NO'),(1,'YES');
INSERT INTO request_types (req_type_id, req_type) VALUES (0,'IN_PERSON'),(1,'REMOTE');
INSERT INTO request_priorities (req_priority_id, req_priority) VALUES (0,'LOW'),(1,'MEDIUM'),(2,'HIGH'),(3,'CRITICAL');
INSERT INTO request_statuses (req_status_id, req_status) VALUES (0,'CREATED'),(1,'MATCHING_VOLUNTEER'),
    (2,'IN_PROGRESS'),(3,'RESOLVED'),(4,'CANCELLED');
INSERT INTO users (user_id, full_name) VALUES ('SID-00-000-000-000-000-001','Asha Rao'),
    ('SID-00-000-000-000-000-002','Ben Carter'),('SID-00-000-000-000-000-003','Chen Li');

-- 8 requests: 6 with no lead volunteer, 3 with no beneficiary, one with a comma/quote/newline subject.
INSERT INTO requests (req_id, creator_id, beneficiary_id, lead_volunteer_id, req_cat_id, req_for_id,
    req_islead_id, req_type_id, req_priority_id, req_status_id, req_subj, req_desc, req_loc,
    iscalamity, to_public, submission_date, serviced_date, last_updated_at) VALUES
 ('REQ-000-000-000-0001','SID-00-000-000-000-000-001','SID-00-000-000-000-000-001',NULL,'1',0,0,0,1,0,'Need groceries','Weekly food',  'POINT(-122.4 37.8)',false,true,'2026-01-05','2026-01-06','2026-01-06 10:00'),
 ('REQ-000-000-000-0002','SID-00-000-000-000-000-001','SID-00-000-000-000-000-002',NULL,'1.3',1,0,0,2,1,'Help for neighbour','Groceries',NULL,false,true,'2026-01-07',NULL,'2026-01-08 10:00'),
 ('REQ-000-000-000-0003','SID-00-000-000-000-000-002',NULL,'SID-00-000-000-000-000-003','2',1,1,1,3,2,'Rent help','Short on rent',NULL,true,false,'2026-01-09','2026-01-12','2026-01-12 09:00'),
 ('REQ-000-000-000-0004','SID-00-000-000-000-000-002','SID-00-000-000-000-000-002',NULL,'2',0,0,1,0,3,'Form help','Fill a form',NULL,false,true,'2026-01-10','2026-01-11','2026-01-20 09:00'),
 ('REQ-000-000-000-0005','SID-00-000-000-000-000-003',NULL,NULL,'1',0,0,0,1,4,'Cancelled','No longer needed',NULL,false,true,'2026-01-11',NULL,'2026-01-21 09:00'),
 ('REQ-000-000-000-0006','SID-00-000-000-000-000-003','SID-00-000-000-000-000-001',NULL,'1.3',1,0,0,2,0,E'Food, "urgent"\nplease','Line one',NULL,false,true,'2026-01-12',NULL,'2026-02-02 09:00'),
 ('REQ-000-000-000-0007','SID-00-000-000-000-000-001','SID-00-000-000-000-000-001',NULL,'2',0,0,1,1,1,'Housing search','Find housing',NULL,false,true,'2026-01-13',NULL,'2026-02-03 09:00'),
 ('REQ-000-000-000-0008','SID-00-000-000-000-000-001','SID-00-000-000-000-000-001','SID-00-000-000-000-000-002','1',0,1,0,1,3,'Delivery','Deliver food',NULL,false,true,'2026-01-14','2026-01-15','2026-02-04 09:00');
"""


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _pg_bin(name):
    for base in ("/opt/homebrew/opt/postgresql@16/bin", "/usr/lib/postgresql/16/bin", "/usr/local/bin"):
        if os.path.exists(os.path.join(base, name)):
            return os.path.join(base, name)
    found = shutil.which(name)
    if not found:
        raise FileNotFoundError(name)
    return found


@contextlib.contextmanager
def local_postgres():
    """Start a temporary PostgreSQL cluster; yield connection settings."""
    root = tempfile.mkdtemp(prefix="archive_pg_")
    data, port = os.path.join(root, "data"), _free_port()
    subprocess.run([_pg_bin("initdb"), "-D", data, "-U", "postgres", "-A", "trust"],
                   check=True, capture_output=True)
    subprocess.run([_pg_bin("pg_ctl"), "-D", data, "-w", "-l", os.path.join(root, "log"),
                    "-o", f"-p {port} -k {root} -c listen_addresses=127.0.0.1", "start"],
                   check=True, capture_output=True)
    try:
        conn = psycopg2.connect(host="127.0.0.1", port=port, user="postgres", dbname="postgres")
        conn.autocommit = True
        conn.cursor().execute(DDL)
        conn.close()
        yield {"DB_HOST": "127.0.0.1", "DB_PORT": str(port), "DB_NAME": "postgres",
               "DB_USER": "postgres", "DB_PASSWORD": "", "DB_SCHEMA": SCHEMA}
    finally:
        subprocess.run([_pg_bin("pg_ctl"), "-D", data, "-m", "immediate", "stop"], capture_output=True)
        shutil.rmtree(root, ignore_errors=True)
