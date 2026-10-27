# PMH Drive

Native Seahub branding: graphite navigation, a light file workspace, restrained
blue actions, and custom SVG logo/favicon. All custom text is English. No custom
scripts, external fonts, login replacements, or changes to permissions/quota.

The integration ConfigMap supplies these files to the existing init container.
`initialize.py` publishes content-addressed assets under
`seahub-data/custom/pmh-drive/` and a managed manifest in `conf/`.
`seahub_lab.py` reads that manifest and sets Seafile's supported `BRANDING_CSS`,
`LOGO_PATH`, and `FAVICON_PATH` settings. Changed content gets a new filename,
avoiding stale browser caches. Previous assets and unrelated custom files are
never overwritten or removed.

The native React UI, mobile sidebar, folded navigation, virtualized row heights,
dialogs, error/disabled states, editors, and keyboard focus remain intact. The
dark sidebar only targets navigation; file-preview trees retain light surfaces.

Publish through GitOps and wait for the Seafile rollout. The existing installer
preserves native state; it does not reinitialize the database or user libraries.
