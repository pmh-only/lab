# Discord login

- OAuth callback: `https://auth.pmh.codes/source/oauth/callback/discord/`
- Required Discord guild: `541782241131495434`
- authentik group: `discord` (not an administrator group)
- Vault KV v2 mount/path: `secret/authentik/discord-oauth`
- Keys: `AUTHENTIK_DISCORD_CLIENT_ID`, `AUTHENTIK_DISCORD_CLIENT_SECRET`

The Vault Kubernetes role `authentik` uses the `lab-authentik` policy. Its
required read permissions are in `vault-policy.hcl`; this policy is managed
separately from Kustomize.

The worker discovers `blueprints/discord.yaml` through a generated ConfigMap.
The source requests `guilds.members.read` in addition to Discord's default
`identify email` scopes. Guild membership is checked against Discord on every
OAuth callback; 404 means non-member and other API failures stop login.
Both enrollment and authentication flows deny missing membership data.

Users are matched by Discord ID, not automatically linked by email or username.
New usernames use the Discord username. If another account already owns that
username, a Discord-specific suffix avoids linking or replacing the other
account. The immutable Discord ID remains the source identity. Existing local
administrator login remains available.
Discord users have authentik's `internal` user type so they can open their own
application library at `/if/user/`. This does not grant administrator roles or
bypass application access policies.

Discord accounts may access only `as218822`, `books`, `go`, `immich`, `meta`,
`pdf`, and `seafile`. The companion `discord-application-access.yaml` Blueprint
binds an allowlist guard to all 19 current applications without removing their
existing policies. Applications
must use `all` policy mode; `any` would allow other bindings to bypass this guard.
Add the same guard when provisioning another application. The user portal stays
accessible and shows only permitted applications. Each application's other
policies must also pass; an existing administrator-only policy is retained
unless an explicit Discord exception is configured.

AS218822 admission is separate from operator authorization. Its dedicated
`as218822` scope emits `as218822_roles`: Discord identities receive only `user`;
active internal administrators without a Discord identity receive `operator`.
The console requires that explicit operator claim for private diagnostics, while
ordinary admitted users can manage only tunnels owned by their OIDC subject.
Older session cookies without an operator flag cannot read operator telemetry.

Guild membership checks apply to new Discord logins, not existing authentik or
application sessions. Leaving the guild does not immediately revoke sessions
or remove previously synchronized group membership. Do not use the group alone
as proof of current guild membership.

After deployment, test in a private browser window with both a guild member and
a non-member. Confirm that only the member can enroll/sign in and joins the
`discord` group. OAuth end-to-end testing requires real Discord accounts.

Argo CD self-heals this deployment from Git. Publish the manifest changes before
expecting the worker's custom Blueprint mount and secret environment to persist.
An already applied Blueprint's database objects remain when its file is removed.

Run expression regression tests with
`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s authentik/tests`
(requires PyYAML).
