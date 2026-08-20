\set ON_ERROR_STOP on
-- Local-only schema + seed data for developing/testing the Steward Dashboard
-- "Review Volunteers" API (steward_volunteer_review_api.py).
--
-- TEMPORARY FIXTURE -- the real `volunteers` table named in the ticket does not exist yet
-- and is expected to land separately. Until it does, this seeds `volunteer_applications`,
-- the only volunteer table with a status column. When the real table arrives, replace the
-- volunteer_applications DDL + seed below and retarget the VOLUNTEER SOURCE BINDING block
-- in steward_volunteer_review_api.py.
--
-- Sourced from the real sample data in this repo:
--   data-analytics/sql/users.csv                            (first 100 rows, real SID ids)
--   database/mock-data-generation/volunteer_applications.csv (all 100 rows)
--
-- WHY THE IDS ARE REMAPPED
-- The two CSVs cannot be joined as shipped. users.csv uses real ids in SID-00-000-000-058
-- format, but volunteer_applications.csv is produced by database/mock-data-generation/
-- utils.py, which generates ids as f"U{n}" -- U101 through U200. Loading both verbatim
-- gives a join that matches zero rows. This script maps the application rows positionally
-- onto the first 100 real users (U101 -> row 1, U102 -> row 2, ...), which is deterministic
-- and preserves the generator's original application_status distribution.
-- The real fix belongs in utils.py and is out of scope for this ticket.
--
-- The seeded fixture: 100 applications, 80 of them SUBMITTED or UNDER_REVIEW.
--
-- Safe to re-run: creates are guarded and inserts use ON CONFLICT DO NOTHING.

CREATE SCHEMA IF NOT EXISTS virginia_dev_saayam_rdbms;

-- application_status is a USER-DEFINED (enum) type in the real schema. Postgres has no
-- CREATE TYPE IF NOT EXISTS, so the usual idiom is a DO block that swallows duplicate_object.
-- Values come from STATUSES in database/mock-data-generation/utils.py.
DO $$
BEGIN
    CREATE TYPE virginia_dev_saayam_rdbms.application_status_enum AS ENUM (
        'DRAFT', 'IN_PROGRESS', 'SUBMITTED', 'UNDER_REVIEW', 'APPROVED'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END
$$;

-- NOTE: CREATE TABLE IF NOT EXISTS means "create it if the name is free", NOT "ensure it
-- looks like this". On a database where users already exists, everything below -- including
-- the PRIMARY KEY -- is silently skipped with only a NOTICE. That is exactly what happened
-- the first time this script was run, and it cascaded: no primary key meant the foreign key
-- below had nothing to reference, so volunteer_applications was never created and every
-- statement after it failed. The guarded ALTER further down is what actually fixes it.
CREATE TABLE IF NOT EXISTS virginia_dev_saayam_rdbms.users (
    user_id                           VARCHAR(255) PRIMARY KEY,
    state_id                          VARCHAR(50),
    country_id                        INTEGER,
    user_status_id                    BIGINT,
    user_category_id                  INTEGER,
    full_name                         VARCHAR(255),
    first_name                        VARCHAR(255),
    middle_name                       VARCHAR(255),
    last_name                         VARCHAR(255),
    primary_email_address             VARCHAR(255),
    primary_phone_number              VARCHAR(255),
    addr_ln1                          VARCHAR(255),
    addr_ln2                          VARCHAR(255),
    addr_ln3                          VARCHAR(255),
    city_name                         VARCHAR(255),
    zip_code                          VARCHAR(255),
    last_location                     VARCHAR(255),
    last_update_date                  TIMESTAMPTZ,
    time_zone                         VARCHAR(255),
    profile_picture_path              VARCHAR(255),
    gender                            VARCHAR(255),
    language_1                        VARCHAR(255),
    language_2                        VARCHAR(255),
    language_3                        VARCHAR(255),
    promotion_wizard_stage            INTEGER,
    promotion_wizard_last_update_date TIMESTAMPTZ,
    external_auth_provider            VARCHAR(20),
    dob                               DATE
);

-- Add the primary key if the table pre-existed without one. Safe to run: verified against
-- the local database that user_id is already unique (2911 rows / 2911 distinct / 0 nulls),
-- so this only formalizes a property the data already has. It also gives the join an index
-- to use -- there were previously no indexes on users at all.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'virginia_dev_saayam_rdbms.users'::regclass
           AND contype IN ('p', 'u')
    ) THEN
        ALTER TABLE virginia_dev_saayam_rdbms.users
            ADD CONSTRAINT users_pkey PRIMARY KEY (user_id);
        RAISE NOTICE 'Added missing PRIMARY KEY on users(user_id)';
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS virginia_dev_saayam_rdbms.volunteer_applications (
    user_id              VARCHAR(255) PRIMARY KEY
                         REFERENCES virginia_dev_saayam_rdbms.users(user_id),
    terms_and_conditions BOOLEAN,
    terms_accepted_at    TIMESTAMP,
    govt_id_path         TEXT,
    path_updated_at      TIMESTAMP,
    skill_codes          JSON,
    availability         JSONB,
    current_page         INTEGER,
    application_status   virginia_dev_saayam_rdbms.application_status_enum,
    is_completed         BOOLEAN,
    created_at           TIMESTAMP,
    last_updated_at      TIMESTAMP
);

