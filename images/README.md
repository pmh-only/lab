# Reviewed downstream images

Application compatibility changes and missing dependencies are built and tested
in CI, never downloaded, compiled, or rewritten while a production Pod starts.
Owned applications (ThePool, Solver, Keysboard) implement their fixes in their
own source repositories rather than these downstream recipes.

The scheduled native ARM64 workflow resolves immutable upstream digests and
hashes the complete recipe/patch inputs. Identical inputs are not rebuilt.
Incompatible upstream bundle changes fail the image build **before** the
published `latest` channel changes. ImageUpdater must track the downstream
image, not the unmodified upstream image. Base images and patches remain
visible in provenance; the cluster only consumes validated image digests.

Seafile deliberately remains on the approved Community 12.0 branch. The
GoAccess image embeds the GeoIP files from the resolved upstream Rybbit image;
they are versioned with the image, not frozen in a persistent log directory.
No dataset download keys or runtime credentials are included in builds.

New GHCR packages must be made public before anonymous Kubernetes pulls can
use them. Never work around package access by installing an expiring Actions
token into the cluster. Verify pull access, image architecture, and startup
before updating production manifests.
