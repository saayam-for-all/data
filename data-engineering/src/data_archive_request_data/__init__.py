"""Data_ArchiveRequestData: archive the requests table to S3 as one enriched table.

Issue #574: export a single enriched requests table instead of six separate
tables, replacing reference ids with readable values from the referenced tables.
"""

LAMBDA_NAME = "Data_ArchiveRequestData"
