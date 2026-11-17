#!/usr/bin/env bash
# Usage: ./load_local.sh [dbname] [path/to/saayam_schema.sql]
# Creates a local Postgres DB from the schema and loads the generated CSVs in FK order.
# Needs psql/createdb/dropdb on PATH and a running local Postgres server.
set -euo pipefail
DB="${1:-saayam_mock}"
SCHEMA_FILE="${2:-saayam_schema.sql}"
SCHEMA_NAME="virginia_dev_saayam_rdbms"
DIR="$(cd "$(dirname "$0")" && pwd)/output"

dropdb --if-exists "$DB"
createdb "$DB"
psql -v ON_ERROR_STOP=1 -q -d "$DB" -c "CREATE SCHEMA $SCHEMA_NAME"

# requests.req_loc / created_loc are PostGIS geometry columns. Use PostGIS if available;
# otherwise load them as text (the generated values are EWKT, e.g. SRID=4326;POINT(-96.8 32.7)).
if psql -q -d "$DB" -c "CREATE EXTENSION IF NOT EXISTS postgis" >/dev/null 2>&1; then
  DDL="$SCHEMA_FILE"; echo "PostGIS found: loading geometry columns as geometry"
else
  DDL="$(mktemp)"; sed 's/public\.geometry(Point,4326)/text/g' "$SCHEMA_FILE" > "$DDL"
  echo "PostGIS not available: loading geometry columns as text"
fi
psql -v ON_ERROR_STOP=1 -q -d "$DB" -f "$DDL"

# Empty field = NULL, quoted "" = empty string (Postgres CSV default), so the two stay distinct.
for t in request_statuses request_priorities request_types request_for request_isleadvol \
         help_categories help_categories_map users requests; do
  cols=$(head -1 "$DIR/$t.csv")
  psql -v ON_ERROR_STOP=1 -q -d "$DB" \
    -c "\copy $SCHEMA_NAME.$t($cols) FROM '$DIR/$t.csv' WITH (FORMAT csv, HEADER true)"
  echo "loaded $t"
done
echo "Done. Try: psql -d $DB -c 'select count(*) from $SCHEMA_NAME.requests'"
