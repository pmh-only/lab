# GHCR webhook

Image Updater accepts signed GitHub Container Registry package notifications at:

```text
https://update.pmh.codes/webhook?type=ghcr.io
```

Before syncing:

1. Create the Vault KV v2 secret at `secret/argocd/image-updater-webhook`
   with a randomly generated `webhook.ghcr-secret` field. Allow the existing
   `image-updater` Vault role's policy to read
   `secret/data/argocd/image-updater-webhook`.
2. Ensure `update.pmh.codes` resolves to the existing public edge. The gateway's
   wildcard certificate already covers this hostname.
3. In the GitHub repository or organization that publishes the GHCR images, add
   a webhook using the URL above, content type `application/json`, the same
   secret, and the **Packages** event. Keep SSL verification enabled.

The receiver handles `package` events with action `published` for container
packages; GitHub's initial `ping` is not supported by this handler. Check a real
package publication delivery to verify it. Only images already managed by an
`ImageUpdater` resource are updated, using their existing update strategies.

The Vault secret is synced to `argocd-image-updater-webhook` in `argocd` and is
required for controller startup. Secret rotation restarts the controller. Public
TLS terminates at the existing edge; only the `envoy-gateway-system` namespace
can reach the internal HTTP webhook port. The existing two-minute polling remains enabled as
a fallback.
