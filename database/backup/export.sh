#!/bin/sh
# One-shot, fail-closed exports using each server's own pinned client image.
set -eu
umask 077
cd /backup
date -u +%Y%m%dT%H%M%SZ > started-at
cat /proc/sys/kernel/random/uuid >> started-at
case "$ENGINE" in
  pgsql)
    export PGPASSWORD="$DATABASE_PASSWORD"
    pg_dumpall -h "$DATABASE_HOST" -U "$DATABASE_USER" --globals-only --file=globals.sql
    psql -X -h "$DATABASE_HOST" -U "$DATABASE_USER" -d postgres -At -v ON_ERROR_STOP=1 \
      -c 'SELECT datname FROM pg_database WHERE datallowconn AND NOT datistemplate ORDER BY datname' > databases
    while IFS= read -r database; do
      case "$database" in ''|*[!a-zA-Z0-9_-]*) echo 'Unsupported database name; backup aborted' >&2; exit 1;; esac
      pg_dump -h "$DATABASE_HOST" -U "$DATABASE_USER" -Fc --create --file="$database.dump" "$database"
    done < databases
    test -s databases
    ;;
  mysql)
    export MYSQL_PWD="$DATABASE_PASSWORD"
    mysqldump -h "$DATABASE_HOST" -u "$DATABASE_USER" \
      --all-databases --single-transaction --quick --routines --events --triggers \
      --hex-blob --set-gtid-purged=OFF --no-tablespaces --column-statistics=0 > all-databases.sql
    test -s all-databases.sql
    ;;
  mongo)
    mongodump --host="$DATABASE_HOST" --username="$DATABASE_USER" \
      --password="$DATABASE_PASSWORD" --authenticationDatabase=admin \
      --archive=all-databases.archive.gz --gzip > /backup/export.log 2>&1 || {
        echo 'MongoDB export failed; credential-bearing output suppressed' >&2; exit 1;
      }
    # Collection names are not needed in backup job logs.
    rm /backup/export.log
    test -s all-databases.archive.gz
    ;;
  *) echo 'Unknown database engine' >&2; exit 1;;
esac
# Only fully successful exports reach the uploader init-container barrier.
printf '%s\n' "$ENGINE" > engine
find . -maxdepth 1 -type f ! -name SHA256SUMS -exec sha256sum {} + > SHA256SUMS
echo 'Native export completed'
