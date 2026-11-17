-- Local test schema. Mirrors virginia_dev_saayam_rdbms.
-- PostGIS is not available here, so geometry is stubbed as text and ST_AsText
-- is a pass-through. The production query text is therefore unchanged.
CREATE SCHEMA virginia_dev_saayam_rdbms;
SET search_path TO virginia_dev_saayam_rdbms, public;

CREATE DOMAIN public.geometry AS text;
CREATE FUNCTION public.st_astext(text) RETURNS text AS $$ SELECT $1 $$ LANGUAGE sql IMMUTABLE;

CREATE TABLE help_categories (
    cat_id varchar(50) PRIMARY KEY, cat_name varchar(100) NOT NULL,
    cat_desc varchar(150) NOT NULL, last_updated_at timestamp(6) DEFAULT (now() AT TIME ZONE 'UTC'));
CREATE TABLE request_for (
    req_for_id integer PRIMARY KEY, req_for varchar(25) NOT NULL,
    req_for_desc varchar(125), last_updated_at timestamp(6) DEFAULT (now() AT TIME ZONE 'UTC'));
CREATE TABLE request_isleadvol (
    req_islead_id integer PRIMARY KEY, req_islead varchar(15) NOT NULL,
    req_islead_desc varchar(100), last_updated_at timestamp(6) DEFAULT (now() AT TIME ZONE 'UTC'));
CREATE TABLE request_types (
    req_type_id integer PRIMARY KEY, req_type varchar(25),
    req_type_desc varchar(125), last_updated_at timestamp(6) DEFAULT (now() AT TIME ZONE 'UTC'));
CREATE TABLE request_priorities (
    req_priority_id integer PRIMARY KEY, req_priority varchar(25) NOT NULL,
    req_priority_desc varchar(125), last_updated_at timestamp(6) DEFAULT (now() AT TIME ZONE 'UTC'));
CREATE TABLE request_statuses (
    req_status_id integer PRIMARY KEY, req_status varchar(25) NOT NULL,
    req_status_desc varchar(125), last_updated_at timestamp(6) DEFAULT (now() AT TIME ZONE 'UTC'));
CREATE TABLE users (
    user_id varchar(255) PRIMARY KEY, last_updated_at timestamp(6) DEFAULT (now() AT TIME ZONE 'UTC'));

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
    req_loc public.geometry, created_loc public.geometry,
    iscalamity boolean, to_public boolean DEFAULT false,
    submission_date timestamp, serviced_date timestamp,
    last_updated_at timestamp(6) DEFAULT (now() AT TIME ZONE 'UTC'));

CREATE TABLE archive_watermark (
    source_table varchar(100) NOT NULL, stream varchar(50) NOT NULL,
    last_value_at timestamp(6), last_run_at timestamp(6),
    PRIMARY KEY (source_table, stream));
CREATE TABLE archive_run_log (
    run_id bigserial PRIMARY KEY, invocation_id varchar(100), source_table varchar(100),
    stream varchar(50), started_at timestamp(6), finished_at timestamp(6),
    range_from timestamp(6), range_to timestamp(6), s3_key varchar(500),
    source_rows bigint, rows_written bigint, bytes_written bigint,
    columns_dropped integer, columns_masked integer, status varchar(30),
    error_message text, triggered_by varchar(50));

-- lookups
INSERT INTO request_for VALUES (0,'SELF','For themselves'),(1,'OTHER','For someone else');
INSERT INTO request_isleadvol VALUES (0,'NO','Not lead'),(1,'YES','Is lead');
INSERT INTO request_types VALUES (0,'IN_PERSON','In person'),(1,'REMOTE','Remote');
INSERT INTO request_priorities VALUES (0,'LOW',''),(1,'MEDIUM',''),(2,'HIGH',''),(3,'CRITICAL','');
INSERT INTO request_statuses VALUES (0,'CREATED',''),(1,'MATCHING_VOLUNTEER',''),(2,'IN_PROGRESS',''),
  (3,'RESOLVED',''),(4,'CANCELLED',''),(5,'DELETED',''),(6,'RATED_BY_REQUESTER','');
INSERT INTO help_categories VALUES ('1','Food','Food help'),('1.3','Groceries','Grocery help'),('2','Housing','Housing help');
INSERT INTO users (user_id) SELECT 'SID-00-000-000-000-000-' || lpad(g::text,3,'0') FROM generate_series(1,20) g;
