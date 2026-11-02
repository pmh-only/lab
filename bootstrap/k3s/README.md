# K3s control-plane node identity

`pmhoci-node-ip.yaml` is deployed on **pmhoci only** as
`/etc/rancher/k3s/config.yaml.d/20-node-ip.yaml` (root:root, mode 0600).
It preserves the existing internal node address. Other nodes have different
addresses and must not receive this file unchanged.

## 2026-11-02 recovery

K3s v1.36.5+k3s1 exited after Kine reported
`Transaction commit failed: sql: transaction has already been committed or rolled back`.
The automatic restart then spent over ten minutes in
`GetHostnameAndIPs -> ResolveBindAddress -> getIPv6DefaultRoutes`, reading the
host's full IPv6 BGP routing table before the API listener was started.
The open `/proc/net/ipv6_route` descriptor and Go diagnostic stack confirmed
this separate recovery blocker; disk and memory were available.

Set the documented `node-ip` configuration instead of deleting BGP routes,
hiding `/proc` files, changing network policy, or resetting the datastore.
Before restarting, SQLite `quick_check` returned `ok` and its native backup
API saved a consistent mode-0600 local copy of `state.db` under the same
private datastore directory. The stalled pre-datastore process was exited
without killing running container shims. With the explicit node identity,
the new server opened its listener immediately; `/readyz` returned `ok`,
all three nodes were Ready, and the eight transitioned applications became
Synced/Healthy.

No K3s binary, cluster/service CIDRs, credentials, BGP routes, application
volumes, or existing systemd unit options were replaced. This removes the
restart blocker; it does not claim an upstream Kine transaction bug was fixed.
If the original transaction error recurs, retain its logs and investigate it
separately rather than resetting or restoring the live database.
