# AS218822 startup checks

The user approved retaining the existing encrypted dotenv configuration and
its existing key. `as218822/bird-dotenvx` in Vault supplies `DOTENV_PRIVATE_KEY`.
Do not rotate/import/rewrite external peer identities automatically. The
previously generated router keys remain unused until their public keys match
the corresponding peer configuration.

`validate-existing.sh` runs inside the pinned original routing image with
`BIRD_VALIDATE=1`, a memory-backed `/run/bird`, no network capabilities, no
service-account token, and a deny-all ingress/egress NetworkPolicy. Mount it
read-only and supply the relevant existing Secret fields as environment
variables. It checks all required template fields before running the native
renderer, because the renderer's validation mode otherwise substitutes dummy
values for missing fields. Raw decrypted configuration/logs must never be
printed or copied out of the temporary Pod.

Current validation: core and GRE dotenv/templates and BIRD syntax pass with
the existing Vault inputs, including the user-supplied Lunalight credentials.
The paired internal peer templates in `as218822/router-public-config.yml` also
pass in the pinned original images. Their public keys are derived from the
Vault-held core/GRE/portal keys; no external upstream identity is rotated.
This does not start BGP, establish a tunnel, or prove peer connectivity.

Live startup found that the supplied Lunalight private key derives the same
public key as the image's configured **remote** peer. The kernel therefore
has no usable Lunalight peer. Syntax validation alone cannot establish a valid
identity pair; `validate-existing.sh` now rejects this `SELF_PEER` case without
printing private keys. Preserve the tunnel addresses and obtain a matching,
distinct local-private/remote-public pair from the operator before claiming
the Lunalight session is operational. Never silently rotate the supplied key.

Core/IPv6 Atlas networking uses the already-verified Sysbox runtime and user
namespaces, with explicit capabilities instead of privileged mode. The original
GRE gateway still uses host networking on `pmhoci`, because its original GRE
underlay is bound to `10.0.0.10`/`enp0s6`. Moving it to a Pod IP would silently
change the external tunnel design. Its privileged sysctl init was replaced by
a read-only precondition; no writable host `/proc` mount is used.

`host-preflight.yml` reads only host addresses, forwarding and rules, with no
capabilities or service-account token. It found IPv6 forwarding **disabled** on
`pmhoci`. An operator must enable it on the host before Application activation:

```sh
sudo sysctl -w net.ipv6.conf.all.forwarding=1
```

Persistence across host reboot must be managed deliberately by the operator;
the Pod never writes host sysctls. Do not register the Application before this
precondition passes. The production gateway still needs host `NET_ADMIN` for
its original interfaces/routes/nftables, but no container uses privileged mode.

After the operator enabled forwarding, the Applications were registered.
The GRE host's live public IPv4 is `168.110.121.95`; the portal endpoint uses
that address. Core/Atlas Tailscale explicitly uses native nftables, avoiding
unavailable host legacy `ip6_tables` modules. The original marked exit SNAT
is installed at priority 99 in the **private core network namespace** before
Tailscale's priority-100 NAT, not by a blocking postStart legacy-iptables hook.
The Sysbox smoke test checks the same IPv6 NAT rule without privileged mode.

`bootstrap/services/as218822_console.py` provisions the native console OIDC
with the exact callback and active/internal/superuser gate, preserving existing
Secrets. It creates an empty native `wireguard-tunnels` Secret **only if absent**;
existing client state is never reconciled from Git or reset. Tailscale uses the
dedicated `tag:as218822`, including the existing device-identity approval checks.
