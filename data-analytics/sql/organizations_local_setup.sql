-- Local-only schema + seed data for developing/testing the Organization Analytics API,
-- sourced directly from the real sample data the team provided:
--   https://github.com/saayam-for-all/data/blob/main/data-analytics/sql/organizations.csv
--   https://github.com/saayam-for-all/data/blob/main/data-analytics/sql/state.csv
-- org_type/org_size are plain TEXT (not a strict lowercase enum) because the real data
-- uses "Non-Profit"/"For-profit"/"Small" casing -- organization_analytics.py normalizes
-- these at query time instead of forcing the schema to match a clean vocabulary that
-- doesn't match the actual data.
-- Safe to re-run: tables are guarded, inserts use ON CONFLICT DO NOTHING.

CREATE SCHEMA IF NOT EXISTS virginia_dev_saayam_rdbms;

CREATE TABLE IF NOT EXISTS virginia_dev_saayam_rdbms.state (
    state_id VARCHAR(50) PRIMARY KEY,
    country_id INT NOT NULL,
    state_name VARCHAR(100) NOT NULL,
    state_code VARCHAR(6),
    last_update_date TIMESTAMP
);

-- Drop and recreate: an earlier iteration of this script created organizations with
-- org_type/org_size as strict lowercase ENUMs. This local table is throwaway test data,
-- so the simplest fix for anyone who ran that earlier version is a clean rebuild rather
-- than an ALTER COLUMN migration.
DROP TABLE IF EXISTS virginia_dev_saayam_rdbms.organizations CASCADE;
DROP TYPE IF EXISTS org_type_enum CASCADE;
DROP TYPE IF EXISTS org_size_enum CASCADE;

