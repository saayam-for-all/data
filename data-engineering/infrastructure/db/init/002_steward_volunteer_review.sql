-- Local dev seed for the Steward Volunteer Review API (issue #273).
--
-- volunteer_applications columns (user_id, application_status,
-- last_updated_at, etc.) are confirmed from
-- database/mock-data-generation/volunteer_applications.py. The `users`
-- table has no DDL in this repo - its primary key column is ASSUMED to be
-- `id` here; verify against the real table (e.g. via information_schema.columns)
-- and update helpers.py's join + this file if the real column name differs.
--
-- application_status values are also ASSUMED from
-- database/mock-data-generation/utils.py's STATUSES list
-- (DRAFT, IN_PROGRESS, SUBMITTED, UNDER_REVIEW, APPROVED). Confirm the real
-- values with `SELECT DISTINCT application_status FROM volunteer_applications;`
-- before relying on STEWARD_REVIEW_STATUSES=UNDER_REVIEW in a real environment.

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,          -- ASSUMED column name
    name TEXT,
    email TEXT
);

CREATE TABLE IF NOT EXISTS volunteer_applications (
    user_id TEXT PRIMARY KEY REFERENCES users(id),
    terms_and_conditions BOOLEAN,
    terms_accepted_at TIMESTAMPTZ,
    govt_id_path TEXT,
    path_updated_at TIMESTAMPTZ,
    skill_codes JSONB,
    availability JSONB,
    current_page INTEGER,
    application_status TEXT NOT NULL,
    is_completed BOOLEAN,
    created_at TIMESTAMPTZ,
    last_updated_at TIMESTAMPTZ NOT NULL
);

INSERT INTO users (id, name, email) VALUES
    ('U101', 'Asha Patel', 'asha.patel@example.com'),
    ('U102', 'Marcus Lee', 'marcus.lee@example.com'),
    ('U103', 'Priya Nair', 'priya.nair@example.com'),
    ('U104', 'Diego Alvarez', 'diego.alvarez@example.com'),
    ('U105', 'Fatima Noor', 'fatima.noor@example.com')
ON CONFLICT (id) DO NOTHING;

INSERT INTO volunteer_applications
    (user_id, terms_and_conditions, terms_accepted_at, govt_id_path, path_updated_at,
     skill_codes, availability, current_page, application_status, is_completed,
     created_at, last_updated_at)
VALUES
    ('U101', TRUE, now() - interval '9 days', '/uploads/id/U101.pdf', now() - interval '9 days',
     '["1.1","2.2"]', '{"weekdays":"evening"}', 5, 'UNDER_REVIEW', TRUE,
     now() - interval '10 days', '2026-05-12T07:15:00Z'),
    ('U102', TRUE, now() - interval '6 days', '/uploads/id/U102.pdf', now() - interval '6 days',
     '["3.3","4.1"]', '{"weekends":"full_day"}', 5, 'UNDER_REVIEW', TRUE,
     now() - interval '7 days', now() - interval '1 days'),
    ('U103', TRUE, now() - interval '3 days', '/uploads/id/U103.pdf', now() - interval '3 days',
     '["5.1"]', '{"weekdays":"morning"}', 4, 'UNDER_REVIEW', TRUE,
     now() - interval '4 days', now() - interval '2 hours'),
    ('U104', TRUE, now() - interval '20 days', '/uploads/id/U104.pdf', now() - interval '20 days',
     '["6.2"]', '{"weekdays":"flexible"}', 5, 'APPROVED', TRUE,
     now() - interval '21 days', now() - interval '15 days'),
    ('U105', FALSE, NULL, '/uploads/id/U105.pdf', now() - interval '1 days',
     '["2.1"]', '{"weekends":"morning"}', 2, 'DRAFT', FALSE,
     now() - interval '1 days', now() - interval '12 hours')
ON CONFLICT (user_id) DO NOTHING;
