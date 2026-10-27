# Professional to Community

The server uses the ARM64 Community image on the validated 12.0 branch.
Do not combine an edition change with an automatic major-version upgrade.
The image updater therefore accepts only `12.0.x-arm` for the main server.

## Safety and validation

Before cutover, take a consistent dump of `ccnet_db`, `seafile_db`, and
`seahub_db`, followed by an archive of the shared Seafile directory. Include
SeaDoc and notification persistent state. Verify gzip/tar readability and SHA-256
checksums. Migration backups live under `/mnt/data/seafile-migration-backups/`
in private directories; they contain credentials and private user data and must
not be published or committed.

Rehearse against separately restored databases and a separate data directory.
Use a dedicated database identity granted access only to those copies. Isolate
cache, notifications, and outbound mail too.
The event-service database in `seafevents.conf` must also use the isolated
identity/database, with background jobs disabled during rehearsal.

Check Community detection, existing
accounts/admin flags/libraries, new-user registration beyond three accounts,
Discord quota assignment through the native OAuth callback, file write/read,
and native read-only `seaf-fsck` before switching production.

For cutover, temporarily suspend this application's automatic synchronization,
quiesce Seafile/SeaDoc/notifications, and take a final cold backup. Never import
the fresh-install schema over existing databases. The existing initialization
marker preserves native state. CE's missing `ccnet.conf` database section is
generated from the existing app database identity, without mounting DB root.
Unavailable Pro search and audit are disabled in `seafevents.conf`; their other
settings are retained for rollback.
The native same-branch minor-update script updates the version/media symlinks.

## Permissions and quotas

OAuth provider identity, subject mapping, client credentials, library ownership,
and native administrator flags stay unchanged. Pro-only database tables and
`pro-data` are retained rather than deleted.

Before cutover, match existing Discord users through their immutable authentik
OAuth subjects. Materialize a native per-user quota no greater than 10 GB and
convert their former quota-only custom role to `default`. Do not change staff
flags, primary administrator quota, or other users' limits.

New Discord users are handled automatically by the native OAuth role hook and
`seahub_discord_quota.DiscordQuotaMiddleware`. It applies the per-user quota
before completing login and fails closed if assignment cannot be verified.
It does not depend on Pro-only role quota RPCs. See `QUOTAS.md`.

Elasticsearch is scaled to zero; its deployment and protected PVC remain for
rollback. Memcached, SeaDoc, notification services, and PMH Drive branding remain.

## Rollback

Preserve both preflight and cold backups plus their checksums. If validation
fails before admitting new writes, stop the Community services and restore the
matching data/configuration and all three databases as one consistent snapshot,
then restore the previous Pro image. Do not blindly restore databases after
users have begun creating new files/accounts: first reconcile those new writes.
Only re-enable automatic synchronization after the desired edition and live
state agree. Temporary rehearsal resources are separate from production and may
be removed after validation; never remove the migration backups as cleanup.

Run quota regression tests with:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s seafile/tests
```
