# Off-site native Vault snapshots

This application creates only backup resources in the existing `vault`
namespace. It does **not** own or change the Vault server StatefulSet, version,
image pin, manual-sync policy, storage, unseal configuration, or TLS Secret.

A fresh short-lived Kubernetes-auth identity may only **read** the native
`sys/storage/raft/snapshot` endpoint. The snapshot container mounts only the
Vault CA from the TLS Secret, not its server private key, and verifies HTTPS.
The uploader cannot access the projected authentication token. Its dedicated S3
identity can write/read the remote private `vault` bucket but cannot delete.

Snapshots remain encrypted with Vault's original seal keys. The job validates
the native archive and internal checksums, uploads it, downloads it again, and
checks SHA-256 before publishing `_COMPLETE`. The schedule starts suspended
until the first run passes these checks. No remote pruning is configured.

**Recovery still requires the original unseal shares**, held separately from
the Raspberry Pi and cluster. No unseal shares are collected, printed, or stored
by this job. An isolated, fully unsealed restore has not been tested; completion
markers explicitly record `fullRestoreTested=false`. Do not run a snapshot
restore against the live cluster as a backup verification step.

The repository encryption password for Kopia is also in Vault, so keep an
offline copy of that password or retain both a usable Vault snapshot and its
original unseal shares. Backup storage credentials alone cannot decrypt either
Vault's sealed data or Kopia's encrypted file snapshots.
