# MongoDB 9.0 migration — 2026-10-02

The automatic `latest` image update installed MongoDB 9.0.2 while the database
still had feature compatibility version (FCV) 8.2. MongoDB refused to start.

Recovery was deployed through GitOps:

1. Scale MongoDB to zero and disable unbounded image updates.
2. Archive the offline data directory and verify the SHA-256 checksum and gzip integrity.
3. Extract a separate test copy and migrate it through MongoDB 8.3.11 / FCV 8.3,
   then MongoDB 9.0.2 / FCV 9.0.
4. Repeat the tested upgrade on the original data directory.
5. Compare collection document counts and index names before and after every stage.
   Exclude MongoDB's FCV document, profiling data, and the empty internal
   `config.queryShapeRepresentativeQueries` collection created by FCV 8.3.
6. Restore the deployment using the official `mongo:9.0` image. Digest updates
   remain automatic, but cannot advance to another major/minor release.

Both test and production migrations passed. The Spotify listening-history
collection (`infos`) retained 126,797 documents, alongside 8,264 albums,
5,430 artists, 15,384 tracks, and the existing user and authentication records.

## Retained recovery artifacts

PVC: `database/mongo-upgrade-20261002-backup` (protected from Argo CD pruning).

- `pre-upgrade.tar.gz`: offline pre-migration database archive, approximately 509 MiB.
- `pre-upgrade.sha256`: verified archive checksum.
- `original-before.json`, `before.json`: original and migration comparison inventories.
- `test-8.3.json`, `test-9.0.json`: test-copy verification inventories.
- `production-8.3.json`, `production-9.0.json`: production verification inventories.
- `staging`, `staging-v2`: isolated test data directories, not production data.

Do not restore old data files under a newer MongoDB binary without checking
version compatibility. Preserve the archive until a fresh post-upgrade backup
has been verified. The one-time migration jobs were removed after success;
their manifests and scripts remain in Git history.
