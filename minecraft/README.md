# Minecraft endpoints

- Game: `play.pmh.codes:25565` (directly to the game host, not the web gateway).
- `_minecraft._tcp.pmh.codes` and `_minecraft._tcp.play.pmh.codes` target
  `play.pmh.codes:25565`, as does `_minecraft._tcp.hawal.pmh.so`.
- Map: `mc.pmh.codes`, `maps.pmh.codes`, `map.mc.pmh.codes`, and
  `hawal.pmh.codes`. `hawal.pmh.so` redirects to the `.codes` map name.
- Map upstream: `pmhmc.tailscale.svc.cluster.local:8100`, managed by
  `tailscale_configs/minecraft.yml` using the verified current-tailnet peer.

The game A/SRV migration was applied before publishing these DNS declarations.
`nameserver/configuration/migrate_minecraft.py` is a guarded, idempotent one-time
migration using the configuration job's mounted administrator credentials. It
reads the mounted zone files, checks the exact old A/SRV values,
publishes the new game address first, and preserves unrelated DNS records.
The normal nameserver reconciler continues to reject unexpected DNS changes.

Old game A/SRV answers had a 3600-second TTL; cached clients may need up to an
hour to pick up the new addresses. New records use a 300-second TTL.
