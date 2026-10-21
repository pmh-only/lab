"""Reconcile non-secret DNS settings using the DNS administrator, not Vault root.

Credentials and the certificate come from mounted Kubernetes Secrets. Secrets,
session tokens, and API response bodies must never be written to logs.
"""

import json
from pathlib import Path
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request


class Client:
    def __init__(self, address, certificate, timeout=20):
        self.address = address.rstrip("/")
        self.context = ssl.create_default_context(cadata=certificate)
        self.token = None
        self.timeout = timeout

    def post(self, path, parameters=None):
        parameters = dict(parameters or {})
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
            # Older Technitium versions also accept the token in the form body.
            parameters["token"] = self.token
        request = urllib.request.Request(
            f"{self.address}/api/{path}",
            data=urllib.parse.urlencode(parameters).encode(),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, context=self.context, timeout=self.timeout) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"DNS API {path}: HTTP {error.code}") from None
        if result.get("status") != "ok":
            raise RuntimeError(f"DNS API {path} rejected the request")
        return result


def normalized(value):
    # Network ACLs are first-match rules: reordering can change authorization.
    return value


def reconcile(client, desired):
    current = client.post("settings/get")["response"]
    desired = dict(desired)
    # This field was renamed in Technitium 15.2.
    if "dnsReverseProxyNetworkACL" not in current:
        if "reverseProxyNetworkACL" not in current:
            raise RuntimeError("DNS server does not expose a reverse-proxy network ACL")
        desired["reverseProxyNetworkACL"] = desired.pop("dnsReverseProxyNetworkACL")
    if any(key not in current for key in desired):
        raise RuntimeError("DNS server does not expose all required settings")
    if all(normalized(current[key]) == normalized(value) for key, value in desired.items()):
        print("DNS proxy ACL, client-IP header, and private recursion settings already match Git")
        return
    parameters = {}
    for key, value in desired.items():
        if isinstance(value, list):
            value = ",".join(value)
        elif isinstance(value, bool):
            value = str(value).lower()
        parameters[key] = value
    client.post("settings/set", parameters)
    actual = client.post("settings/get")["response"]
    if not all(normalized(actual.get(key)) == normalized(value) for key, value in desired.items()):
        raise RuntimeError("DNS settings verification failed")
    print("DNS proxy ACL, client-IP header, and private recursion settings reconciled from Git")


def permission_table(rows, key):
    return "|".join(
        str(value).lower() if isinstance(value, bool) else str(value)
        for row in rows
        for value in (row[key], row["canView"], row["canModify"], row["canDelete"])
    )


def grant_user(client, get_path, set_path, parameters, username, modify, delete):
    permissions = client.post(get_path, parameters)["response"]
    expected = {"username": username, "canView": True, "canModify": modify, "canDelete": delete}
    rows = permissions.get("userPermissions", [])
    existing = next((row for row in rows if row["username"] == username), None)
    if existing and all(existing.get(key) == value for key, value in expected.items()):
        return
    users = [row for row in rows if row["username"] != username] + [expected]
    client.post(set_path, {
        **parameters,
        "userPermissions": permission_table(users, "username"),
        "groupPermissions": permission_table(permissions.get("groupPermissions", []), "name"),
    })
    actual = client.post(get_path, parameters)["response"]
    user = next((row for row in actual.get("userPermissions", []) if row["username"] == username), {})
    if not all(user.get(key) == value for key, value in expected.items()):
        raise RuntimeError("DNS01 permission verification failed")


def reconcile_dns01(client, desired):
    username = desired["username"]
    user = client.post("admin/users/get", {"user": username})["response"]
    if user.get("displayName") != desired["displayName"] or user.get("disabled"):
        raise RuntimeError("Provision the managed DNS01 service account before reconciling zone permissions")
    if set(user.get("memberOfGroups", [])) - {"Everyone"}:
        raise RuntimeError("DNS01 service account belongs to an unexpected privileged group")
    # Global list access only: no new-zone creation, zone deletion, or ACL edits.
    grant_user(client, "admin/permissions/get", "admin/permissions/set", {"section": "Zones"}, username, False, False)
    zones = {zone["name"].rstrip(".").lower(): zone for zone in client.post("zones/list")["response"]["zones"]}
    for name in desired["zones"]:
        existing = zones.get(name)
        if existing and (existing.get("type") != "Primary" or existing.get("disabled") or existing.get("internal")):
            raise RuntimeError(f"Refusing to replace or enable the existing zone {name}")
        if not existing:
            client.post("zones/create", {"zone": name, "type": "Primary"})
        # Zone delete permission is needed to remove TXT records. Global zone
        # delete remains denied, so the account cannot delete entire zones.
        grant_user(client, "zones/permissions/get", "zones/permissions/set", {"zone": name}, username, True, True)
    print(f"DNS01 service account restricted to {len(desired['zones'])} declared zones; other users and groups preserved")


