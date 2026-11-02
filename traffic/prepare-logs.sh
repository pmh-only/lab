#!/bin/sh
set -eu
# Keep the raw log and any old user-maintained GeoIP datasets untouched.
umask 027
touch /logs/all.log
marker=/logs/.lab-goaccess-derived-log-v1
value='lab-goaccess-derived-log-v1;source=all.log'
if [ -e /logs/all.safe.log ] && { [ ! -f "$marker" ] || [ "$(cat "$marker")" != "$value" ]; }; then
  echo 'Existing derived report log has no matching ownership marker; refusing replacement' >&2
  exit 1
fi
umask 077
echo "$value" > "$marker"
umask 027
# Rebuild only the managed derived cache through native Fluent Bit backfill.
: > /logs/all.safe.log
