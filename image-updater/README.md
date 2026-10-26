# Automatic image updates

The `image-updater` Application owns the enabled ImageUpdater resources.
Updates are signed Git commits to `main`, consumed by the child Applications.

- Versioned images use unconstrained `semver` (`:*`), including new major releases.
  Pre-release versions are excluded.
- Mutable channels (`latest`, `release`, `alpine`, and similar) retain `digest`
  tracking so a rebuilt channel image is detected.
- ARM, Alpine and dind version tags use `:*-0` plus an anchored stable-tag filter.
  The filter allows the flavor suffix without allowing release candidates.
- Composite PostgreSQL extension tags use `newest-build` with a flavor filter;
  these are ordered by image build time rather than semantic version.
- Only tags published in the configured image repository can be selected.
  Custom mirrors must publish new versions themselves.

Vault, vault-backup, vault-ui and vault-secrets-operator are excluded from image
updates. Their pinned images and values files remain unchanged.

Non-Vault Helm chart sources use `targetRevision: x` to track the latest stable
chart across major releases. Argo CD resolves chart versions directly, without
creating image-updater commits for chart upgrades. Vault charts remain pinned.
Remote Kustomize install manifests are not updated by this policy. CRD migration
behavior depends on each chart and its configured upgrade settings.
Major upgrades are intentionally automatic and may require manual data migration
or break compatibility, including between independently updated images.
