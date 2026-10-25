# Kopia server

`https://backup.pmh.so` redirects to `https://backup.pmh.codes`, the canonical
Kopia server from the original manifests: one Deployment, one persistent
`kopia-pvc`, and the read-only `/mnt/data` host mount exposed at `/data`.
There are no separate file-backup CronJobs or read-only console replicas.

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

An init container connects the **existing** encrypted remote repository using
the already provisioned bucket identity and repository password. It never
initializes or resets the repository. Configuration, cache, logs, and temporary
files use the original PVC subpaths. The server is pinned to `pmhoci`; the user
confirms `/mnt/data` contains the same files on both nodes, so only one server
backs it up. The local-path PVC root is not mounted into Kopia. DB backups
remain separate; Velero handles PVC filesystem backups.

Envoy retains the original OIDC layer. Kopia itself retains its original native
password authentication (`pmh_only@pmh.codes` and Vault `kopia/kopia-secret` →
`ADMIN_PASSWORD`). Its encryption password is unchanged. No password-free
listener, disabled CSRF, proxy credential injection, or repository read-only
restriction is used. NetworkPolicy limits ingress to the main Envoy data plane.

Snapshot management and policies use the original native Kopia server/UI.
Existing remote data, including earlier checkpoints, is preserved. A successful
login alone does not establish a complete or tested recovery point. No live
database restores are performed by this deployment.
