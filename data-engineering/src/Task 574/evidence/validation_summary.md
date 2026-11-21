# Task 574 local validation

Generated: 2026-11-03T20:08:54.991077+00:00

Synthetic data on SQLite; S3 replaced with a local file sink. The real lambda_handler and export SQL were executed. No AWS calls.

- Source requests selected: **12**
- Exported requests: **12**
- Distinct exported IDs: **12**
- Duplicate requests: **0**
- Source unchanged: **True**
- Source rows with null timestamps: **1**
- Null timestamps excluded by selection: **0**
- All source columns, raw IDs and descriptions retained; six readable labels added.
- All six lookups use LEFT JOIN; no user-table join or category-tree join.

| Reference | Matched | Null retained | Unmatched retained | Matched but null label |
|---|---:|---:|---:|---:|
| req_cat_id | 10 | 1 | 1 | 0 |
| req_for_id | 10 | 1 | 1 | 0 |
| req_islead_id | 10 | 1 | 1 | 0 |
| req_type_id | 10 | 1 | 1 | 1 |
| req_priority_id | 10 | 1 | 1 | 0 |
| req_status_id | 10 | 1 | 1 | 0 |

CSV SHA-256: `72b7c5aeeee50079dec190313b53a88f494e73b13b7abdb168027f5a48d0cde5`

The null and unmatched lookup rows are deliberately invalid relative to the production FK/NOT NULL constraints. They demonstrate preservation under dirty input.

Task 573 historical baseline (221 dev requests, 2026-10-24): unmatched = 0 for all nine references; beneficiary_id null = 8; lead_volunteer_id null = 218; all others = 0. Those are published schema counts, not results from this synthetic run.

Production PostgreSQL/PostGIS, live S3, deployment, and retirement of the old Lambda have not been exercised. Keep the previous Lambda until deployment validation succeeds.
