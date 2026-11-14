# Cap

`https://cap.pmh.codes` serves Cap v4 and its dashboard. A dedicated, persistent
Valkey holds keys, sessions and widget assets; DuckDB holds analytics on a separate
PVC. Both images are digest-pinned and support the cluster's ARM64 nodes.

`authentik/blueprints/cap.yaml` embeds the password and interactive CAPTCHA in the
identification form of `lab-internal-authentication`. The server verifies the
single-use CAPTCHA **before checking the password**. Invalid credentials or MFA
restart the entire flow without retaining context, requiring a new CAPTCHA.
Direct Discord source flows are unchanged.
`default-authentication-flow` first presents **Continue with Internal** and
**Continue with Discord** as direct navigation buttons, without radios or an
extra Continue step. Fixed same-origin links open the native child flows and
preserve the original, HTML-escaped `next`/OIDC query.
The internal flow has its own identification stage and no source buttons.
The Discord flow uses native source-only identification (no password/CAPTCHA),
so authentik constructs its OAuth URL, state and return path as usual.
The shared built-in identification stage keeps its Discord source unchanged.
`login-choice.yaml` removes objects from the earlier selector experiment.
The selector's button styling is CSS-only in `authentik/branding/theme.css`;
`branding-css.yaml` reconciles it into the existing brand via a ConfigMap-backed
worker environment value. Native link/keyboard navigation and routing stay intact.
Existing HTTP sessions can retain a pickled plan from before this change.
After upgrading from the previous flow, run
`authentik/migrate-pending-login-plans.py` to preview and selectively clear only
obsolete unauthenticated entry plans. It preserves authenticated sessions and
the original return query. New-browser-only tests do not cover this migration.
Verification uses the internal Cap service with JSON; browsers use the public
HTTPS endpoint and self-hosted widget. A small Git-managed module served by
authentik styles the widget dark and sizes its iframe without scrollbars.
Do not put the CAPTCHA endpoints behind
authentik authentication: that would create a login dependency loop.

## First deployment

Complete the Cap bootstrap **before publishing the authentik changes**. The
authentik worker deliberately requires its secret, rather than importing a stage
with an empty verification key. Keep an existing administrator session open when
enabling CAPTCHA.

1. Log in to Vault with permission to create the Cap policy/role and write the
   two KV paths below. Never commit credentials.

   ```sh
   export VAULT_ADDR=https://vault.pmh.codes
   vault login
   vault policy write cap - <<'EOF'
   path "secret/data/cap/cap-secrets" {
     capabilities = ["read"]
   }
   EOF
   vault write auth/kubernetes/role/cap \
     bound_service_account_names=vault-auth \
     bound_service_account_namespaces=cap \
     audience=vault token_policies=cap token_ttl=1h
   python -c 'import json,secrets; print(json.dumps({"ADMIN_KEY": secrets.token_hex(24)}))' \
     | vault kv put secret/cap/cap-secrets -
   ```

   Ensure the existing `authentik` Vault role's policy permits reading
   `secret/data/authentik/cap` (preserve its existing policies).

2. Commit/push **only** `apps/cap.yml` and `cap/` first. Let the existing app-of-apps
   create and synchronize Cap; do not use `kubectl apply` to deploy the workload.

3. Open the Cap dashboard and sign in using `ADMIN_KEY` from Vault. Under
   **Instance settings**:
   - **Visitor location / Your proxy or CDN**: use `X-Forwarded-For`.
     The network policy restricts ingress to the gateway and authentik.
   - **Widget files**: enable serving files from this server, using the versions
     bundled with the pinned image. Wait for the downloads to complete.
   - Create a site key named `authentik`, with allowed origin
     `https://auth.pmh.codes`. Copy its site key and secret.

4. Store the integration values in Vault. Set the two variables privately in
   your shell (do not paste secrets into tracked files or commands in shell
   history).

   ```sh
   read -r -p 'Cap site key: ' CAP_SITE_KEY
   read -r -s -p 'Cap secret key: ' CAP_SECRET_KEY
   export CAP_SITE_KEY CAP_SECRET_KEY
   python - <<'PY' | vault kv put secret/authentik/cap -
   import json, os
   key = os.environ["CAP_SITE_KEY"]
   print(json.dumps({
       "AUTHENTIK_CAP_ENDPOINT": f"https://cap.pmh.codes/{key}/",
       "AUTHENTIK_CAP_SECRET_KEY": os.environ["CAP_SECRET_KEY"],
       "AUTHENTIK_CAP_VERIFY_URL":
           f"http://cap-service.cap.svc.cluster.local:3000/{key}/siteverify",
   }))
   PY
   unset CAP_SITE_KEY CAP_SECRET_KEY
   ```

5. Check that `/health`, `/assets/widget.js` and `/assets/cap_wasm_bg.wasm`
   return HTTP 200 over public HTTPS. Then commit/push the `authentik/` changes.
   Vault Secrets Operator supplies the worker's environment; the mounted
   blueprint creates the stage and flow binding.

## Verification

```sh
kubectl get applications -n argocd cap authentik
kubectl get pods,pvc,httproute,vaultstaticsecret -n cap
kubectl get vaultstaticsecret authentik-cap -n authentik
kubectl rollout status deployment/authentik-worker -n authentik
curl --fail https://cap.pmh.codes/health
curl --fail --output /dev/null https://cap.pmh.codes/assets/widget.js
```

In a private browser window, confirm the login form presents password and Cap,
valid solves allow password verification, invalid tokens fail, and existing MFA
still runs. Invalid passwords and MFA must restart the flow with a new CAPTCHA.
A Cap outage
must fail closed. Do not claim deployment complete from manifest validation alone.

`authentik/tests/cap-guard.py` checks the live blueprint, retry actions and server
verification order with mocked credentials. Run it using the command in its
docstring; it does not attempt passwords against real accounts or alter MFA data.

## Recovery and updates

- Preserve both PVCs and the Vault values. Losing Valkey loses site keys.
- Changing `ADMIN_KEY` makes encrypted site secrets unreadable; coordinate a
  Cap site-secret reset and Vault integration update instead of rotating it alone.
- Update image digests through Git review; do not silently follow `latest`.
- To disable CAPTCHA, set the identification stage's `captcha_stage` to `null`
  in its blueprint and sync. Removing the blueprint file does not undo imported
  settings. For emergency recovery use `ak shell` through Kubernetes access and
  reconcile the same change in Git.
