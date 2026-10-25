#!/bin/sh
set -eu
umask 077
export AWS_EC2_METADATA_DISABLED=true
cd /backup
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$(cat /proc/sys/kernel/random/uuid)"
DESTINATION="$S3_ENDPOINT_URL/dbdump/clickhouse/$RUN_ID"
# Credentials stay in private temporary files, not process arguments or logs.
printf 'user = "%s:%s"\n' "$DATABASE_USER" "$DATABASE_PASSWORD" > curl.conf
printf "BACKUP ALL TO S3('%s', '%s', '%s')\n" "$DESTINATION" "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY" > request.sql
if ! curl --fail --silent --show-error --connect-timeout 15 --max-time 10800 \
  --config curl.conf --data-binary @request.sql \
  "http://$DATABASE_HOST:8123/" -o result 2> error; then
  echo 'Native ClickHouse backup failed; response suppressed' >&2
  exit 1
fi
grep -q BACKUP_CREATED result || { echo 'Native backup did not complete' >&2; exit 1; }
rm curl.conf request.sql error
printf 'format=lab-clickhouse-native-v1\n' > _COMPLETE
cat result >> _COMPLETE
aws --endpoint-url "$S3_ENDPOINT_URL" s3 cp _COMPLETE "s3://dbdump/clickhouse/$RUN_ID/_COMPLETE" --quiet
echo "Native ClickHouse backup completed: clickhouse/$RUN_ID"
