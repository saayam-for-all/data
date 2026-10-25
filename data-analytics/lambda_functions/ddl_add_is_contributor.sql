-- Migration: add is_contributor flag to organizations
-- Required by the Organization Analytics API (contributor distribution,
-- top contributor organizations). Follows the same pattern as is_collaborator
-- (see branch sanobar_113_add_collaborator_flag).
--
-- To be raised as a separate PR against saayam-for-all/database
-- (ddl/Tables/ddl_organizations.sql should also be updated to include the column).

ALTER TABLE virginia_dev_saayam_rdbms.organizations
    ADD COLUMN IF NOT EXISTS is_contributor BOOLEAN;

COMMENT ON COLUMN virginia_dev_saayam_rdbms.organizations.is_contributor
    IS 'TRUE if the organization contributes resources/funding to Saayam.';
