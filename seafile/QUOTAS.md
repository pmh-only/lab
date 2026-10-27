# Discord storage quota

authentik's dedicated `seafile` scope supplies `seafile_role=discord_10gb` only
for Discord-linked accounts or members of the `discord` group. The native Seahub
OAuth hook marks that verified login and uses the ordinary `default` user role.
`seahub_discord_quota.DiscordQuotaMiddleware` applies a persistent native per-user
quota before sending the callback response: at most 10,000,000,000 bytes. A
smaller existing limit is preserved. No Professional-only role quota API is used.

Every Discord OAuth login reapplies and verifies the per-user limit. Quota
assignment failure logs the user out and returns an error rather than completing
an unlimited login. Context-local state prevents another concurrent user's
login from being classified as Discord. Other users' quotas are untouched.
Existing Discord users are converted once during migration, so their active
sessions and sync clients retain the limit without waiting for another login.
Reducing a quota does not delete files; the server prevents further writes when
the limit is reached. Administrator overrides are capped again on the next
Discord OAuth login.

Seafile administration is a separate native account flag, not an OAuth role or
an authentik group grant. The owner's primary OAuth account is an administrator;
the Discord group is not. Accounts are matched using the immutable OAuth subject,
never by display name or an unverified email address.
