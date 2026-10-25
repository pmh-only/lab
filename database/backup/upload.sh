#!/bin/sh
set -eu
umask 077
export AWS_EC2_METADATA_DISABLED=true
cd /backup
test -s SHA256SUMS
sha256sum -c SHA256SUMS > /dev/null
RUN_ID="$(head -n 1 started-at)-$(tail -n 1 started-at)"
DESTINATION="s3://dbdump/$BACKUP_NAME/$RUN_ID"
aws --endpoint-url "$S3_ENDPOINT_URL" s3 cp /backup/ "$DESTINATION/" --recursive --quiet
# Read back every artifact before publishing the completion marker. S3 ETags
# are not reliable content hashes for multipart uploads.
while read -r expected file; do
  aws --endpoint-url "$S3_ENDPOINT_URL" s3 cp "$DESTINATION/${file#./}" /backup/readback --quiet
  actual="$(sha256sum /backup/readback | cut -d ' ' -f 1)"
  test "$actual" = "$expected"
  rm /backup/readback
done < SHA256SUMS
printf 'format=lab-db-backup-v1\nengine=%s\nsha256=%s\n' "$ENGINE" "$(sha256sum SHA256SUMS | cut -d ' ' -f 1)" > /backup/_COMPLETE
aws --endpoint-url "$S3_ENDPOINT_URL" s3 cp /backup/_COMPLETE "$DESTINATION/_COMPLETE" --quiet
echo "Backup complete and read-back verified: $BACKUP_NAME/$RUN_ID"
