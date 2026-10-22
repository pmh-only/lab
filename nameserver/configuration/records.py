"""Add reviewed public DNS RRsets without replacing unexpected existing data."""

import base64
import ipaddress
import json


FIELDS = {
    "A": ("ipAddress",), "AAAA": ("ipAddress",), "CNAME": ("cname",),
    "MX": ("preference", "exchange"), "SRV": ("priority", "weight", "port", "target"),
    "TXT": ("characterStringsBase64",),
}
DOMAIN_FIELDS = {"cname", "exchange", "target"}
WEB_TYPES = {"A", "AAAA", "CNAME", "ANAME", "APP", "HTTPS", "SVCB"}
DNSSEC_TYPES = {"RRSIG", "NSEC", "NSEC3", "NSEC3PARAM", "DNSKEY", "CDS", "CDNSKEY"}


def canonical(record_type, data):
    if record_type not in FIELDS:
        raise RuntimeError("Unreviewed DNS record type")
    result = {}
    for field in FIELDS[record_type]:
        value = data[field]
        if field in DOMAIN_FIELDS:
            value = value.rstrip(".").lower() or "."
        elif field == "ipAddress":
            address = ipaddress.ip_address(value)
            if address.version != (4 if record_type == "A" else 6):
                raise RuntimeError("DNS address family mismatch")
            value = str(address)
        elif field == "characterStringsBase64":
            if not isinstance(value, list) or not value:
                raise RuntimeError("TXT record must contain explicit character strings")
            parts = [base64.b64decode(part, validate=True) for part in value]
            if any(len(part) > 255 for part in parts):
                raise RuntimeError("TXT character string exceeds its wire-format limit")
            value = [base64.b64encode(part).decode() for part in parts]
        elif type(value) is not int or not 0 <= value <= 65535:
            raise RuntimeError("DNS integer field is outside its wire-format range")
        result[field] = value
    return json.dumps(result, sort_keys=True)


