# Original Velero UI and PVC backup configuration

`apps/velero.yml` contains the original three applications: Velero, Velero UI,
and its HTTPRoute/Secret configuration. `velero.pmh.codes` serves the native
OTWLD Velero UI with its original generic OAuth login, not a replacement page.
The new client secret and required JWT signing secret are kept in Vault at
`velero/velero-ui-secrets`. Reconcile them with `bootstrap/services/velero_ui.py`.

Velero's original settings are restored: `deployNodeAgent: true`,
`defaultVolumesToFsBackup: true`, a 12-hour filesystem backup timeout, the daily
`backup` schedule, 30-day retention, and 16 parallel file uploads. Volume
snapshots remain disabled as in the original manifest; PVC contents use native
filesystem backup. The node agent does not request privileged mode.

Velero's internal encrypted filesystem-backup repository uses its native
`velero-repo-credentials` Secret, synchronized from Vault rather than a default
shared password. Existing object-store credentials and all remote backups are
preserved. Native UI/RBAC control behavior is retained for Authentik admins.
Running-database file copies do not replace backpack's database dumps.
