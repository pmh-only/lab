#!/bin/bash
set -euo pipefail

# The official entrypoint invokes this only for a new PGDATA. Never reset roles,
# databases, extensions or schema in an existing database directory on restart.
psql --no-psqlrc --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\set app_password `cat /run/secrets/immich-db/DB_PASSWORD`
BEGIN;
CREATE ROLE immich LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'app_password';
COMMENT ON ROLE immich IS 'lab-immich-bootstrap-v1';
ALTER DATABASE immich OWNER TO immich;
ALTER SCHEMA public OWNER TO immich;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE EXTENSION IF NOT EXISTS vchord CASCADE;
CREATE EXTENSION IF NOT EXISTS earthdistance CASCADE;
ALTER DATABASE immich SET vchordrq.probes = 1;
COMMIT;
SQL
echo "Native Immich database initialized with a dedicated non-superuser owner and supported extensions"
