# Argo CD access

Anonymous visitors can view applications, resource manifests, configuration and
AppProjects at <https://argo.pmh.codes>. This intentionally exposes application
metadata and configuration; do not put credentials in plaintext manifests.
Public status badges are enabled separately with `statusbadge.enabled: "true"`,
serving `/api/badge?name=<app>` for the repository README.

The custom default `role:public` grants only `applications/get` and `projects/get`.
It does not grant logs, terminal sessions, sync, resource actions, create, update,
delete, or access to repository/cluster/account administration. Do not replace it
with the built-in `role:readonly`, which also grants log access. Unspecified
permissions are denied; explicit denies on the default role would also affect
authenticated administrators. Authentik administrators and the recovery local
admin retain their existing full access.

## GitHub deployment notifications

Argo CD Notifications reports to `pmh-only/lab` using GitHub App `5488198`.
The App must be installed on **pmh-only**, with access to **lab** and repository
permissions **Commit statuses: read/write** and **Deployments: read/write**.
Set its installation ID in both `notifications.yml` and
`bootstrap/services/argocd_notifications.py` when changing installations.

Import the downloaded GitHub App PEM without committing it:

```sh
chmod 600 /path/to/argocd.pem
python bootstrap/services/argocd_notifications.py /path/to/argocd.pem
```

Use the dependencies in `bootstrap/services/requirements.txt` and an existing
non-root Vault userpass operator login, as with the other bootstrap helpers.
The importer verifies GitHub identity and repository access before writing
`secret/argocd/notifications-github`. It refuses to replace an existing key.
Vault Secrets Operator syncs the key to `argocd-notifications-secret` using a
dedicated service account and read-only Vault policy. The PEM never belongs in Git.

The global subscription includes only operations with a `lab` source. For
multi-source applications it selects the resolved `lab` SHA, not a chart version.

- `continuous-delivery/<app>` is pending while syncing or progressing, success
  once synced and healthy, and failure for failed/error syncs or degraded apps.
- Terminal results create GitHub deployments in `production/<app>` with an Argo
  CD log link. Pending notifications do not create duplicate deployment records.
- Notifications are deduplicated per sync attempt, allowing retries of the same
  SHA. Existing app states are reported when the subscription is first enabled.
- Deployments disable auto-merge and required-context checks: notifications report
  an already attempted deployment, rather than requesting a new deployment.

Sync the `argocd-access` Application after committing the manifests. No per-app
subscription annotations are needed.

## Discord sync notifications

All applications also send Sync **Running**, **Succeeded**, and **Failed/Error**
events to a Discord incoming webhook, independently of the GitHub deployment
subscription. Success means the sync operation succeeded; it does not wait for
Healthy. Events are deduplicated by sync attempt and phase, including retries of
the same SHA. A fixed activation cutoff in `trigger.discord-sync` prevents an
initial flood of historical operation notifications.

Import the explicitly supplied webhook URL from a protected local file:

```sh
chmod 600 /path/to/discord-webhook.txt
python bootstrap/services/argocd_discord.py /path/to/discord-webhook.txt
```

The helper validates the incoming webhook via a read-only Discord request, then
CAS-merges `discord-webhook-url` into the existing Vault notification credential
at `secret/argocd/notifications-github`. The GitHub private key, Vault reader policy,
and existing Kubernetes secret destination are preserved. Re-importing the same
webhook is a no-op; a differing URL requires a coordinated rotation. Notifications
reload the synced secret automatically; the URL is never stored in Git.

Messages include app name, sync phase, namespace, operation start time, and an
Argo CD link. They do not include logs, raw error messages, or manifest contents.
Mentions are disabled to avoid accidental mass pings.
