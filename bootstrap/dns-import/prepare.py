#!/usr/bin/env python3
"""Prepare reviewed public records from a Cloudflare BIND export, offline.

Never modifies the input. Does not import authority, DNSSEC, nameserver addresses,
or apex web records. Cloudflare proxy behavior cannot be preserved by DNS alone.
"""

import argparse
import base64
import json
import os
from pathlib import Path
import re
import sys

import dns.exception
import dns.name
import dns.rdatatype
import dns.zonefile


DNSSEC = {"DNSKEY", "RRSIG", "NSEC", "NSEC3", "NSEC3PARAM", "CDS", "CDNSKEY"}


def prepare(text, zone, protected_names):
    zone = zone.rstrip(".").lower()
    origin = dns.name.from_text(zone)
    excluded = []
    clean = []
    # Legacy SOA is never imported (Cloudflare also omits its terminal dot).
    # A flattened apex CNAME cannot coexist with MX/TXT in a standard zone.
    apex_cname = re.compile(r"^" + re.escape(zone) + r"\.?\s+\d+\s+IN\s+CNAME\s+", re.I)
    apex_soa = re.compile(r"^" + re.escape(zone) + r"\.?\s+\d+\s+IN\s+SOA\s+", re.I)
    for line in text.splitlines():
        if line.lstrip().startswith("$"):
            raise RuntimeError("Zone directives are not accepted; supply an explicit Cloudflare record export")
        if apex_soa.match(line):
            excluded.append({"name": zone, "type": "SOA", "reason": "authority-and-signing-managed-separately"})
            continue
        if apex_cname.match(line):
            excluded.append({"name": zone, "type": "CNAME", "reason": "apex-web-disabled"})
            continue
        clean.append(line)
    try:
        # Parse explicit FQDNs from the root so foreign owners cannot be silently
        # discarded by the parser's zone-origin filter before our scope check.
        rrsets = dns.zonefile.read_rrsets("\n".join(clean), rdclass=None, origin=dns.name.root, relativize=False)
    except (dns.exception.DNSException, ValueError):
        raise RuntimeError("Zone parser rejected the export; record values are suppressed") from None
    records = []
    for rrset in rrsets:
        name = rrset.name.to_text().rstrip(".").lower()
        record_type = dns.rdatatype.to_text(rrset.rdtype)
        if not rrset.name.is_subdomain(origin):
            raise RuntimeError("Export contains an out-of-zone record")
        reason = None
        if record_type in DNSSEC or record_type == "SOA" or (record_type == "NS" and name == zone):
            reason = "authority-and-signing-managed-separately"
        elif name in protected_names:
            reason = "nameserver-address-managed-separately"
        elif name == zone and record_type in {"A", "AAAA", "CNAME", "ANAME", "HTTPS", "SVCB", "APP"}:
            reason = "apex-web-disabled"
        if reason:
            excluded.extend({"name": name, "type": record_type, "reason": reason} for _ in rrset)
            continue
        for value in rrset:
            if record_type in {"A", "AAAA"}:
                data = {"ipAddress": value.address}
            elif record_type == "CNAME":
                data = {"cname": value.target.to_text().rstrip(".") or "."}
            elif record_type == "MX":
                data = {"preference": value.preference, "exchange": value.exchange.to_text().rstrip(".") or "."}
            elif record_type == "SRV":
                data = {"priority": value.priority, "weight": value.weight, "port": value.port, "target": value.target.to_text().rstrip(".") or "."}
            elif record_type == "TXT":
                data = {"characterStringsBase64": [base64.b64encode(part).decode() for part in value.strings]}
            else:
                raise RuntimeError(f"Record type {record_type} needs manual review; refusing partial preparation")
            records.append({"name": name, "type": record_type, "ttl": 300 if rrset.ttl == 1 else rrset.ttl, "data": data})
    records.sort(key=lambda r: (r["name"], r["type"], json.dumps(r["data"], sort_keys=True)))
    document = {"zones": [{"zone": zone, "emptyApexWeb": True, "records": records}]}
    report = {"zone": zone, "preservedRecords": len(records), "excluded": excluded, "cloudflareProxyNotMigrated": True}
    return document, report


def save_new(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(data, output, indent=2, ensure_ascii=False)
        output.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--zone", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    document, report = prepare(args.input.read_text(), args.zone, {"ns1.pmh.codes", "ns2.pmh.codes"})
    if args.output.exists() or args.report.exists():
        raise RuntimeError("Output/report already exists; refusing to overwrite it")
    save_new(args.output, document)
    save_new(args.report, report)
    print(f"Prepared {report['preservedRecords']} public records; {len(report['excluded'])} authority/apex records excluded; no values printed")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError) as error:
        print(f"DNS import preparation failed: {error}", file=sys.stderr)
        sys.exit(1)
