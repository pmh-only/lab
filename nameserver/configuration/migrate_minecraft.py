"""One-time, guarded migration of the game address; run before DNS reconciliation.

Uses the same mounted credentials and Client as configure.py. Pass the reviewed
imported-records.json on stdin. No unrelated records or SRV services are changed.
"""

import json
from pathlib import Path
import sys

from configure import Client
from records import canonical, reconcile


def migrate(client, declaration):
    zone = "pmh.codes"
    moves = [
        ("mc.pmh.codes", "A", {"ipAddress": "168.107.9.91"},
         {"ipAddress": "168.110.121.95"}),
        ("_minecraft._tcp.pmh.codes", "SRV",
         {"priority": 0, "weight": 5, "port": 25565, "target": "mc.pmh.codes"},
         {"priority": 0, "weight": 5, "port": 25565, "target": "play.pmh.codes"}),
    ]
    desired = next(z for z in declaration["zones"] if z["zone"] == zone)
    owners = {"play.pmh.codes", "mc.pmh.codes", "map.mc.pmh.codes",
              "_minecraft._tcp.pmh.codes", "_minecraft._tcp.play.pmh.codes"}
    selected = [r for r in desired["records"] if r["name"] in owners]
    pending = []
    # Verify both old RRsets before making any changes. A repeated run is safe.
    for owner, kind, old, new in moves:
        records = client.post("zones/records/get", {"zone": zone, "domain": owner})["response"]["records"]
        records = [r for r in records if r["name"].rstrip(".").lower() == owner and r["type"] == kind]
        expected = {canonical(kind, r["data"]) for r in selected if r["name"] == owner and r["type"] == kind}
        values = {canonical(kind, r["rData"]) for r in records}
        if any(r.get("disabled") for r in records) or not values or values - (expected | {canonical(kind, old)}):
            raise RuntimeError(f"Unexpected {kind} at {owner}; refusing migration")
        if canonical(kind, old) in values:
            pending.append((owner, kind, old, new))
    # Publish the new game endpoint before moving any existing game references.
    initial = [r for r in selected if r["name"] not in {m[0] for m in moves}]
    reconcile(client, {"zones": [{"zone": zone, "records": initial}]}, [zone])
    # Move the SRV first so uncached game clients stop depending on the web name.
    for owner, kind, old, new in reversed(pending):
        client.post("zones/records/update", {
            "zone": zone, "domain": owner, "type": kind, "ttl": 300,
            **old, **{"new" + k[0].upper() + k[1:]: v for k, v in new.items()},
        })
    reconcile(client, {"zones": [{"zone": zone, "records": selected}]}, [zone])
    print("Minecraft game A/SRV and map DNS migration verified")


if __name__ == "__main__":
    client = Client("https://nameserver.nameserver.svc.cluster.local:53443",
                    Path("/run/secrets/nameserver-ca/tls.crt").read_text())
    client.token = client.post("user/login", {
        "user": "admin", "pass": Path("/run/secrets/nameserver-admin/password").read_text(),
    })["token"]
    try:
        migrate(client, json.load(sys.stdin))
    finally:
        client.post("user/logout")
