# Encrypted node file backups

`kopia-backup` is independent of the old, undeployed Kopia web UI. It uses the
private remote `kopia` bucket on pmhraspberry, a bucket-scoped S3 account, and a
fresh native encryption password at Vault `secret/kopia/s3` →
`REPOSITORY_PASSWORD`. Keep an offline recovery copy of this password separate
from the cluster; do not paste it in logs or Git.

Two pinned, node-specific CronJobs cover `/mnt/data` **and** the local-path PVC
root `/var/lib/rancher/k3s/storage`, mounted read-only. They have no Kubernetes
API token, no host network, and are not privileged Pods. Root with only
`DAC_READ_SEARCH` is needed to read files owned by different services. Source
directories must already exist; jobs never create host directories.

Initialize the newly provisioned repository and verify encryption/recovery with:

```sh
python bootstrap/services/kopia_initialize.py
```

This uses a temporary non-root Pod without host mounts, refuses an unmanaged
non-empty bucket, disables automated repository maintenance, and creates,
fully verifies, restores, and byte-compares a non-secret probe. Only that Pod is
deleted; its small encrypted probe snapshot remains.

File schedules begin suspended until their initial real snapshots have passed.
Snapshots are pinned pending a retention review, so no automatic snapshot
expiration is enabled. Each run checks repository metadata and downloads a
sample of file content for verification. A full initial transfer may take hours
over a relayed Tailscale connection; monitor storage capacity.

**Consistency limitation:** live filesystem copies are not application-consistent
database recovery points. Use the independently verified native database dumps
for SQL/MongoDB/ClickHouse recovery, native Raft snapshots for Vault recovery,
and application-specific recovery procedures for live SQLite and object stores.
These jobs do not establish that an entire service can be restored. Kopia's web
UI and SSO are not enabled by this application.
