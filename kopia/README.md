# Backup console

`https://backup.pmh.so` redirects to `https://backup.pmh.codes`, the canonical
Kopia console. The UI is separate from the `kopia-backup` file workers.

Reconcile its dedicated identities with:

```sh
python bootstrap/services/kopia_ui.py
```

The Authentik application permits only authenticated, active internal superusers.
Its confidential OIDC client has one strict callback:
`https://backup.pmh.codes/oauth2/callback`. Native policy evaluation verifies an
existing administrator is allowed and an existing non-administrator is denied.
Do not recreate this application with only the generic OIDC helper: the console
also requires its admin-only application policy binding.

The UI connects read-only to the **existing** encrypted remote repository. Its
separate S3 identity can only list and read the `kopia` bucket; writes and deletes
are rejected. No repository is initialized and no live data/PVC is mounted in
the console. Existing backup worker keys, policies, and repository password stay
unchanged. Console Vault access uses a separate role, not the workers' reader.

Envoy handles OIDC. Inside the Pod, a minimal NGINX proxy supplies a secret-held
Basic credential to Kopia's password-protected, loopback-only HTTP listener.
Neither the browser nor Git receives that credential. NetworkPolicy allows only
the main Envoy data plane to reach the proxy. Anonymous network listeners,
disabled CSRF, and the dangerous unauthenticated-server flag are not used.

The console is for viewing/browsing backups. Restore-to-live-host and deletion
are deliberately not enabled. Readable repository objects and a successful UI
login do not establish that every service has a complete, tested recovery point.
File snapshots and database backup completion are tracked separately.
