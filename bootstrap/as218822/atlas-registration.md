# RIPE Atlas registration required

The running probes have persistent identities but registration currently fails
with SSH permission denied. Register these public keys using the owner's RIPE
account at <https://atlas.ripe.net/apply/swprobe/>. If updating an existing
probe, use the owner's supported key-update/re-registration procedure instead
of guessing or overwriting the old identity.

## IPv4 probe

```text
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJNv486oHsNXK+WDiN8a0xQ//Rbpl46+70gEGfMZEHcx ripe-atlas-ipv4-54958fc56d-6bmw8
```

## AS218822 IPv6 probe

```text
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFtZy6skZvpFuHNHZ9cQ3DXdTJS4K4hTP4hiVkmPuSe0 ripe-atlas-as218822-598d4fb7d6-dckgv
```

These are public keys read from `/etc/ripe-atlas/probe_key.pub` on the current
probes. Their private keys remain only in the original PVCs. Do not regenerate
them or remove the PVCs to fix registration. Before registration, verify the
current public key with `kubectl -n as218822 exec deployment/<probe-name>
-c ripe-atlas -- cat /etc/ripe-atlas/probe_key.pub`.