-- The API filters on application_status and sorts by last_updated_at DESC, so this index
-- covers the exact access pattern.
CREATE INDEX IF NOT EXISTS idx_volunteer_applications_status_updated
    ON virginia_dev_saayam_rdbms.volunteer_applications (application_status, last_updated_at DESC);


-- 100 real user ids from users.csv.
-- Only user_id is seeded, deliberately. This script has to run against databases where
-- users already exists with a schema we do not control, so listing all 28 columns would
-- break the moment one of them is missing. The API only ever selects u.user_id, and on a
-- database that already has these users this whole statement is a no-op anyway.
INSERT INTO virginia_dev_saayam_rdbms.users (user_id) VALUES
    ('SID-00-000-000-058'),
    ('SID-00-000-000-060'),
    ('SID-00-000-000-061'),
    ('SID-00-000-000-078'),
    ('SID-00-000-000-079'),
    ('SID-00-000-000-080'),
    ('SID-00-000-000-081'),
    ('SID-00-000-000-082'),
    ('SID-00-000-000-083'),
    ('SID-00-000-000-084'),
    ('SID-00-000-000-085'),
    ('SID-00-000-000-086'),
    ('SID-00-000-000-087'),
    ('SID-00-000-000-088'),
    ('SID-00-000-000-090'),
    ('SID-00-000-000-091'),
    ('SID-00-000-000-092'),
    ('SID-00-000-000-093'),
    ('SID-00-000-000-094'),
    ('SID-00-000-000-095'),
    ('SID-00-000-000-096'),
    ('SID-00-000-000-300'),
    ('SID-00-000-000-097'),
    ('SID-00-000-000-098'),
    ('SID-00-000-000-099'),
    ('SID-00-000-000-100'),
    ('SID-00-000-000-101'),
    ('SID-00-000-000-307'),
    ('SID-00-000-000-308'),
    ('SID-00-000-000-309'),
    ('SID-00-000-000-310'),
    ('SID-00-000-000-311'),
    ('SID-00-000-000-312'),
    ('SID-00-000-000-333'),
    ('SID-00-000-000-340'),
    ('SID-00-000-000-348'),
    ('SID-00-000-000-357'),
    ('SID-00-000-000-364'),
    ('SID-00-000-000-371'),
    ('SID-00-000-000-383'),
    ('SID-00-000-000-391'),
    ('SID-00-000-000-103'),
    ('SID-00-000-000-104'),
    ('SID-00-000-000-105'),
    ('SID-00-000-000-106'),
    ('SID-00-000-000-107'),
    ('SID-00-000-000-108'),
    ('SID-00-000-000-109'),
    ('SID-00-000-000-110'),
    ('SID-00-000-000-111'),
    ('SID-00-000-000-089'),
    ('SID-00-000-000-112'),
    ('SID-00-000-000-428'),
    ('SID-00-000-000-113'),
    ('SID-00-000-000-114'),
    ('SID-00-000-000-115'),
    ('SID-00-000-000-116'),
    ('SID-00-000-000-117'),
    ('SID-00-000-000-118'),
    ('SID-00-000-000-119'),
    ('SID-00-000-000-120'),
    ('SID-00-000-000-121'),
    ('SID-00-000-000-122'),
    ('SID-00-000-000-123'),
    ('SID-00-000-000-124'),
    ('SID-00-000-000-125'),
    ('SID-00-000-000-126'),
    ('SID-00-000-000-127'),
    ('SID-00-000-000-129'),
    ('SID-00-000-000-130'),
    ('SID-00-000-000-131'),
    ('SID-00-000-000-132'),
    ('SID-00-000-000-133'),
    ('SID-00-000-000-134'),
    ('SID-00-000-000-135'),
    ('SID-00-000-000-136'),
    ('SID-00-000-000-137'),
    ('SID-00-000-000-138'),
    ('SID-00-000-000-139'),
    ('SID-00-000-000-140'),
    ('SID-00-000-000-141'),
    ('SID-00-000-000-142'),
    ('SID-00-000-000-143'),
    ('SID-00-000-000-144'),
    ('SID-00-000-000-145'),
    ('SID-00-000-000-146'),
    ('SID-00-000-000-147'),
    ('SID-00-000-000-148'),
    ('SID-00-000-000-149'),
    ('SID-00-000-000-150'),
    ('SID-00-000-000-151'),
    ('SID-00-000-000-152'),
    ('SID-00-000-000-153'),
    ('SID-00-000-000-154'),
    ('SID-00-000-000-155'),
    ('SID-00-000-000-156'),
    ('SID-00-000-000-157'),
    ('SID-00-000-000-158'),
    ('SID-00-000-000-159'),
    ('SID-00-000-000-160')
ON CONFLICT (user_id) DO NOTHING;