def ensure_record_set(client, zone, name, record_type, field, expected, ttl):
    # The API returns records at the requested name, not every record in a zone.
    scope = {"zone": zone, "domain": name}
    records = client.post("zones/records/get", scope)["response"]["records"]
    existing = {
        record["rData"][field].rstrip(".").lower()
        for record in records
        if record["name"].rstrip(".").lower() == name and record["type"] == record_type
    }
    if existing - set(expected):
        raise RuntimeError(f"Conflicting {record_type} records at {name}; refusing to discard existing data")
    for value in sorted(set(expected) - existing):
        client.post("zones/records/add", {
            "zone": zone, "domain": name, "type": record_type,
            field: value, "ttl": ttl, "overwrite": "false", "comments": "Managed by GitOps nameserver",
        })
    actual = client.post("zones/records/get", scope)["response"]["records"]
    values = {
        record["rData"][field].rstrip(".").lower()
        for record in actual
        if record["name"].rstrip(".").lower() == name and record["type"] == record_type
    }
    if values != set(expected):
        raise RuntimeError(f"Authoritative {record_type} verification failed at {name}")


def reconcile_authoritative(client, zones, desired):
    nameservers = [item["name"] for item in desired["nameservers"]]
    for zone in zones:
        ensure_record_set(client, zone, zone, "NS", "nameServer", nameservers, desired["ttl"])
        for item in desired["nameservers"]:
            if item["name"].endswith("." + zone):
                ensure_record_set(client, zone, item["name"], "A", "ipAddress", [item["publicIPv4"]], desired["ttl"])
    zone_status = {zone["name"]: zone for zone in client.post("zones/list")["response"]["zones"]}
    for zone in zones:
        if zone_status[zone]["dnssecStatus"] == "Unsigned":
            # Generate fresh server-side keys; never import previous private keys.
            client.post("zones/dnssec/sign", {"zone": zone, **desired["dnssec"]})
        state = client.post("zones/dnssec/viewDS", {"zone": zone})["response"]
        if not state["dnssecStatus"].startswith("Signed") or not state.get("dsRecords"):
            raise RuntimeError(f"DNSSEC signing verification failed for {zone}")
    print(f"Authoritative NS/A records and DNSSEC prepared for {len(zones)} private zones; external delegation unchanged")


def configure(client, desired, password, dns01=None, authoritative=None, after_configure=None, imported=None):
    result = client.post("user/login", {"user": "admin", "pass": password})
    client.token = result.get("token")
    if not client.token:
        raise RuntimeError("DNS login did not return a session token")
    try:
        reconcile(client, desired)
        if dns01:
            reconcile_dns01(client, dns01)
            if authoritative:
                reconcile_authoritative(client, dns01["zones"], authoritative)
            if imported:
                from records import reconcile as reconcile_records

                reconcile_records(client, imported, dns01["zones"])
        if after_configure:
            after_configure(client)
    finally:
        try:
            client.post("user/logout")
        finally:
            client.token = None


def main():
    dns01 = json.loads(Path("/configuration/dns01.json").read_text())
    client = Client(
        "https://nameserver.nameserver.svc.cluster.local:53443",
        Path("/run/secrets/nameserver-ca/tls.crt").read_text(),
    )
    configure(
        client,
        json.loads(Path("/configuration/settings.json").read_text()),
        Path("/run/secrets/nameserver-admin/password").read_text(),
        dns01,
        json.loads(Path("/configuration/authoritative.json").read_text()),
        imported=json.loads(Path("/configuration/imported-records.json").read_text()),
    )


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        print(f"DNS configuration failed: {error}", file=sys.stderr)
        sys.exit(1)