CREATE TABLE IF NOT EXISTS virginia_dev_saayam_rdbms.organizations (
    org_id VARCHAR(255) PRIMARY KEY,
    org_name VARCHAR(125) NOT NULL,
    street VARCHAR(255),
    city_name VARCHAR(100),
    state_id VARCHAR(50),
    zip_code VARCHAR(10),
    mission TEXT,
    web_url VARCHAR(255),
    phone VARCHAR(20),
    email VARCHAR(255),
    org_type TEXT,
    org_size TEXT,
    org_rating INTEGER CHECK (org_rating IS NULL OR (org_rating >= 1 AND org_rating <= 5)),
    is_collaborator BOOLEAN,
    is_contributor BOOLEAN,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'UTC'),
    last_updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'UTC'),
    FOREIGN KEY (state_id) REFERENCES virginia_dev_saayam_rdbms.state(state_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_org_name ON virginia_dev_saayam_rdbms.organizations(org_name);
CREATE INDEX IF NOT EXISTS idx_org_state_id ON virginia_dev_saayam_rdbms.organizations(state_id);
CREATE INDEX IF NOT EXISTS idx_org_city_state ON virginia_dev_saayam_rdbms.organizations(city_name, state_id);

INSERT INTO virginia_dev_saayam_rdbms.state (state_id, country_id, state_name, state_code, last_update_date) VALUES
    ('AL', 1, 'Alabama', 'US-AL', '2025-08-08 00:00:00'),
    ('AK', 1, 'Alaska', 'US-AK', '2026-02-01 00:00:00'),
    ('AZ', 1, 'Arizona', 'US-AZ', '2025-05-27 00:00:00'),
    ('AR', 1, 'Arkansas', 'US-AR', '2024-09-07 00:00:00'),
    ('CA', 1, 'California', 'US-CA', '2026-05-17 00:00:00'),
    ('CO', 1, 'Colorado', 'US-CO', '2026-04-22 00:00:00'),
    ('CT', 1, 'Connecticut', 'US-CT', '2024-03-17 00:00:00'),
    ('DE', 1, 'Delaware', 'US-DE', '2025-01-03 00:00:00'),
    ('DC', 1, 'District of Columbia', 'US-DC', '2026-03-31 00:00:00'),
    ('FL', 1, 'Florida', 'US-FL', '2025-06-26 00:00:00'),
    ('GA', 1, 'Georgia', 'US-GA', '2024-11-16 00:00:00'),
    ('HI', 1, 'Hawaii', 'US-HI', '2026-05-07 00:00:00'),
    ('ID', 1, 'Idaho', 'US-ID', '2025-02-01 00:00:00'),
    ('IL', 1, 'Illinois', 'US-IL', '2025-11-28 00:00:00'),
    ('IN', 1, 'Indiana', 'US-IN', '2026-05-28 00:00:00'),
    ('IA', 1, 'Iowa', 'US-IA', '2026-04-08 00:00:00'),
    ('KS', 1, 'Kansas', 'US-KS', '2025-04-17 00:00:00'),
    ('KY', 1, 'Kentucky', 'US-KY', '2025-05-03 00:00:00'),
    ('LA', 1, 'Louisiana', 'US-LA', '2026-04-25 00:00:00'),
    ('ME', 1, 'Maine', 'US-ME', '2025-11-01 00:00:00'),
    ('MD', 1, 'Maryland', 'US-MD', '2026-04-04 00:00:00'),
    ('MA', 1, 'Massachusetts', 'US-MA', '2024-12-18 00:00:00'),
    ('MI', 1, 'Michigan', 'US-MI', '2025-04-27 00:00:00'),
    ('MN', 1, 'Minnesota', 'US-MN', '2026-05-06 00:00:00'),
    ('MS', 1, 'Mississippi', 'US-MS', '2024-03-11 00:00:00'),
    ('MO', 1, 'Missouri', 'US-MO', '2024-12-03 00:00:00'),
    ('MT', 1, 'Montana', 'US-MT', '2026-03-01 00:00:00'),
    ('NE', 1, 'Nebraska', 'US-NE', '2025-11-19 00:00:00'),
    ('NV', 1, 'Nevada', 'US-NV', '2024-09-28 00:00:00'),
    ('NH', 1, 'New Hampshire', 'US-NH', '2024-10-01 00:00:00'),
    ('NJ', 1, 'New Jersey', 'US-NJ', '2024-11-16 00:00:00'),
    ('NM', 1, 'New Mexico', 'US-NM', '2026-05-03 00:00:00'),
    ('NY', 1, 'New York', 'US-NY', '2024-11-22 00:00:00'),
    ('NC', 1, 'North Carolina', 'US-NC', '2024-11-13 00:00:00'),
    ('ND', 1, 'North Dakota', 'US-ND', '2025-05-25 00:00:00'),
    ('OH', 1, 'Ohio', 'US-OH', '2026-05-16 00:00:00'),
    ('OK', 1, 'Oklahoma', 'US-OK', '2025-11-21 00:00:00'),
    ('OR', 1, 'Oregon', 'US-OR', '2026-05-19 00:00:00'),
    ('PA', 1, 'Pennsylvania', 'US-PA', '2024-12-12 00:00:00'),
    ('RI', 1, 'Rhode Island', 'US-RI', '2026-02-19 00:00:00'),
    ('SC', 1, 'South Carolina', 'US-SC', '2025-09-12 00:00:00'),
    ('SD', 1, 'South Dakota', 'US-SD', '2025-05-02 00:00:00'),
    ('TN', 1, 'Tennessee', 'US-TN', '2026-02-08 00:00:00'),
    ('TX', 1, 'Texas', 'US-TX', '2024-12-29 00:00:00'),
    ('UT', 1, 'Utah', 'US-UT', '2026-03-07 00:00:00'),
    ('VT', 1, 'Vermont', 'US-VT', '2024-11-28 00:00:00'),
    ('VA', 1, 'Virginia', 'US-VA', '2025-08-24 00:00:00'),
    ('WA', 1, 'Washington', 'US-WA', '2024-12-09 00:00:00'),
    ('WV', 1, 'West Virginia', 'US-WV', '2024-03-22 00:00:00'),
    ('WI', 1, 'Wisconsin', 'US-WI', '2024-08-06 00:00:00'),
    ('WY', 1, 'Wyoming', 'US-WY', '2026-01-01 00:00:00')
ON CONFLICT (state_id) DO NOTHING;

INSERT INTO virginia_dev_saayam_rdbms.organizations
    (org_id, org_name, street, city_name, state_id, zip_code, mission, web_url, phone, email,
     org_type, org_size, org_rating, is_collaborator, is_contributor, created_at, last_updated_at) VALUES
    ('ORG00001', 'Harbor Veterans Support', '18196 Anthony Forge', 'North Judithbury', 'AK', '30996', 'Own night respond red information last everything thank serve civil institution everyone democratic shake bill here grow gas enough.', 'https://www.harborveteranssuppor.org', '(078) 161-8495', 'contact@harborveteranssuppor.org', 'Non-Profit', 'Small', 5, FALSE, TRUE, '2025-01-13 03:53:25', '2025-01-29 03:53:25'),
    ('ORG00002', 'Summit Community Foundation', '16475 Mitchell Fords', 'North Donnaport', 'IN', '88342', 'Reduce raise author play move each left establish understand read detail food shoulder argue.', 'https://www.summitcommunityfound.org', '(056) 413-9537', NULL, 'For-profit', 'Large', 2, FALSE, TRUE, '2024-07-31 05:09:50', '2025-05-28 05:09:50'),
    ('ORG00003', 'Northgate Education Fund', '884 Hurst Locks', 'Thomasberg', 'WI', '47948', 'Young catch management sense technology check civil quite others his other life.', 'https://www.northgateeducationfu.org', '(480) 184-5146', 'contact@northgateeducationfu.org', 'Non-Profit', 'Medium', 3, FALSE, TRUE, '2023-12-27 08:29:26', '2024-02-12 08:29:26'),
    ('ORG00004', 'Harbor Family Services', '148 Eric Track', 'Lake Nancyview', 'MN', '21675', 'Well two truth out major born guy world southern dream drive note bad rule staff within mouth call process water close.', 'https://www.harborfamilyservices.org', '(896) 383-4657', 'contact@harborfamilyservices.org', 'Non-Profit', 'Large', 5, TRUE, FALSE, '2025-11-03 10:50:27', '2026-05-15 10:50:27'),
    ('ORG00005', 'Maplewood Relief Network', '0983 Adrian Station', 'Martinezbury', 'ME', '83220', 'Director town teacher audience draw protect Democrat car very number line.', 'https://www.maplewoodreliefnetwo.org', '(763) 116-5667', 'contact@maplewoodreliefnetwo.org', 'Non-Profit', 'Small', 3, TRUE, FALSE, '2025-10-01 18:42:58', '2026-01-28 18:42:58'),
    ('ORG00006', 'Harbor Senior Care Network', '5133 Amanda Dam', 'Lake Deniseville', 'MO', '55797', 'Everything economic type kitchen technology nearly anything yourself structure why unit support coach.', 'https://www.harborseniorcarenetw.org', '(773) 602-6064', 'contact@harborseniorcarenetw.org', 'For-profit', 'Medium', 3, FALSE, TRUE, '2025-11-28 00:29:24', '2026-05-18 00:29:24'),
    ('ORG00007', 'Summit Education Fund', '34309 Julie Centers Apt. 978', 'Mitchellside', 'RI', '70116', 'Arm meet surface attention attack technology identify walk now often always.', 'https://www.summiteducationfund.org', '(169) 985-4353', 'contact@summiteducationfund.org', 'Non-Profit', 'Small', 3, TRUE, FALSE, '2024-04-03 11:35:56', '2025-03-19 11:35:56'),
    ('ORG00008', 'Riverside Environmental Coalition', '1079 Charles Forest Suite 251', 'Lake Debbie', 'IA', '32519', 'Expect just myself few worker southern more property never use billion there.', 'https://www.riversideenvironment.org', '(411) 824-4935', 'contact@riversideenvironment.org', 'For-profit', 'Large', 5, TRUE, FALSE, '2024-02-06 20:22:49', '2024-05-24 20:22:49'),
    ('ORG00009', 'Lakeside Veterans Support', '64005 Dana Greens', 'Williamview', 'MT', '21679', 'Necessary into act away third tough nation strong old challenge camera final together someone team together decide economic bill sister this image.', 'https://www.lakesideveteranssupp.org', '(923) 226-0256', 'contact@lakesideveteranssupp.org', 'Non-Profit', 'Small', 5, FALSE, TRUE, '2025-08-06 12:36:21', '2026-05-31 12:36:21'),
    ('ORG00010', 'Golden Gate Family Services', '0733 Bailey View', 'West Erik', 'IA', '30332', 'Age cover foreign ten whom evidence political hundred wonder movie voice boy.', 'https://www.goldengatefamilyserv.org', '(429) 401-9655', 'contact@goldengatefamilyserv.org', 'For-profit', 'Small', 2, FALSE, TRUE, '2024-09-06 10:32:10', '2025-10-16 10:32:10'),
    ('ORG00011', 'Hopewell Veterans Support', '60883 Reynolds Shores Suite 951', 'South Rachelborough', 'RI', '94840', 'Medical project for recent never court professor here security community notice image.', 'https://www.hopewellveteranssupp.org', '(044) 369-9577', 'contact@hopewellveteranssupp.org', 'Non-Profit', 'Medium', 5, TRUE, FALSE, '2024-09-11 16:54:24', '2025-08-25 16:54:24'),
    ('ORG00012', 'Harbor Animal Rescue', '148 Davis Terrace', 'New Thomas', 'UT', '31285', 'Different current agency each little sure authority increase picture create recent manager during prevent accept seem show blood interesting.', 'https://www.harboranimalrescue.org', '(287) 083-1727', 'contact@harboranimalrescue.org', 'For-profit', 'Large', 3, TRUE, FALSE, '2025-04-05 13:20:47', '2025-06-24 13:20:47'),
    ('ORG00013', 'Northgate Housing Trust', '727 Green Gateway Suite 873', 'Stephaniemouth', 'WA', '36493', 'Back experience even floor music catch discuss really relationship ask imagine my indeed deal information toward once receive.', 'https://www.northgatehousingtrus.org', '(967) 054-6688', 'contact@northgatehousingtrus.org', 'Non-Profit', 'Medium', 3, TRUE, FALSE, '2025-08-04 08:43:46', '2025-10-21 08:43:46'),
    ('ORG00014', 'Oakwood Environmental Coalition', '0656 Mary Crossroad Apt. 699', 'South Jeffrey', 'OH', '87401', 'Base investment term consider employee force lawyer front they everything week instead.', 'https://www.oakwoodenvironmental.org', '(170) 805-3100', 'contact@oakwoodenvironmental.org', 'For-profit', 'Small', 1, FALSE, TRUE, '2025-12-19 02:37:45', '2026-07-31 02:37:45'),
    ('ORG00015', 'Unity Senior Care Network', '27193 Lyons Trafficway', 'Port Andrew', 'KS', '48852', 'Paper white responsibility sing clearly find official up office.', 'https://www.unityseniorcarenetwo.org', '(663) 193-1491', 'contact@unityseniorcarenetwo.org', 'For-profit', 'Large', 4, FALSE, TRUE, '2025-08-01 00:55:53', '2026-04-30 00:55:53'),
    ('ORG00016', 'Meadowbrook Legal Aid Society', '506 Garcia Lake', 'West Amandastad', 'FL', '83808', 'Religious itself safe whole establish space Mrs low itself room environmental system store beautiful think during let particular her agreement surface consider.', 'https://www.meadowbrooklegalaids.org', '(354) 549-4808', 'contact@meadowbrooklegalaids.org', 'Non-Profit', 'Large', 2, TRUE, FALSE, '2025-12-17 16:40:36', '2026-06-17 16:40:36'),
    ('ORG00017', 'Liberty Education Fund', '777 Christopher Forges', 'East Jenniferfort', 'TX', '53506', 'Fill ok list most international second former reflect even edge building court build movie several.', 'https://www.libertyeducationfund.org', '(233) 749-8941', 'contact@libertyeducationfund.org', 'For-profit', 'Large', 2, TRUE, FALSE, '2025-09-03 06:43:41', '2026-02-23 06:43:41'),
    ('ORG00018', 'Sunrise Community Foundation', '82400 Terry Crossroad Suite 109', 'Jeremyburgh', 'OK', '37769', 'Long future whole education technology box assume man officer rather charge specific we be easy newspaper indicate other.', 'https://www.sunrisecommunityfoun.org', '(938) 677-4964', NULL, 'For-profit', 'Large', 2, TRUE, FALSE, '2025-01-05 04:43:02', '2026-04-13 04:43:02'),
    ('ORG00019', 'Cedar Valley Community Foundation', '341 John Plaza', 'New Susanville', 'CA', '10339', 'Able late order fact discuss religious reflect law reach under skin person product value interesting name.', 'https://www.cedarvalleycommunity.org', '(242) 102-4994', 'contact@cedarvalleycommunity.org', 'Non-Profit', 'Large', 5, TRUE, FALSE, '2024-09-08 23:01:01', '2025-01-10 23:01:01'),
    ('ORG00020', 'Lakeside Legal Aid Society', '877 Carly Meadows Suite 940', 'Barkerfurt', 'NE', '12471', 'While structure offer week yourself public especially American series like prepare trouble consider.', NULL, '(967) 175-6551', 'contact@lakesidelegalaidsoci.org', 'Non-Profit', 'Large', 4, TRUE, FALSE, '2025-09-26 04:56:36', '2025-10-23 04:56:36'),
    ('ORG00021', 'Harbor Veterans Support', '680 Miller Glen Suite 168', 'Robertfort', 'AR', '00651', 'Left approach million performance material kind appear environment capital explain thing machine ahead picture son report financial add impact different success box water.', 'https://www.harborveteranssuppor.org', '(274) 846-7737', 'contact@harborveteranssuppor.org', 'Non-Profit', 'Large', 2, TRUE, FALSE, '2024-12-20 08:08:43', '2025-09-20 08:08:43'),
    ('ORG00022', 'Meadowbrook Housing Trust', '46584 Justin Hills', 'Leehaven', 'NV', '77432', 'Your majority chance Mrs generation necessary myself lay focus country recently occur do simply analysis seat relate specific.', 'https://www.meadowbrookhousingtr.org', '(627) 028-9517', 'contact@meadowbrookhousingtr.org', 'Non-Profit', 'Large', 5, TRUE, FALSE, '2023-11-03 23:32:24', '2023-11-28 23:32:24'),
    ('ORG00023', 'Maplewood Veterans Support', '217 Morgan Square Suite 158', 'Smithberg', 'AL', '50309', 'Phone thought maintain must pay doctor range explain dinner bed within set region.', 'https://www.maplewoodveteranssup.org', '(172) 400-5045', 'contact@maplewoodveteranssup.org', 'For-profit', 'Medium', 4, TRUE, FALSE, '2024-07-12 05:29:45', '2024-10-29 05:29:45'),
    ('ORG00024', 'Liberty Senior Care Network', '21969 Tyler Prairie', 'East Amanda', 'AR', '19259', 'Leave effect effort act source top quality citizen kid generation onto police.', 'https://www.libertyseniorcarenet.org', '(647) 436-7136', 'contact@libertyseniorcarenet.org', 'For-profit', 'Large', 3, FALSE, TRUE, '2025-01-08 04:53:38', '2025-12-30 04:53:38'),
    ('ORG00025', 'Maplewood Animal Rescue', '640 Renee Summit', 'Victoriaport', 'TX', '65608', 'Simply discover soon despite couple economy sense should race carry best physical always small almost half capital travel.', 'https://www.maplewoodanimalrescu.org', '(562) 328-5884', 'contact@maplewoodanimalrescu.org', 'Non-Profit', 'Large', 3, FALSE, TRUE, '2025-09-01 07:28:52', '2025-09-26 07:28:52'),
    ('ORG00026', 'Lakeside Food Bank', '517 Donald Fork Suite 851', 'Robinfort', 'NC', '52218', 'Enough buy happy see energy herself police he push likely people wall.', 'https://www.lakesidefoodbank.org', '(593) 174-6120', 'contact@lakesidefoodbank.org', 'Non-Profit', 'Large', 1, FALSE, TRUE, '2025-12-16 01:12:13', '2026-06-06 01:12:13'),
    ('ORG00027', 'Silverline Senior Care Network', '82675 Matthews Stream', 'Wendyville', 'MT', '20754', 'Pressure street past voice evidence real describe know door guy wonder happen top population.', 'https://www.silverlineseniorcare.org', '(064) 317-1390', 'contact@silverlineseniorcare.org', 'For-profit', 'Small', 5, TRUE, FALSE, '2023-09-20 02:41:52', '2024-04-21 02:41:52'),
    ('ORG00028', 'Sunrise Veterans Support', '83933 Schroeder Turnpike', 'Johnberg', 'OR', '78617', 'Everyone worker would music sometimes body term capital group small open administration.', 'https://www.sunriseveteranssuppo.org', '(402) 681-1775', 'contact@sunriseveteranssuppo.org', 'For-profit', 'Large', 2, TRUE, FALSE, '2024-11-15 14:42:45', '2025-06-05 14:42:45'),
    ('ORG00029', 'Unity Youth Alliance', '0076 Parks Overpass Suite 115', 'South Williamton', 'NJ', '80231', 'Assume every plan nature foot yes most law painting between reduce table prepare.', 'https://www.unityyouthalliance.org', '(836) 736-5766', 'contact@unityyouthalliance.org', 'Non-Profit', 'Large', 5, FALSE, TRUE, '2025-06-01 04:57:01', '2025-07-08 04:57:01'),
    ('ORG00030', 'Pinecrest Arts Collective', '71111 Davis Streets Suite 280', 'Ronaldview', 'NC', '77370', 'No prove improve them wait institution trouble anything explain fine billion medical choice lot suggest glass news boy everything difficult.', 'https://www.pinecrestartscollect.org', '(689) 980-9402', 'contact@pinecrestartscollect.org', 'For-profit', 'Large', 3, FALSE, TRUE, '2024-04-10 11:23:28', '2024-06-29 11:23:28'),
    ('ORG00031', 'Maplewood Housing Trust', '29612 Christopher Pines', 'Sandrastad', 'VA', '28698', 'Information game have return since nothing be apply church pay purpose evening product magazine kind event sense.', 'https://www.maplewoodhousingtrus.org', '(156) 149-7840', 'contact@maplewoodhousingtrus.org', 'For-profit', 'Small', 5, TRUE, FALSE, '2024-02-22 07:14:14', '2025-06-13 07:14:14'),
    ('ORG00032', 'Harbor Veterans Support', '4510 Burgess Extensions', 'North Jamesborough', 'FL', '17433', 'Mouth discover next property government however score job least back fine investment identify policy face if whom.', 'https://www.harborveteranssuppor.org', '(297) 516-1369', 'contact@harborveteranssuppor.org', 'For-profit', 'Medium', 3, TRUE, FALSE, '2024-08-04 14:45:26', '2025-06-09 14:45:26'),
    ('ORG00033', 'Cedar Valley Health Initiative', '2181 Rebecca Keys', 'South Monicamouth', 'IN', '46520', 'Door chair culture own set pretty concern significant management senior service large.', 'https://www.cedarvalleyhealthini.org', '(995) 527-1774', 'contact@cedarvalleyhealthini.org', 'For-profit', 'Large', 1, FALSE, TRUE, '2025-08-01 03:10:37', '2025-12-20 03:10:37'),
    ('ORG00034', 'Northgate Community Foundation', '0054 Deanna Walk Apt. 998', 'West Williamport', 'MI', '50895', 'Oil west school American training occur could painting may whatever late specific study word base position.', 'https://www.northgatecommunityfo.org', '(037) 788-9255', 'contact@northgatecommunityfo.org', 'Non-Profit', 'Large', 5, FALSE, TRUE, '2025-11-20 04:24:57', '2025-11-24 04:24:57'),
    ('ORG00035', 'Summit Relief Network', '515 Angela Lights', 'Ortizmouth', 'VT', '37744', 'Rich prevent trade their four old center glass whose recognize hot organization.', 'https://www.summitreliefnetwork.org', '(148) 652-8168', 'contact@summitreliefnetwork.org', 'Non-Profit', 'Large', 4, FALSE, TRUE, '2024-06-30 08:17:34', '2024-07-21 08:17:34'),
    ('ORG00036', 'Golden Gate Education Fund', '3322 Kenneth Turnpike Apt. 888', 'Kyleborough', 'AZ', '05448', 'Then peace others child Congress realize person total return analysis hair rest wide particular sell six doctor.', 'https://www.goldengateeducationf.org', '(347) 359-7746', 'contact@goldengateeducationf.org', 'Non-Profit', 'Small', 5, TRUE, FALSE, '2024-11-06 04:17:03', '2026-03-19 04:17:03'),
    ('ORG00037', 'Meadowbrook Food Bank', '0758 Jennifer Path', 'Burchborough', 'KS', '16842', 'Base civil last message store begin treat stage this us increase how hear.', 'https://www.meadowbrookfoodbank.org', '(615) 305-1522', 'contact@meadowbrookfoodbank.org', 'Non-Profit', 'Medium', 2, FALSE, TRUE, '2023-09-08 21:39:44', '2024-10-12 21:39:44'),
    ('ORG00038', 'Hopewell Literacy Project', '9010 Lewis Drive Suite 143', 'Hortonberg', 'TX', '39973', 'Answer information soldier lead book toward others administration middle drop century.', 'https://www.hopewellliteracyproj.org', '(609) 539-6218', 'contact@hopewellliteracyproj.org', 'Non-Profit', 'Medium', 1, FALSE, TRUE, '2026-01-10 23:29:11', '2026-03-07 23:29:11'),
    ('ORG00039', 'Green Valley Health Initiative', '7065 Burgess Knolls', 'New Amyhaven', 'MN', '09356', 'Drop price billion old series card good full poor store range wonder long consider care respond.', 'https://www.greenvalleyhealthini.org', '(704) 303-0548', 'contact@greenvalleyhealthini.org', 'For-profit', 'Medium', 2, TRUE, FALSE, '2024-08-02 13:58:33', '2025-01-17 13:58:33'),
    ('ORG00040', 'Summit Education Fund', '0541 Kim Locks Suite 652', 'Kingborough', 'WY', '65539', 'Happen something entire bar interesting issue yet Congress family bill foreign fast knowledge response coach know language risk treatment.', 'https://www.summiteducationfund.org', '(964) 016-5820', 'contact@summiteducationfund.org', 'For-profit', 'Small', 1, FALSE, TRUE, '2023-12-13 07:26:52', '2025-03-06 07:26:52')
ON CONFLICT (org_id) DO NOTHING;