def reconcile(client, declaration, allowed_zones):
    plans = []
    cname_removals = []
    for zone in declaration["zones"]:
        name = zone["zone"]
        if name not in allowed_zones:
            raise RuntimeError("Imported zone was not explicitly declared")
        snapshots = {}

        if zone.get("authorityOnly"):
            if zone["records"]:
                raise RuntimeError("An authority-only zone cannot declare ordinary records")
            all_records = client.post("zones/records/get", {"zone": name, "domain": name, "listZone": "true"})["response"]["records"]
            for existing in all_records:
                record_type = existing["type"]
                apex_metadata = record_type in {"SOA", "NS", "DNSKEY", "NSEC3PARAM", "CDS", "CDNSKEY"} and existing["name"].rstrip(".").lower() == name
                generated_proof = record_type in {"RRSIG", "NSEC", "NSEC3"}
                if not apex_metadata and not generated_proof:
                    raise RuntimeError(f"Unexpected non-authority record in {name}; refusing automatic deletion")

        def read(owner):
            if owner not in snapshots:
                snapshots[owner] = client.post("zones/records/get", {"zone": name, "domain": owner})["response"]["records"]
            return [r for r in snapshots[owner] if r["name"].rstrip(".").lower() == owner]

        if zone.get("emptyApexWeb") and any(r["type"] in WEB_TYPES for r in read(name)):
            raise RuntimeError(f"Unexpected apex web record at {name}; refusing to delete it automatically")
        groups = {}
        for record in zone["records"]:
            owner, record_type = record["name"], record["type"]
            if owner != name and not owner.endswith("." + name):
                raise RuntimeError("Imported record is outside its declared zone")
            if owner in {"ns1.pmh.codes", "ns2.pmh.codes"}:
                raise RuntimeError("Nameserver addresses must be managed separately")
            if owner == name and record_type in WEB_TYPES and zone.get("emptyApexWeb"):
                raise RuntimeError("Imported record would populate the disabled apex website")
            if type(record["ttl"]) is not int or not 1 <= record["ttl"] <= 2147483647:
                raise RuntimeError("Imported record TTL is invalid")
            identity = canonical(record_type, record["data"])
            groups.setdefault((owner, record_type), {})[identity] = record
        replacements = {}
        for replacement in zone.get("replaceCnames", []):
            owner = replacement["name"]
            if owner == name or not owner.endswith("." + name) or owner in {"ns1.pmh.codes", "ns2.pmh.codes"}:
                raise RuntimeError("CNAME replacement is outside the permitted non-apex scope")
            if owner in replacements or (owner, "CNAME") in groups or not any((owner, kind) in groups for kind in ["A", "AAAA"]):
                raise RuntimeError("CNAME replacement must declare a unique address RRset")
            identity = canonical("CNAME", {"cname": replacement["expectedCname"]})
            selected = [r for r in read(owner) if r["type"] == "CNAME"]
            if selected and (len(selected) != 1 or selected[0].get("disabled") or canonical("CNAME", selected[0]["rData"]) != identity):
                raise RuntimeError(f"Unexpected CNAME at {owner}; refusing replacement")
            replacements[owner] = identity
            if selected:
                cname_removals.append((name, owner, identity))
        # Validate every RRset before making any changes to this declaration.
        for (owner, record_type), expected in groups.items():
            existing = read(owner)
            if owner in replacements:
                existing = [r for r in existing if r["type"] != "CNAME"]
            if any(r["type"] == "CNAME" and record_type != "CNAME" for r in existing):
                raise RuntimeError(f"Existing CNAME conflicts with import at {owner}")
            if record_type == "CNAME" and any(r["type"] not in DNSSEC_TYPES | {"CNAME"} for r in existing):
                raise RuntimeError(f"Existing non-CNAME data conflicts with import at {owner}")
            selected = [r for r in existing if r["type"] == record_type]
            if any(r.get("disabled") for r in selected):
                raise RuntimeError(f"Existing disabled record needs review at {owner}")
            values = {canonical(record_type, r["rData"]) for r in selected}
            if values - set(expected):
                raise RuntimeError(f"Unexpected existing {record_type} data at {owner}; refusing to replace it")
            plans.append((name, owner, record_type, expected, values))
    # Only explicitly approved, exact old CNAMEs may be removed. Check again
    # immediately before deletion; unrelated/new data is never overwritten.
    for zone, owner, identity in cname_removals:
        actual = client.post("zones/records/get", {"zone": zone, "domain": owner})["response"]["records"]
        selected = [r for r in actual if r["name"].rstrip(".").lower() == owner and r["type"] == "CNAME"]
        if selected:
            if len(selected) != 1 or selected[0].get("disabled") or canonical("CNAME", selected[0]["rData"]) != identity:
                raise RuntimeError(f"CNAME changed during reconciliation at {owner}; refusing deletion")
            client.post("zones/records/delete", {"zone": zone, "domain": owner, "type": "CNAME"})
        remaining = client.post("zones/records/get", {"zone": zone, "domain": owner})["response"]["records"]
        if any(r["name"].rstrip(".").lower() == owner and r["type"] == "CNAME" for r in remaining):
            raise RuntimeError(f"Approved CNAME replacement did not clear the old alias at {owner}")
    for zone, owner, record_type, expected, existing in plans:
        for identity in sorted(set(expected) - existing):
            record = expected[identity]
            data = json.loads(identity)
            if record_type == "TXT":
                data["characterStringsBase64"] = ",".join(data["characterStringsBase64"])
            client.post("zones/records/add", {
                "zone": zone, "domain": owner, "type": record_type, "ttl": record["ttl"],
                "overwrite": "false", "comments": "Reviewed public DNS import managed by GitOps", **data,
            })
        actual = client.post("zones/records/get", {"zone": zone, "domain": owner})["response"]["records"]
        values = {canonical(record_type, r["rData"]) for r in actual if r["name"].rstrip(".").lower() == owner and r["type"] == record_type}
        if values != set(expected):
            raise RuntimeError(f"Public DNS import verification failed at {owner} ({record_type})")
    print(f"Reviewed {sum(len(p[3]) for p in plans)} public DNS records match Git; declared apex and mail policies preserved")