-- 100 volunteer applications, ids remapped onto the users above
INSERT INTO virginia_dev_saayam_rdbms.volunteer_applications (user_id, terms_and_conditions, terms_accepted_at, govt_id_path, path_updated_at, skill_codes, availability, current_page, application_status, is_completed, created_at, last_updated_at) VALUES
    ('SID-00-000-000-058', TRUE, '2026-01-06 11:03', '/uploads/id/U101.pdf', '2026-01-06 12:00', '["2.4","6"]', '{"weekdays":"evening"}', 1, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, FALSE, '2026-01-06 10:01', '2026-01-07 15:14'),
    ('SID-00-000-000-060', TRUE, '2026-01-06 15:04', '/uploads/id/U102.pdf', '2026-01-06 16:51', '["5.1.2","6.6"]', '{"weekdays":"afternoon"}', 2, 'APPROVED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-01-06 12:45', '2026-01-12 22:08'),
    ('SID-00-000-000-061', TRUE, '2026-01-04 14:30', '/uploads/id/U103.pdf', '2026-01-04 16:01', '["6.8","3.5","1.3.2"]', '{"weekdays":["monday_evening","wednesday_evening"]}', 4, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-01-04 14:06', '2026-01-06 00:19'),
    ('SID-00-000-000-078', TRUE, '2026-01-08 15:34', '/uploads/id/U104.pdf', '2026-01-08 16:32', '["2.1","3.3.7","2.3"]', '{"weekends":"full_day"}', 3, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-01-08 12:45', '2026-01-10 21:54'),
    ('SID-00-000-000-079', TRUE, '2026-01-10 16:29', '/uploads/id/U105.pdf', '2026-01-10 16:47', '["3.3.11","5.5","3.3.9","3.3.10"]', '{"weekdays":"evening"}', 2, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-01-10 13:44', '2026-01-20 22:40'),
    ('SID-00-000-000-080', TRUE, '2026-01-07 10:59', '/uploads/id/U106.pdf', '2026-01-07 11:15', '["6.3","4.2"]', '{"weekends":"full_day"}', 4, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-01-07 09:51', '2026-01-09 15:23'),
    ('SID-00-000-000-081', TRUE, '2026-01-12 20:03', '/uploads/id/U107.pdf', '2026-01-12 21:52', '["4.7","4.3.5","3.3.6","3.2"]', '{"weekdays":"afternoon"}', 1, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-01-12 17:34', '2026-01-14 00:32'),
    ('SID-00-000-000-082', TRUE, '2026-01-13 17:15', '/uploads/id/U108.pdf', '2026-01-13 19:47', '["5.4","3.4","6.1"]', '{"weekends":"morning","weekdays":"evening"}', 1, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-01-13 15:38', '2026-01-24 04:35'),
    ('SID-00-000-000-083', TRUE, '2026-01-14 14:47', '/uploads/id/U109.pdf', '2026-01-14 16:43', '["3.5","5.1.9"]', '{"weekends":"full_day"}', 1, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-01-14 14:07', '2026-01-24 21:36'),
    ('SID-00-000-000-084', TRUE, '2026-01-11 17:03', '/uploads/id/U110.pdf', '2026-01-11 20:58', '["6.7","4.3"]', '{"weekends":"full_day"}', 3, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-01-11 14:48', '2026-01-16 00:01'),
    ('SID-00-000-000-085', TRUE, '2026-01-15 10:22', '/uploads/id/U111.pdf', '2026-01-15 13:36', '["3.10","5.1.5","6.1","3.3.11"]', '{"weekends":"full_day"}', 4, 'APPROVED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-01-15 10:05', '2026-01-18 22:24'),
    ('SID-00-000-000-086', TRUE, '2026-01-17 16:11', '/uploads/id/U112.pdf', '2026-01-17 17:46', '["5.3","5.1.2","3.1"]', '{"weekends":"full_day"}', 1, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-01-17 13:25', '2026-01-27 02:00'),
    ('SID-00-000-000-087', TRUE, '2026-01-13 11:43', '/uploads/id/U113.pdf', '2026-01-13 12:00', '["4.3.1","2"]', '{"weekdays":"flexible","weekends":"partial"}', 4, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-01-13 10:45', '2026-01-16 20:08'),
    ('SID-00-000-000-088', TRUE, '2026-01-15 17:15', '/uploads/id/U114.pdf', '2026-01-15 17:39', '["5.1.10","4.3.4","5.1.1","5"]', '{"weekdays":["monday_evening","wednesday_evening"]}', 1, 'UNDER_REVIEW'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-01-15 16:51', '2026-01-16 00:25'),
    ('SID-00-000-000-090', TRUE, '2026-01-15 14:06', '/uploads/id/U115.pdf', '2026-01-15 14:41', '["3.3.13","3.7","5.1.4"]', '{"weekdays":"evening"}', 4, 'APPROVED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-01-15 12:12', '2026-01-23 15:44'),
    ('SID-00-000-000-091', TRUE, '2026-01-16 14:13', '/uploads/id/U116.pdf', '2026-01-16 15:07', '["1.3.4","3.3.11","4.4"]', '{"weekdays":"flexible","weekends":"partial"}', 4, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, FALSE, '2026-01-16 12:10', '2026-01-20 21:51'),
    ('SID-00-000-000-092', TRUE, '2026-01-18 12:32', '/uploads/id/U117.pdf', '2026-01-18 15:00', '["6","1.3.4","4.2","1.3.3"]', '{"weekdays":"afternoon"}', 2, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-01-18 12:18', '2026-01-18 23:05'),
    ('SID-00-000-000-093', TRUE, '2026-01-18 12:26', '/uploads/id/U118.pdf', '2026-01-18 12:56', '["3.3.9","6.5","6.7","1.3.2"]', '{"weekdays":["monday_evening","wednesday_evening"]}', 3, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-01-18 10:43', '2026-01-22 16:38'),
    ('SID-00-000-000-094', TRUE, '2026-01-20 16:10', '/uploads/id/U119.pdf', '2026-01-20 17:26', '["4.2","2","1.1"]', '{"weekends":"morning","weekdays":"evening"}', 1, 'APPROVED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-01-20 13:25', '2026-01-22 01:39'),
    ('SID-00-000-000-095', TRUE, '2026-01-21 15:58', '/uploads/id/U120.pdf', '2026-01-21 17:32', '["3.3.10","5.1.11","6"]', '{"weekdays":"morning"}', 1, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-01-21 14:56', '2026-02-01 01:51'),
    ('SID-00-000-000-096', TRUE, '2026-01-22 15:28', '/uploads/id/U121.pdf', '2026-01-22 16:07', '["3.8","6.8","3.3.4"]', '{"weekdays":"evening"}', 3, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-01-22 13:07', '2026-01-30 23:23'),
    ('SID-00-000-000-300', TRUE, '2026-01-22 15:53', '/uploads/id/U122.pdf', '2026-01-22 17:18', '["3.5","3.3.10"]', '{"weekdays":"morning"}', 4, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-01-22 15:53', '2026-01-30 17:25'),
    ('SID-00-000-000-097', TRUE, '2026-01-28 13:08', '/uploads/id/U123.pdf', '2026-01-28 15:37', '["3.3","5.1.10","3.10","1.3.2"]', '{"weekends":"full_day"}', 1, 'APPROVED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-01-28 11:34', '2026-02-02 19:20'),
    ('SID-00-000-000-098', TRUE, '2026-01-29 12:06', '/uploads/id/U124.pdf', '2026-01-29 14:44', '["3.3.1","3.3.8","3.3.10","3.3.12"]', '{"weekends":"full_day"}', 3, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-01-29 10:22', '2026-02-05 03:26'),
    ('SID-00-000-000-099', TRUE, '2026-01-27 13:27', '/uploads/id/U125.pdf', '2026-01-27 17:10', '["5.1.5","3.3.6"]', '{"weekends":"full_day"}', 3, 'APPROVED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-01-27 11:50', '2026-02-01 06:05'),
    ('SID-00-000-000-100', TRUE, '2026-01-27 11:06', '/uploads/id/U126.pdf', '2026-01-27 12:17', '["3.7","4.3.3"]', '{"weekends":"morning","weekdays":"evening"}', 3, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-01-27 09:42', '2026-01-27 14:13'),
    ('SID-00-000-000-101', TRUE, '2026-01-28 14:53', '/uploads/id/U127.pdf', '2026-01-28 16:21', '["4.2","5.1.10","6.8","5.2"]', '{"weekdays":["tuesday_morning","thursday_afternoon"]}', 2, 'UNDER_REVIEW'::virginia_dev_saayam_rdbms.application_status_enum, FALSE, '2026-01-28 13:02', '2026-02-01 17:06'),
    ('SID-00-000-000-307', TRUE, '2026-01-28 20:54', '/uploads/id/U128.pdf', '2026-01-28 23:58', '["3.3.3","4.3.5","5.1.10","1.3.5"]', '{"weekends":"morning","weekdays":"evening"}', 3, 'APPROVED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-01-28 17:59', '2026-02-08 01:44'),
    ('SID-00-000-000-308', TRUE, '2026-02-02 15:25', '/uploads/id/U129.pdf', '2026-02-02 18:23', '["6.1","3.10","3.3.2"]', '{"weekdays":["tuesday_morning","thursday_afternoon"]}', 2, 'APPROVED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-02-02 13:42', '2026-02-12 03:42'),
    ('SID-00-000-000-309', TRUE, '2026-02-03 11:09', '/uploads/id/U130.pdf', '2026-02-03 14:30', '["6.8","4.3","5.1.4","5.1.11"]', '{"weekends":"morning","weekdays":"evening"}', 4, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-02-03 09:19', '2026-02-06 00:35'),
    ('SID-00-000-000-310', TRUE, '2026-02-04 15:05', '/uploads/id/U131.pdf', '2026-02-04 17:57', '["3.3.6","3.3.3","3.3"]', '{"weekdays":"flexible","weekends":"partial"}', 4, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, FALSE, '2026-02-04 14:05', '2026-02-14 06:01'),
    ('SID-00-000-000-311', TRUE, '2026-02-04 14:51', '/uploads/id/U132.pdf', '2026-02-04 16:33', '["3.3","1"]', '{"weekdays":"flexible","weekends":"partial"}', 1, 'APPROVED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-02-04 12:45', '2026-02-10 19:44'),
    ('SID-00-000-000-312', TRUE, '2026-02-02 17:46', '/uploads/id/U133.pdf', '2026-02-02 19:42', '["5.1.4","5.4"]', '{"weekdays":["tuesday_morning","thursday_afternoon"]}', 4, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-02-02 17:15', '2026-02-12 07:39'),
    ('SID-00-000-000-333', TRUE, '2026-02-07 18:58', '/uploads/id/U134.pdf', '2026-02-07 20:53', '["3.3.9","3.7","5.3"]', '{"weekends":"full_day"}', 4, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-02-07 16:57', '2026-02-09 08:11'),
    ('SID-00-000-000-340', TRUE, '2026-02-06 14:40', '/uploads/id/U135.pdf', '2026-02-06 15:15', '["3.3.7","4.5"]', '{"weekdays":"flexible","weekends":"partial"}', 1, 'UNDER_REVIEW'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-02-06 14:20', '2026-02-12 21:36'),
    ('SID-00-000-000-348', TRUE, '2026-02-08 10:52', '/uploads/id/U136.pdf', '2026-02-08 14:43', '["1.2","6.4","4.4","5.1.6"]', '{"weekends":"full_day"}', 4, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, FALSE, '2026-02-08 09:13', '2026-02-14 23:30'),
    ('SID-00-000-000-357', TRUE, '2026-02-09 12:24', '/uploads/id/U137.pdf', '2026-02-09 14:03', '["4.7","3.3.11","5.1.4"]', '{"weekdays":"evening"}', 1, 'APPROVED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-02-09 12:17', '2026-02-15 23:39'),
    ('SID-00-000-000-364', TRUE, '2026-02-07 15:54', '/uploads/id/U138.pdf', '2026-02-07 16:06', '["4.4","4.3","3.3.5"]', '{"weekdays":["tuesday_morning","thursday_afternoon"]}', 4, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-02-07 15:08', '2026-02-12 04:59'),
    ('SID-00-000-000-371', FALSE, NULL, '/uploads/id/U139.pdf', '2026-02-10 12:48', '["4.3.3","3.3.6"]', '{"weekdays":"evening"}', 1, 'UNDER_REVIEW'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-02-10 10:30', '2026-02-10 16:00'),
    ('SID-00-000-000-383', TRUE, '2026-02-13 14:06', '/uploads/id/U140.pdf', '2026-02-13 14:35', '["3.3.5","5.1.4","3.4","4.3.6"]', '{"weekdays":"evening"}', 1, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, FALSE, '2026-02-13 11:15', '2026-02-15 18:41'),
    ('SID-00-000-000-391', TRUE, '2026-02-12 16:15', '/uploads/id/U141.pdf', '2026-02-12 16:34', '["3.3.9","2.4","4","6.7"]', '{"weekdays":["monday_evening","wednesday_evening"]}', 1, 'UNDER_REVIEW'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-02-12 15:25', '2026-02-18 01:01'),
    ('SID-00-000-000-103', TRUE, '2026-02-11 19:28', '/uploads/id/U142.pdf', '2026-02-11 22:58', '["2.4","5.1.10","4.3.5"]', '{"weekends":"morning","weekdays":"evening"}', 2, 'APPROVED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-02-11 17:41', '2026-02-18 01:44'),
    ('SID-00-000-000-104', TRUE, '2026-02-16 19:40', '/uploads/id/U143.pdf', '2026-02-16 23:11', '["6.6","3.6","4.3","3.3.9"]', '{"weekdays":["tuesday_morning","thursday_afternoon"]}', 4, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-02-16 17:49', '2026-02-20 11:40'),
    ('SID-00-000-000-105', TRUE, '2026-02-15 10:17', '/uploads/id/U144.pdf', '2026-02-15 12:21', '["4.3.4","3.5"]', '{"weekends":"full_day"}', 3, 'APPROVED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-02-15 09:31', '2026-02-23 12:54'),
    ('SID-00-000-000-106', TRUE, '2026-02-14 15:08', '/uploads/id/U145.pdf', '2026-02-14 18:22', '["5.1.5","5.1.7"]', '{"weekends":"full_day"}', 3, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-02-14 12:46', '2026-02-18 01:06'),
    ('SID-00-000-000-107', TRUE, '2026-02-17 15:58', '/uploads/id/U146.pdf', '2026-02-17 17:46', '["6.1","4.3.1","4.3.4","5.1.3"]', '{"weekdays":"afternoon"}', 1, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-02-17 14:30', '2026-02-20 22:53'),
    ('SID-00-000-000-108', TRUE, '2026-02-17 15:17', '/uploads/id/U147.pdf', '2026-02-17 18:31', '["6.7","3.8","2.3","3.3.2"]', '{"weekdays":"afternoon"}', 3, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-02-17 12:47', '2026-02-18 06:05'),
    ('SID-00-000-000-109', TRUE, '2026-02-19 12:01', '/uploads/id/U148.pdf', '2026-02-19 12:33', '["5.1.7","2.4","1.1","6.4"]', '{"weekdays":"flexible","weekends":"partial"}', 3, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-02-19 09:03', '2026-02-21 12:49'),
    ('SID-00-000-000-110', TRUE, '2026-02-18 12:52', '/uploads/id/U149.pdf', '2026-02-18 15:33', '["1.3.3","3.3.1","6.3","4"]', '{"weekends":"full_day"}', 5, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, FALSE, '2026-02-18 10:25', '2026-02-25 01:11'),
    ('SID-00-000-000-111', TRUE, '2026-02-23 16:44', '/uploads/id/U150.pdf', '2026-02-23 20:24', '["5.1.1","4.1","6.3","1.3.4"]', '{"weekdays":"morning"}', 2, 'UNDER_REVIEW'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-02-23 15:28', '2026-03-05 23:40'),
    ('SID-00-000-000-089', TRUE, '2026-02-21 12:51', '/uploads/id/U151.pdf', '2026-02-21 12:51', '["5.1.2","6.7","5.1.5"]', '{"weekends":"full_day"}', 3, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-02-21 12:11', '2026-02-28 14:34'),
    ('SID-00-000-000-112', TRUE, '2026-02-23 13:24', '/uploads/id/U152.pdf', '2026-02-23 16:09', '["3.6","3.3"]', '{"weekends":"morning","weekdays":"evening"}', 3, 'IN_PROGRESS'::virginia_dev_saayam_rdbms.application_status_enum, FALSE, '2026-02-23 12:27', '2026-03-05 04:01'),
    ('SID-00-000-000-428', TRUE, '2026-02-25 13:28', '/uploads/id/U153.pdf', '2026-02-25 15:11', '["5.1.9","6","5.1.8"]', '{"weekdays":"evening"}', 4, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-02-25 10:29', '2026-03-03 00:27'),
    ('SID-00-000-000-113', TRUE, '2026-02-23 15:10', '/uploads/id/U154.pdf', '2026-02-23 17:40', '["3.6","6.4"]', '{"weekends":"morning","weekdays":"evening"}', 4, 'UNDER_REVIEW'::virginia_dev_saayam_rdbms.application_status_enum, FALSE, '2026-02-23 12:43', '2026-03-04 04:08'),
    ('SID-00-000-000-114', TRUE, '2026-02-25 16:03', '/uploads/id/U155.pdf', '2026-02-25 18:03', '["5","4.3.1","4.3"]', '{"weekends":"morning","weekdays":"evening"}', 3, 'APPROVED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-02-25 15:40', '2026-03-04 05:34'),
    ('SID-00-000-000-115', TRUE, '2026-03-02 16:01', '/uploads/id/U156.pdf', '2026-03-02 17:57', '["4.2","3.4"]', '{"weekdays":"flexible","weekends":"partial"}', 4, 'APPROVED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-02 15:52', '2026-03-10 18:39'),
    ('SID-00-000-000-116', TRUE, '2026-03-01 11:51', '/uploads/id/U157.pdf', '2026-03-01 15:04', '["5.1.11","1.3.3","3.3.4"]', '{"weekdays":"morning"}', 3, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-01 09:12', '2026-03-09 02:35'),
    ('SID-00-000-000-117', TRUE, '2026-02-27 15:06', '/uploads/id/U158.pdf', '2026-02-27 15:09', '["5","2.2","3.3.6","3"]', '{"weekends":"morning","weekdays":"evening"}', 2, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-02-27 12:45', '2026-03-07 02:27'),
    ('SID-00-000-000-118', TRUE, '2026-03-03 18:51', '/uploads/id/U159.pdf', '2026-03-03 19:28', '["3.3.2","6.7","5.2"]', '{"weekdays":["tuesday_morning","thursday_afternoon"]}', 1, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-03 16:30', '2026-03-08 08:18'),
    ('SID-00-000-000-119', TRUE, '2026-03-03 18:29', '/uploads/id/U160.pdf', '2026-03-03 21:34', '["6.6","6.5","5.1.7"]', '{"weekdays":["tuesday_morning","thursday_afternoon"]}', 4, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-03 17:17', '2026-03-09 03:09'),
    ('SID-00-000-000-120', TRUE, '2026-03-05 17:53', '/uploads/id/U161.pdf', '2026-03-05 18:54', '["4.5","3.3.7","5","1.3.2"]', '{"weekdays":"afternoon"}', 4, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-05 14:55', '2026-03-12 05:44'),
    ('SID-00-000-000-121', TRUE, '2026-03-06 11:39', '/uploads/id/U162.pdf', '2026-03-06 13:03', '["5.1.11","2.3"]', '{"weekdays":"morning"}', 2, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-06 09:08', '2026-03-12 23:12'),
    ('SID-00-000-000-122', TRUE, '2026-03-07 15:02', '/uploads/id/U163.pdf', '2026-03-07 17:48', '["4.3.1","5.5"]', '{"weekdays":"morning"}', 4, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-07 13:21', '2026-03-15 18:27'),
    ('SID-00-000-000-123', TRUE, '2026-03-06 15:05', '/uploads/id/U164.pdf', '2026-03-06 15:30', '["2.3","5.1.11","3.3.11","4"]', '{"weekdays":["tuesday_morning","thursday_afternoon"]}', 1, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-06 13:14', '2026-03-10 20:53'),
    ('SID-00-000-000-124', TRUE, '2026-03-07 15:27', '/uploads/id/U165.pdf', '2026-03-07 18:49', '["3.3.11","3.3.12"]', '{"weekdays":"afternoon"}', 5, 'UNDER_REVIEW'::virginia_dev_saayam_rdbms.application_status_enum, FALSE, '2026-03-07 12:33', '2026-03-17 22:20'),
    ('SID-00-000-000-125', TRUE, '2026-03-08 17:45', '/uploads/id/U166.pdf', '2026-03-08 20:35', '["5.1.4","3.8"]', '{"weekdays":["tuesday_morning","thursday_afternoon"]}', 4, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-08 16:40', '2026-03-14 05:54'),
    ('SID-00-000-000-126', TRUE, '2026-03-13 14:19', '/uploads/id/U167.pdf', '2026-03-13 15:57', '["2.4","3.3.8","4.4"]', '{"weekends":"morning","weekdays":"evening"}', 3, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-13 13:29', '2026-03-14 02:22'),
    ('SID-00-000-000-127', TRUE, '2026-03-09 12:05', '/uploads/id/U168.pdf', '2026-03-09 15:38', '["3.3.7","6.8","4.3.4"]', '{"weekdays":"afternoon"}', 3, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-09 09:58', '2026-03-20 04:24'),
    ('SID-00-000-000-129', TRUE, '2026-03-15 11:07', '/uploads/id/U169.pdf', '2026-03-15 12:26', '["1.3.1","6.5","4.3.5"]', '{"weekdays":"afternoon"}', 3, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-15 10:57', '2026-03-20 23:52'),
    ('SID-00-000-000-130', TRUE, '2026-03-12 13:23', '/uploads/id/U170.pdf', '2026-03-12 15:38', '["3.6","3.3.11","3.4","5.1.6"]', '{"weekdays":"afternoon"}', 3, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-12 11:50', '2026-03-13 22:42'),
    ('SID-00-000-000-131', TRUE, '2026-03-13 17:27', '/uploads/id/U171.pdf', '2026-03-13 17:50', '["1.1","3.5","5.5"]', '{"weekdays":["monday_evening","wednesday_evening"]}', 3, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, FALSE, '2026-03-13 15:54', '2026-03-23 00:42'),
    ('SID-00-000-000-132', FALSE, NULL, '/uploads/id/U172.pdf', '2026-03-13 16:16', '["4.3","6.9","3.3.6","1.3.5"]', '{"weekdays":"afternoon"}', 3, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-13 12:30', '2026-03-23 22:23'),
    ('SID-00-000-000-133', TRUE, '2026-03-14 09:48', '/uploads/id/U173.pdf', '2026-03-14 10:12', '["5.5","3.2"]', '{"weekdays":"afternoon"}', 4, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-14 09:19', '2026-03-23 21:58'),
    ('SID-00-000-000-134', TRUE, '2026-03-18 12:37', '/uploads/id/U174.pdf', '2026-03-18 16:37', '["1.3.1","4.3.6","3.3.5"]', '{"weekdays":["monday_evening","wednesday_evening"]}', 3, 'APPROVED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-18 10:53', '2026-03-20 03:00'),
    ('SID-00-000-000-135', TRUE, '2026-03-16 15:48', '/uploads/id/U175.pdf', '2026-03-16 19:25', '["2.2","3.3.5","6.7"]', '{"weekends":"full_day"}', 3, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-16 15:17', '2026-03-19 22:15'),
    ('SID-00-000-000-136', TRUE, '2026-03-17 18:12', '/uploads/id/U176.pdf', '2026-03-17 19:36', '["6.7","1"]', '{"weekdays":"afternoon"}', 2, 'APPROVED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-17 17:13', '2026-03-26 00:27'),
    ('SID-00-000-000-137', FALSE, NULL, '/uploads/id/U177.pdf', '2026-03-18 12:30', '["6.6","4.3"]', '{"weekdays":"morning"}', 2, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, FALSE, '2026-03-18 09:08', '2026-03-24 20:37'),
    ('SID-00-000-000-138', TRUE, '2026-03-22 19:20', '/uploads/id/U178.pdf', '2026-03-22 19:47', '["5.1.9","3.3.6","6.9"]', '{"weekdays":"evening"}', 5, 'UNDER_REVIEW'::virginia_dev_saayam_rdbms.application_status_enum, FALSE, '2026-03-22 16:49', '2026-03-27 03:28'),
    ('SID-00-000-000-139', TRUE, '2026-03-20 19:49', '/uploads/id/U179.pdf', '2026-03-20 20:16', '["5.1.11","2","2.1"]', '{"weekdays":["monday_evening","wednesday_evening"]}', 2, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-20 16:54', '2026-03-25 05:56'),
    ('SID-00-000-000-140', TRUE, '2026-03-24 19:52', '/uploads/id/U180.pdf', '2026-03-24 21:42', '["3","6.1"]', '{"weekdays":"flexible","weekends":"partial"}', 4, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-24 17:18', '2026-03-28 04:03'),
    ('SID-00-000-000-141', TRUE, '2026-03-25 17:35', '/uploads/id/U181.pdf', '2026-03-25 18:55', '["3.4","4.3.6","3.3.1","5.1.5"]', '{"weekdays":["monday_evening","wednesday_evening"]}', 1, 'UNDER_REVIEW'::virginia_dev_saayam_rdbms.application_status_enum, FALSE, '2026-03-25 15:46', '2026-03-31 20:42'),
    ('SID-00-000-000-142', TRUE, '2026-03-24 19:26', '/uploads/id/U182.pdf', '2026-03-24 21:49', '["3.1","5","4.3.4"]', '{"weekends":"morning","weekdays":"evening"}', 4, 'APPROVED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-24 17:03', '2026-03-25 02:27'),
    ('SID-00-000-000-143', TRUE, '2026-03-26 11:15', '/uploads/id/U183.pdf', '2026-03-26 14:03', '["3.3.6","2.4","4.3.3"]', '{"weekdays":["tuesday_morning","thursday_afternoon"]}', 3, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-26 10:36', '2026-04-04 17:54'),
    ('SID-00-000-000-144', TRUE, '2026-03-29 19:49', '/uploads/id/U184.pdf', '2026-03-29 23:21', '["3.6","1.3","3.3.13","4.1"]', '{"weekdays":["tuesday_morning","thursday_afternoon"]}', 2, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-29 17:01', '2026-04-01 09:03'),
    ('SID-00-000-000-145', TRUE, '2026-03-26 11:54', '/uploads/id/U185.pdf', '2026-03-26 12:17', '["5.4","3.3.5","4.4","5.1"]', '{"weekdays":"morning"}', 3, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-26 11:47', '2026-04-01 00:53'),
    ('SID-00-000-000-146', TRUE, '2026-03-27 11:22', '/uploads/id/U186.pdf', '2026-03-27 14:14', '["3.6","5.1.11"]', '{"weekdays":"morning"}', 4, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-27 11:10', '2026-04-02 18:27'),
    ('SID-00-000-000-147', TRUE, '2026-03-30 18:00', '/uploads/id/U187.pdf', '2026-03-30 20:31', '["5.4","4.1","1.3.2"]', '{"weekends":"full_day"}', 1, 'APPROVED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-30 15:07', '2026-03-30 23:50'),
    ('SID-00-000-000-148', TRUE, '2026-03-30 13:19', '/uploads/id/U188.pdf', '2026-03-30 15:26', '["5.1.10","3.3.12","3.10","4.4"]', '{"weekdays":"evening"}', 3, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-03-30 13:18', '2026-03-31 22:21'),
    ('SID-00-000-000-149', TRUE, '2026-04-02 10:49', '/uploads/id/U189.pdf', '2026-04-02 13:16', '["6.4","4.7","5.1"]', '{"weekdays":"flexible","weekends":"partial"}', 3, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-04-02 09:29', '2026-04-05 01:55'),
    ('SID-00-000-000-150', TRUE, '2026-04-05 14:32', '/uploads/id/U190.pdf', '2026-04-05 15:34', '["6.6","4.7","5.4"]', '{"weekdays":"afternoon"}', 3, 'UNDER_REVIEW'::virginia_dev_saayam_rdbms.application_status_enum, FALSE, '2026-04-05 14:05', '2026-04-08 21:23'),
    ('SID-00-000-000-151', TRUE, '2026-04-01 19:50', '/uploads/id/U191.pdf', '2026-04-01 20:39', '["4.3.3","3.3","3.3.8"]', '{"weekdays":"morning"}', 2, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, FALSE, '2026-04-01 17:40', '2026-04-10 23:27'),
    ('SID-00-000-000-152', TRUE, '2026-04-03 18:57', '/uploads/id/U192.pdf', '2026-04-03 20:51', '["6.3","4.3","4.2","3.3.1"]', '{"weekdays":["monday_evening","wednesday_evening"]}', 3, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-04-03 16:29', '2026-04-08 05:54'),
    ('SID-00-000-000-153', TRUE, '2026-04-07 10:28', '/uploads/id/U193.pdf', '2026-04-07 10:42', '["3.8","2","2.2"]', '{"weekdays":"evening"}', 4, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-04-07 10:19', '2026-04-16 19:32'),
    ('SID-00-000-000-154', TRUE, '2026-04-07 14:28', '/uploads/id/U194.pdf', '2026-04-07 15:06', '["5.1.2","2.4"]', '{"weekdays":"evening"}', 1, 'APPROVED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-04-07 12:20', '2026-04-16 01:17'),
    ('SID-00-000-000-155', TRUE, '2026-04-06 19:04', '/uploads/id/U195.pdf', '2026-04-06 19:44', '["4.3.6","3.8","4.5"]', '{"weekdays":"morning"}', 1, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-04-06 16:28', '2026-04-17 06:05'),
    ('SID-00-000-000-156', TRUE, '2026-04-08 11:47', '/uploads/id/U196.pdf', '2026-04-08 12:51', '["6.8","3.3.1","4.3.1","2.1"]', '{"weekdays":["tuesday_morning","thursday_afternoon"]}', 3, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-04-08 10:35', '2026-04-12 23:35'),
    ('SID-00-000-000-157', TRUE, '2026-04-08 13:03', '/uploads/id/U197.pdf', '2026-04-08 16:25', '["3.10","5.4","2.2"]', '{"weekdays":"afternoon"}', 3, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-04-08 10:19', '2026-04-08 21:44'),
    ('SID-00-000-000-158', TRUE, '2026-04-09 15:46', '/uploads/id/U198.pdf', '2026-04-09 16:21', '["2","3.9"]', '{"weekdays":"afternoon"}', 1, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-04-09 14:49', '2026-04-19 22:17'),
    ('SID-00-000-000-159', TRUE, '2026-04-13 18:06', '/uploads/id/U199.pdf', '2026-04-13 21:23', '["3.3.11","5.1.11","1.3.2","5"]', '{"weekdays":"flexible","weekends":"partial"}', 4, 'UNDER_REVIEW'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-04-13 15:09', '2026-04-23 02:11'),
    ('SID-00-000-000-160', TRUE, '2026-04-11 19:15', '/uploads/id/U200.pdf', '2026-04-11 23:06', '["4.3.6","6.4"]', '{"weekdays":["tuesday_morning","thursday_afternoon"]}', 3, 'SUBMITTED'::virginia_dev_saayam_rdbms.application_status_enum, TRUE, '2026-04-11 17:15', '2026-04-18 07:39')
ON CONFLICT (user_id) DO NOTHING;


-- Sanity checks -- both should print non-zero, and the join count should be 100.
-- A zero join count is the exact symptom the id remap above exists to prevent.
SELECT COUNT(*) AS seeded_users FROM virginia_dev_saayam_rdbms.users;
SELECT COUNT(*) AS seeded_applications FROM virginia_dev_saayam_rdbms.volunteer_applications;
SELECT COUNT(*) AS joinable_rows
  FROM virginia_dev_saayam_rdbms.volunteer_applications va
  JOIN virginia_dev_saayam_rdbms.users u ON u.user_id = va.user_id;
SELECT application_status, COUNT(*)
  FROM virginia_dev_saayam_rdbms.volunteer_applications
 GROUP BY application_status ORDER BY 2 DESC;
