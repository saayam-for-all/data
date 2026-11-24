-- Local copy of the source tables for verifying the requests archive (issue #586).
--
--
-- WHERE EACH PART COMES FROM
--
-- Column types and primary keys come from the schema spreadsheet
-- (database/Saayam_Table.column.names_data.xlsx). Table and column NAMES follow
-- the Task 2 Lambda (data-engineering/src/data_archive_request_data), because
-- the spreadsheet is older than the database the Lambda was written against:
--
--   spreadsheet                      used here (Lambda / data-analytics/sql/requests.csv)
--   -------------------------------  ----------------------------------------------------
--   request                          requests
--   request.req_user_id              requests.creator_id
--   request.last_update_date         requests.last_updated_at
--   request_type                     request_types
--   request_priority                 request_priorities
--   request_status                   request_statuses
--
-- Columns that are NOT in the spreadsheet, typed by assumption:
--   requests.beneficiary_id      varchar(255)  same type as the other user ids
--   requests.lead_volunteer_id   varchar(255)  same type as the other user ids
--   requests.deletion_reason     text
--
-- No foreign keys are declared from requests to the lookup tables, so a request
-- can point at a lookup row that does not exist. That is the state check 5 needs,
-- and the issue implies the live database allows it too.
--
-- Every timestamp is `timestamp without time zone`, as the spreadsheet and the
-- issue state for this schema.
--
-- Verify all of this against the live database when access arrives:
--   SELECT table_name, column_name, data_type
--   FROM information_schema.columns
--   WHERE table_schema = 'virginia_dev_saayam_rdbms'
--     AND table_name IN ('requests', 'request_for', 'request_isleadvol',
--                        'help_categories', 'request_types',
--                        'request_priorities', 'request_statuses')
--   ORDER BY table_name, ordinal_position;

DROP SCHEMA IF EXISTS virginia_dev_saayam_rdbms CASCADE;
CREATE SCHEMA virginia_dev_saayam_rdbms;

CREATE TABLE virginia_dev_saayam_rdbms.requests (
    req_id            character varying(255) PRIMARY KEY,
    creator_id        character varying(255),
    req_for_id        integer,
    req_islead_id     integer,
    req_cat_id        character varying(50),
    req_type_id       integer,
    req_priority_id   integer,
    req_status_id     integer,
    req_loc           character varying(125),
    iscalamity        boolean,
    req_subj          character varying(125),
    req_desc          character varying(255),
    req_doc_link      text,
    audio_req_desc    character varying(255),
    submission_date   timestamp without time zone,
    serviced_date     timestamp without time zone,
    last_updated_at   timestamp without time zone,
    to_public         boolean,
    beneficiary_id    character varying(255),
    lead_volunteer_id character varying(255),
    deletion_reason   text
);

CREATE TABLE virginia_dev_saayam_rdbms.request_for (
    req_for_id        integer PRIMARY KEY,
    req_for           character varying(25),
    req_for_desc      character varying(125),
    last_updated_date timestamp without time zone
);

CREATE TABLE virginia_dev_saayam_rdbms.request_isleadvol (
    req_islead_id     integer PRIMARY KEY,
    req_islead        character varying(15),
    req_islead_desc   character varying(100),
    last_updated_date timestamp without time zone
);

CREATE TABLE virginia_dev_saayam_rdbms.help_categories (
    cat_id   character varying(50) PRIMARY KEY,
    cat_name character varying(100),
    cat_desc character varying(150)
);

CREATE TABLE virginia_dev_saayam_rdbms.request_types (
    req_type_id       integer PRIMARY KEY,
    req_type          character varying(25),
    req_type_desc     character varying(125),
    last_updated_date timestamp without time zone
);

CREATE TABLE virginia_dev_saayam_rdbms.request_priorities (
    req_priority_id   integer PRIMARY KEY,
    req_priority      character varying(25),
    req_priority_desc character varying(125),
    last_updated_date timestamp without time zone
);

CREATE TABLE virginia_dev_saayam_rdbms.request_statuses (
    req_status_id     integer PRIMARY KEY,
    req_status        character varying(25),
    req_status_desc   character varying(125),
    last_updated_date timestamp without time zone
);
