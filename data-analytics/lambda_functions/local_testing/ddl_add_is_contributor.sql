-- Migration: add is_contributor flag to the organizations table.
-- Needed by the Organization Analytics API (#228) for contributor distribution
-- and top-contributor metrics. Mirrors the existing is_collaborator boolean.
--
-- Raise this as a SEPARATE PR against saayam-for-all/database, and also update
-- ddl/Tables/ddl_organizations.sql to include the column.

ALTER TABLE virginia_dev_saayam_rdbms.organizations
    ADD COLUMN IF NOT EXISTS is_contributor BOOLEAN;

COMMENT ON COLUMN virginia_dev_saayam_rdbms.organizations.is_contributor
    IS 'TRUE if the organization contributes resources/funding to Saayam.';
