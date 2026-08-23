-- Run against saayam_local
-- Adds is_contributor column locally for testing (not yet in real DDL per task note,
-- but new task spec requires total_contributors as a real KPI, so we add it for local testing)

ALTER TABLE virginia_dev_saayam_rdbms.organizations
    ADD COLUMN IF NOT EXISTS is_contributor BOOLEAN;
