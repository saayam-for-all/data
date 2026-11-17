#!/usr/bin/env bash
# Usage: ./load_local.sh [dbname] [path/to/saayam_schema.sql]
# Creates a local Postgres DB from the schema and loads the generated CSVs in FK order.
set -euo pipefail
DB="${1:-saayam_mock}"; SCHEMA="${2:-saayam_schema.sql}"; DIR="$(dirname "$0")/output"
dropdb --if-exists "$DB" && createdb "$DB"
psql -v ON_ERROR_STOP=1 -d "$DB" -f "$SCHEMA"
# empty field = NULL, quoted "" = empty string (Postgres CSV default), so the two stay distinct
for spec in "request_statuses" "request_priorities" "request_types" "request_for" "request_isleadvol" \
            "help_categories" "help_categories_map" "users" "requests"; do
  cols=$(head -1 "$DIR/$spec.csv")
  psql -v ON_ERROR_STOP=1 -d "$DB" -c "\copy $spec($cols) FROM '$DIR/$spec.csv' WITH (FORMAT csv, HEADER true)"
done
echo "Loaded into $DB"
