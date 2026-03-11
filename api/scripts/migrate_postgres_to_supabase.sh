#!/usr/bin/env bash
set -euo pipefail

SOURCE_DB_URL="${SOURCE_DATABASE_URL:-${1:-}}"
TARGET_DB_URL="${SUPABASE_DATABASE_URL:-${2:-}}"
SCHEMA_NAME="${MIGRATION_SCHEMA:-public}"

if [[ -z "${SOURCE_DB_URL}" || -z "${TARGET_DB_URL}" ]]; then
  echo "Usage:"
  echo "  SOURCE_DATABASE_URL=<postgres-url> SUPABASE_DATABASE_URL=<postgres-url> $0"
  echo "or"
  echo "  $0 <source_postgres_url> <supabase_postgres_url>"
  exit 1
fi

if [[ "${SOURCE_DB_URL}" != postgres://* && "${SOURCE_DB_URL}" != postgresql://* ]]; then
  echo "SOURCE_DATABASE_URL must be a postgres connection string."
  exit 1
fi

if [[ "${TARGET_DB_URL}" != postgres://* && "${TARGET_DB_URL}" != postgresql://* ]]; then
  echo "SUPABASE_DATABASE_URL must be a postgres connection string."
  echo "Do not use the dashboard URL (https://<project>.supabase.co)."
  exit 1
fi

for tool in pg_dump pg_restore psql; do
  if ! command -v "${tool}" >/dev/null 2>&1; then
    echo "Missing required tool: ${tool}"
    echo "Install PostgreSQL client tools first."
    exit 1
  fi
done

DUMP_FILE="$(mktemp "${TMPDIR:-/tmp}/forecasthub-migrate.XXXXXX.dump")"
trap 'rm -f "${DUMP_FILE}"' EXIT

echo "Dumping source database schema='${SCHEMA_NAME}'..."
pg_dump \
  --verbose \
  --format=custom \
  --no-owner \
  --no-privileges \
  --schema="${SCHEMA_NAME}" \
  --dbname="${SOURCE_DB_URL}" \
  --file="${DUMP_FILE}"

echo "Restoring into Supabase target schema='${SCHEMA_NAME}'..."
pg_restore \
  --verbose \
  --clean \
  --if-exists \
  --exit-on-error \
  --no-owner \
  --no-privileges \
  --schema="${SCHEMA_NAME}" \
  --dbname="${TARGET_DB_URL}" \
  "${DUMP_FILE}"

echo "Comparing base table counts in schema='${SCHEMA_NAME}'..."
SOURCE_TABLES="$(psql "${SOURCE_DB_URL}" -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema='${SCHEMA_NAME}' AND table_type='BASE TABLE';")"
TARGET_TABLES="$(psql "${TARGET_DB_URL}" -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema='${SCHEMA_NAME}' AND table_type='BASE TABLE';")"
echo "Source tables: ${SOURCE_TABLES}"
echo "Target tables: ${TARGET_TABLES}"

if [[ "${SOURCE_TABLES}" != "${TARGET_TABLES}" ]]; then
  echo "Warning: table counts differ. Inspect schemas manually before cutover."
else
  echo "Schema/table count check passed."
fi

echo "Migration complete."
