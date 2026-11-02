"""Parse reviewed BIND-format records, leaving server-managed DNS data alone."""

import base64
import json
from pathlib import Path

import dns.exception
import dns.rdatatype
import dns.zone

from records import canonical


def read_records(path, origin):
    # Parse from the DNS root so dnspython cannot silently discard owners outside
    # the declared zone. $ORIGIN in each file supplies the normal relative names.
    try:
        zone = dns.zone.from_file(
            path, origin=".", relativize=False, check_origin=False,
            allow_include=False, allow_directives=["$ORIGIN", "$TTL"],
        )
    except dns.exception.DNSException as error:
        raise RuntimeError(f"Invalid zone file {Path(path).name}: {error}") from None
    records = []
    for name, node in zone.nodes.items():
        owner = name.to_text().rstrip(".").lower()
        if owner != origin and not owner.endswith("." + origin):
            raise RuntimeError(f"Zone file owner {owner} is outside {origin}")
        for rrset in node.rdatasets:
            kind = dns.rdatatype.to_text(rrset.rdtype)
            if not 1 <= rrset.ttl <= 2147483647:
                raise RuntimeError(f"Invalid TTL in {Path(path).name}")
            for rdata in rrset:
                if kind in {"A", "AAAA"}:
                    data = {"ipAddress": rdata.address}
                elif kind == "CNAME":
                    data = {"cname": rdata.target.to_text()}
                elif kind == "MX":
                    data = {"preference": rdata.preference, "exchange": rdata.exchange.to_text()}
                elif kind == "SRV":
                    data = {
                        "priority": rdata.priority, "weight": rdata.weight,
                        "port": rdata.port, "target": rdata.target.to_text(),
                    }
                elif kind == "TXT":
                    data = {"characterStringsBase64": [base64.b64encode(part).decode() for part in rdata.strings]}
                else:
                    raise RuntimeError(f"Unmanaged record type {kind} in {Path(path).name}")
                records.append({"name": owner, "type": kind, "ttl": rrset.ttl,
                                "data": json.loads(canonical(kind, data))})
    return records


def load_declaration(configuration, zone_directory=None, allowed_zones=None):
    configuration = Path(configuration)
    zone_directory = Path(zone_directory) if zone_directory is not None else configuration
    if allowed_zones is None:
        allowed_zones = json.loads((configuration / "dns01.json").read_text())["zones"]
    declaration = json.loads((configuration / "zones.json").read_text())
    seen = set()
    for zone in declaration["zones"]:
        name = zone["zone"]
        if name not in allowed_zones or name in seen:
            raise RuntimeError("Zone files must name unique, explicitly allowed zones")
        if set(zone) - {"zone", "emptyApexWeb", "authorityOnly", "replaceCnames"}:
            raise RuntimeError("Unexpected zone-file policy; records belong in .zone files")
        seen.add(name)
        zone["records"] = read_records(zone_directory / (name + ".zone"), name)
        if not zone["records"] and not zone.get("authorityOnly"):
            raise RuntimeError(f"Empty zone file for {name}; refusing reconciliation")
    if seen != set(allowed_zones):
        raise RuntimeError("Every declared public zone must have a zone file and policy")
    return declaration


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configuration", type=Path)
    parser.add_argument("zone_directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(load_declaration(args.configuration, args.zone_directory), indent=2))
