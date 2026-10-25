#!/bin/sh
set -eu
umask 077
export AWS_EC2_METADATA_DISABLED=true
cd /backup
sha256sum -c SHA256SUMS > /dev/null
RUN_ID="$(head -n 1 started-at)-$(tail -n 1 started-at)"
DESTINATION="s3://vault/$RUN_ID"
aws --endpoint-url "$S3_ENDPOINT_URL" s3 cp /backup/ "$DESTINATION/" --recursive --quiet
aws --endpoint-url "$S3_ENDPOINT_URL" s3 cp "$DESTINATION/vault.snap" /backup/readback --quiet
test "$(sha256sum /backup/readback | cut -d ' ' -f 1)" = "$(sha256sum vault.snap | cut -d ' ' -f 1)"
rm /backup/readback
printf 'format=lab-vault-raft-v1\nfullRestoreTested=false\n' > _COMPLETE
aws --endpoint-url "$S3_ENDPOINT_URL" s3 cp _COMPLETE "$DESTINATION/_COMPLETE" --quiet
echo 'Vault sealed Raft snapshot uploaded and read-back verified; unseal recovery is not tested'
