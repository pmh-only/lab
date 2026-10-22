#!/bin/bash
set -euo pipefail

# Mounted as an additional file: preserve and run the image's 10_postgis.sh.
# Official PostgreSQL init scripts only execute for previously empty PGDATA.
psql --no-psqlrc --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\set app_password `cat /run/secrets/track-db/DATABASE_PASSWORD`
BEGIN;
CREATE ROLE dawarich LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'app_password';
COMMENT ON ROLE dawarich IS 'lab-track-bootstrap-v1';
ALTER DATABASE dawarich OWNER TO dawarich;
ALTER SCHEMA public OWNER TO dawarich;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
COMMIT;
SQL
echo "Native PostGIS initialization retained; application has a dedicated non-superuser database owner"
