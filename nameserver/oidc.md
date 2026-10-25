# Technitium console SSO

The console at `https://names.pmh.codes` uses native OIDC with Authentik and the
exact callback `https://names.pmh.codes/sso/callback`. Local administrator login
is retained; SSO does not replace DNS API accounts or DNSSEC keys.

Only active, internal Authentik superusers receive `roles: [lab-technitium-admins]`.
Technitium maps that role to its local `Administrators` group. Automatic account
provisioning is restricted to mapped identities; ordinary logins get no access.

Reconcile using the existing non-root Vault operator login:

```sh
python bootstrap/services/technitium_oidc.py
```

The client secret is kept at `secret/nameserver/technitium-oidc` and in
Technitium's native persisted authentication configuration. It is not put in Git
or mounted into DNS pods. The namespace's existing Vault reader policy is not
changed. Native cluster synchronization distributes authentication settings.
Only the web service may restart; DNS pods are not restarted by this helper.
