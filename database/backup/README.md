# Remote database backups

Backups go over Tailscale to RustFS on
`pmhraspberry.tailscale.svc.cluster.local:9000`, in the private `dbdump` bucket.
HTTP is carried inside Tailscale's encrypted tunnel. Database dumps themselves
are not client-side encrypted; access to the Raspberry Pi storage must be secured.

The database backup S3 identity can list, write, and read this bucket, but cannot
delete backup data. Its only deletion permission is
`dbdump/clickhouse/*/.lock`, required to finalize native ClickHouse backups.
The remote administrator credential stays in Vault at
`secret/backup/rustfs-admin` and is never mounted in backup Pods. Velero and Kopia
have different identities restricted to their respective buckets.

## Jobs and completion

The base starts CronJobs **suspended**; the engine overlays enable the reviewed
schedules. PostgreSQL, MySQL, MongoDB, and Immich passed isolated restore checks.
ClickHouse's native backup succeeded; its full restore check was canceled by
the user. The user explicitly approved enabling its schedule without resuming
restore testing. Daily times are Asia/Seoul:

| Job | Time | Format |
| --- | --- | --- |
| `backup-pgsql` | 03:00 | PostgreSQL 18 globals and per-database custom dumps |
| `backup-mysql` | 03:20 | MySQL 8.4 all-database SQL, routines, events, triggers |
| `backup-mongo` | 03:40 | MongoDB compressed native archive, dedicated `backup` role |
| `backup-clickhouse` | 04:00 | Native ClickHouse `BACKUP ALL TO S3` |
| `backup-immich` | 04:20 | Immich's pinned PostgreSQL 14 client and extensions |

Each run writes a unique UTC timestamp/UUID prefix. Logical dumps have SHA-256
manifests and are downloaded again for checksum verification before `_COMPLETE`
is written. ClickHouse writes its marker only after native `BACKUP_CREATED`.
Partial runs are not recoverable backup sets and must not be selected for restore.
No lifecycle expiration, object pruning, or remote cleanup is configured here.

Jobs use temporary storage, do not mount live PVCs, and do not restart database
Deployments. Reloader is explicitly disabled for these Jobs and CronJobs so a
Secret update cannot start extra runs or bypass a suspended schedule.

Logical exports are consistent at each engine's supported level: PostgreSQL
per-database snapshots, MySQL transactional tables, MongoDB collection exports
(this standalone server has no oplog point-in-time snapshot), and native
ClickHouse snapshots. They are not one atomic snapshot across all applications.
Immich media, S3 application objects, and other filesystem data require separate
file/object backups; a database dump alone is not full application recovery.

## Verification

With a private loopback relay to the remote endpoint on port 19000:

```sh
python bootstrap/services/backup_s3.py
python bootstrap/services/backup_restore.py mongo mysql pgsql clickhouse immich
```

The restore helper selects only completed sets, creates a unique temporary
namespace, denies ingress and production-database egress, and restores to fresh
local databases using the pinned native server images. It has no production
database credentials, live PVCs, hostPaths, Services, or Kubernetes API tokens.
Only the namespace it created is deleted afterward; remote backups are retained.
This is an actual native import check, not merely a successful upload. It does
not constitute a complete application recovery or cross-service recovery drill.

Velero follows its original manifests: Kubernetes resources plus native PVC
filesystem backups through the node agent. CSI/cloud volume snapshots remain
disabled as in the original YAML; privileged Pods are not requested. The native
Velero UI and controller retain their original management permissions. These
PVC file copies do not replace the engine-native database dumps above.
