-- Local dev seed for the Organization Analytics API (issue #228).
--
-- Column names are confirmed against the issue's sample data
-- (data-analytics/sql/organizations.csv and states.csv). is_contributor is
-- flagged in the issue as possibly missing from the current dev DB; it is
-- included here since local dev should mirror the target schema.

CREATE SCHEMA IF NOT EXISTS virginia_dev_saayam_rdbms;

CREATE TABLE IF NOT EXISTS virginia_dev_saayam_rdbms.states (
    state_id TEXT PRIMARY KEY,
    state_name TEXT NOT NULL
);

INSERT INTO virginia_dev_saayam_rdbms.states (state_id, state_name) VALUES
    ('AK', 'Alaska'), ('IN', 'Indiana'), ('WI', 'Wisconsin'), ('MN', 'Minnesota'),
    ('ME', 'Maine'), ('MO', 'Missouri'), ('RI', 'Rhode Island'), ('IA', 'Iowa'),
    ('MT', 'Montana'), ('UT', 'Utah'), ('WA', 'Washington'), ('OH', 'Ohio'),
    ('KS', 'Kansas'), ('FL', 'Florida'), ('TX', 'Texas'), ('OK', 'Oklahoma'),
    ('CA', 'California')
ON CONFLICT (state_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS virginia_dev_saayam_rdbms.organizations (
    org_id TEXT PRIMARY KEY,
    org_name TEXT NOT NULL,
    street TEXT,
    city_name TEXT,
    state_id TEXT REFERENCES virginia_dev_saayam_rdbms.states(state_id),
    zip_code TEXT,
    mission TEXT,
    web_url TEXT,
    phone TEXT,
    email TEXT,
    org_type TEXT,
    org_size TEXT,
    org_rating NUMERIC(2, 0),
    is_collaborator BOOLEAN DEFAULT FALSE,
    is_contributor BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT now(),
    last_updated_at TIMESTAMPTZ DEFAULT now()
);

INSERT INTO virginia_dev_saayam_rdbms.organizations
    (org_id, org_name, city_name, state_id, mission, web_url, phone, email,
     org_type, org_size, org_rating, is_collaborator, is_contributor, created_at, last_updated_at)
VALUES
    ('ORG00001', 'Harbor Veterans Support', 'North Judithbury', 'AK', 'Veteran services', 'https://www.harborveteranssuppor.org', '(078) 161-8495', 'contact@harborveteranssuppor.org', 'Non-Profit', 'Small', 5, FALSE, TRUE, now() - interval '600 days', now() - interval '580 days'),
    ('ORG00002', 'Summit Community Foundation', 'North Donnaport', 'IN', 'Community foundation', 'https://www.summitcommunityfound.org', '(056) 413-9537', NULL, 'For-profit', 'Large', 2, FALSE, TRUE, now() - interval '700 days', now() - interval '400 days'),
    ('ORG00003', 'Northgate Education Fund', 'Thomasberg', 'WI', 'Education fund', 'https://www.northgateeducationfu.org', '(480) 184-5146', 'contact@northgateeducationfu.org', 'Non-Profit', 'Medium', 3, FALSE, TRUE, now() - interval '900 days', now() - interval '850 days'),
    ('ORG00004', 'Harbor Family Services', 'Lake Nancyview', 'MN', 'Family services', 'https://www.harborfamilyservices.org', '(896) 383-4657', 'contact@harborfamilyservices.org', 'Non-Profit', 'Large', 5, TRUE, FALSE, now() - interval '300 days', now() - interval '100 days'),
    ('ORG00005', 'Maplewood Relief Network', 'Martinezbury', 'ME', 'Disaster relief', 'https://www.maplewoodreliefnetwo.org', '(763) 116-5667', 'contact@maplewoodreliefnetwo.org', 'Non-Profit', 'Small', 3, TRUE, FALSE, now() - interval '320 days', now() - interval '60 days'),
    ('ORG00006', 'Harbor Senior Care Network', 'Lake Deniseville', 'MO', 'Senior care', 'https://www.harborseniorcarenetw.org', '(773) 602-6064', 'contact@harborseniorcarenetw.org', 'For-profit', 'Medium', 3, FALSE, TRUE, now() - interval '280 days', now() - interval '55 days'),
    ('ORG00007', 'Summit Education Fund', 'Mitchellside', 'RI', 'Education fund', 'https://www.summiteducationfund.org', '(169) 985-4353', 'contact@summiteducationfund.org', 'Non-Profit', 'Small', 3, TRUE, FALSE, now() - interval '850 days', now() - interval '400 days'),
    ('ORG00008', 'Riverside Environmental Coalition', 'Lake Debbie', 'IA', 'Environmental advocacy', 'https://www.riversideenvironment.org', '(411) 824-4935', 'contact@riversideenvironment.org', 'For-profit', 'Large', 5, TRUE, FALSE, now() - interval '950 days', now() - interval '870 days'),
    ('ORG00009', 'Lakeside Veterans Support', 'Williamview', 'MT', 'Veteran services', 'https://www.lakesideveteranssupp.org', '(923) 226-0256', 'contact@lakesideveteranssupp.org', 'Non-Profit', 'Small', 5, FALSE, TRUE, now() - interval '400 days', now() - interval '90 days'),
    ('ORG00010', 'Golden Gate Family Services', 'West Erik', 'IA', 'Family services', 'https://www.goldengatefamilyserv.org', '(429) 401-9655', 'contact@goldengatefamilyserv.org', 'For-profit', 'Small', NULL, FALSE, TRUE, now() - interval '700 days', now() - interval '320 days'),
    ('ORG00011', 'Hopewell Veterans Support', 'South Rachelborough', 'RI', 'Veteran services', 'https://www.hopewellveteranssupp.org', '(044) 369-9577', 'contact@hopewellveteranssupp.org', 'Non-Profit', 'Medium', 5, TRUE, FALSE, now() - interval '750 days', now() - interval '390 days'),
    ('ORG00012', 'Harbor Animal Rescue', 'New Thomas', 'UT', 'Animal welfare', 'https://www.harboranimalrescue.org', '(287) 083-1727', 'contact@harboranimalrescue.org', 'For-profit', 'Large', 3, TRUE, FALSE, now() - interval '520 days', now() - interval '440 days'),
    ('ORG00013', 'Northgate Housing Trust', 'Stephaniemouth', 'WA', 'Affordable housing', 'https://www.northgatehousingtrus.org', '(967) 054-6688', 'contact@northgatehousingtrus.org', 'Non-Profit', 'Medium', 3, TRUE, FALSE, now() - interval '400 days', now() - interval '320 days'),
    ('ORG00014', 'Oakwood Environmental Coalition', 'South Jeffrey', 'OH', 'Environmental advocacy', 'https://www.oakwoodenvironmental.org', '(170) 805-3100', 'contact@oakwoodenvironmental.org', 'For-profit', 'Small', 1, FALSE, TRUE, now() - interval '260 days', now() - interval '35 days'),
    ('ORG00015', 'Unity Senior Care Network', 'Port Andrew', 'KS', 'Senior care', 'https://www.unityseniorcarenetwo.org', '(663) 193-1491', 'contact@unityseniorcarenetwo.org', 'For-profit', 'Large', 4, FALSE, TRUE, now() - interval '400 days', now() - interval '130 days'),
    ('ORG00016', 'Meadowbrook Legal Aid Society', 'West Amandastad', 'FL', 'Legal aid', 'https://www.meadowbrooklegalaids.org', '(354) 549-4808', 'contact@meadowbrooklegalaids.org', 'Non-Profit', 'Large', 2, TRUE, FALSE, now() - interval '260 days', now() - interval '80 days'),
    ('ORG00017', 'Liberty Education Fund', 'East Jenniferfort', 'TX', 'Education fund', 'https://www.libertyeducationfund.org', '(233) 749-8941', 'contact@libertyeducationfund.org', 'For-profit', 'Large', 2, TRUE, FALSE, now() - interval '360 days', now() - interval '195 days'),
    ('ORG00018', 'Sunrise Community Foundation', 'Jeremyburgh', 'OK', 'Community foundation', 'https://www.sunrisecommunityfoun.org', '(938) 677-4964', NULL, 'For-profit', 'Large', 2, TRUE, FALSE, now() - interval '600 days', now() - interval '150 days'),
    ('ORG00019', 'Cedar Valley Community Foundation', 'New Susanville', 'CA', 'Community foundation', 'https://www.cedarvalleycommunity.org', '(242) 102-4994', 'contact@cedarvalleycommunity.org', 'Non-Profit', 'Large', 5, TRUE, FALSE, now() - interval '720 days', now() - interval '600 days'),
    ('ORG00020', 'Bay Area Youth Alliance', 'San Leandro', 'CA', 'Youth development', 'https://www.bayareayouthalliance.org', '(415) 555-0134', 'contact@bayareayouthalliance.org', 'Non-Profit', 'Medium', NULL, FALSE, TRUE, now() - interval '20 days', now() - interval '5 days')
ON CONFLICT (org_id) DO NOTHING;
