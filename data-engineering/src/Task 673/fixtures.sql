-- Synthetic data only. {schema} is safely quoted by psycopg2.sql.Identifier.
CREATE SCHEMA {schema};
CREATE TABLE {schema}.help_categories (cat_id TEXT PRIMARY KEY, cat_name TEXT);
INSERT INTO {schema}.help_categories VALUES ('food', 'Food'), ('housing', 'Housing');

CREATE TABLE {schema}.countries (country_id TEXT PRIMARY KEY, country_name TEXT);
INSERT INTO {schema}.countries VALUES ('US', 'United States');
CREATE TABLE {schema}.states (
    state_id TEXT PRIMARY KEY, state_code TEXT, state_name TEXT, country_id TEXT
);
INSERT INTO {schema}.states VALUES ('IL', 'IL', 'Illinois', 'US');
CREATE TABLE {schema}.cities (
    city_name TEXT, state_id TEXT, lattitude DOUBLE PRECISION, longitude DOUBLE PRECISION
);
INSERT INTO {schema}.cities VALUES
    ('Chicago', 'IL', 41.8781, -87.6298),
    ('Evanston', 'IL', 42.0451, -87.6877);

CREATE TABLE {schema}.users (
    user_id TEXT PRIMARY KEY, first_name TEXT, last_name TEXT,
    addr_ln1 TEXT, addr_ln2 TEXT, addr_ln3 TEXT, city_name TEXT,
    zip_code TEXT, state_id TEXT, primary_phone_number TEXT, primary_email_address TEXT
);
INSERT INTO {schema}.users VALUES
    ('beneficiary-673', 'Local', 'Beneficiary', '10 Example Street', NULL, NULL,
     'Chicago', '60601', 'IL', '555-0100', 'beneficiary@example.invalid');
CREATE TABLE {schema}.requests (
    req_id TEXT PRIMARY KEY, beneficiary_id TEXT, req_cat_id TEXT,
    req_desc TEXT, req_subj TEXT, req_loc TEXT
);
INSERT INTO {schema}.requests VALUES
    ('request-673', 'beneficiary-673', 'food', 'Need groceries', 'Food assistance',
     '41.8781, -87.6298');
CREATE TABLE {schema}.user_locations (user_id TEXT, curr_loc TEXT);
CREATE TABLE {schema}.user_org_map (org_id TEXT, user_id TEXT);

CREATE TABLE {schema}.organizations (
    org_id TEXT PRIMARY KEY, org_name TEXT, org_type TEXT,
    is_collaborator BOOLEAN, is_contributor BOOLEAN,
    street TEXT, city_name TEXT, state_id TEXT, zip_code TEXT,
    org_size TEXT, org_rating DOUBLE PRECISION, phone TEXT, email TEXT,
    web_url TEXT, mission TEXT
);
INSERT INTO {schema}.organizations VALUES
    ('org-true', 'Community Pantry', 'Nonprofit', TRUE, TRUE,
     '30 Example Street', 'Chicago', 'IL', '60601', 'Large', 4.8, '555-0101',
     'pantry@example.invalid', 'https://pantry.example.invalid', 'Food assistance'),
    ('org-false', 'Neighborhood Kitchen', 'Nonprofit', FALSE, FALSE,
     '40 Example Street', 'Chicago', 'IL', '60601', 'Small', 4.5, '555-0102',
     'kitchen@example.invalid', 'https://kitchen.example.invalid', 'Food assistance'),
    ('org-null', 'Volunteer Groceries', 'Community', NULL, NULL,
     '50 Example Street', 'Chicago', 'IL', '60601', 'Medium', 4.0, '555-0103',
     'groceries@example.invalid', 'https://groceries.example.invalid', 'Food assistance'),
    ('org-other-city', 'Evanston Pantry', 'Nonprofit', FALSE, TRUE,
     '60 Example Street', 'Evanston', 'IL', '60201', 'Medium', 4.1, '555-0105',
     'evanston@example.invalid', 'https://evanston.example.invalid', 'Food assistance'),
    ('org-other-category', 'Housing Support', 'Nonprofit', TRUE, FALSE,
     '70 Example Street', 'Chicago', 'IL', '60601', 'Large', 4.7, '555-0106',
     'housing@example.invalid', 'https://housing.example.invalid', 'Housing assistance');
CREATE TABLE {schema}.org_skills (org_id TEXT, cat_id TEXT);
INSERT INTO {schema}.org_skills VALUES
    ('org-true', 'food'), ('org-true', 'food'), ('org-false', 'food'),
    ('org-null', 'food'), ('org-other-city', 'food'), ('org-other-category', 'housing');
