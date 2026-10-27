# Discord storage quota

authentik's dedicated `seafile` scope supplies `seafile_role=discord_10gb` only
for Discord-linked accounts or members of the `discord` group. The native Seahub
OAuth role hook maps that claim to an ordinary user role with `role_quota=10g`:
10,000,000,000 bytes per user. Other users' roles and quotas are not changed.

The role is assigned and the native role quota is refreshed on OAuth login.
Existing sessions must sign in again to receive a newly configured role. A
Seafile administrator can override individual quotas; keep Discord accounts'
individual quotas unset or no greater than 10 GB. Reducing a quota does not delete
existing files; the server prevents further writes when the limit is reached.

Seafile administration is a separate native account flag, not an OAuth role or
an authentik group grant. The owner's primary OAuth account is an administrator;
the Discord group is not. Accounts are matched using the immutable OAuth subject,
never by display name or an unverified email address.
