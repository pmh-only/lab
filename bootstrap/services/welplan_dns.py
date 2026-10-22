#!/usr/bin/env python3
"""Retarget only the exact reviewed legacy Welplan A record; retain all data."""

import base64
import importlib.util
import json
import select
import subprocess
import threading

from provision import ROOT


ZONE = "pmh.codes"
HOST = "welplan.pmh.codes"
LEGACY = "158.247.242.239"
TARGETS = {"168.110.121.95", "138.2.112.39"}


def records(client, owner):
    result = client.post("zones/records/get", {"zone": ZONE, "domain": owner})["response"]["records"]
    return [r for r in result if r["name"].rstrip(".").lower() == owner]


def retarget(client):
    existing = records(client, HOST)
    if any(r["type"] in {"CNAME", "AAAA", "ANAME", "APP", "HTTPS", "SVCB"} for r in existing):
        raise RuntimeError("Unreviewed Welplan web records require review")
    addresses = [r for r in existing if r["type"] == "A"]
    values = {r["rData"]["ipAddress"] for r in addresses}
    if any(r.get("disabled") for r in addresses) or not values or not (values == {LEGACY} or values <= TARGETS):
        raise RuntimeError("Welplan address changed unexpectedly; refusing replacement")
    if values == {LEGACY}:
        # Native exact old->new update avoids an empty RRset/DNS outage.
        again = records(client, HOST)
        actual = [r for r in again if r["type"] == "A"]
        if len(actual) != 1 or actual[0].get("disabled") or actual[0]["rData"]["ipAddress"] != LEGACY:
            raise RuntimeError("Welplan address changed during preflight")
        client.post("zones/records/update", {"zone": ZONE, "domain": HOST, "type": "A", "ipAddress": LEGACY,
            "newIpAddress": "168.110.121.95", "ttl": 300, "ptr": "false", "updateSvcbHints": "false",
            "comments": "Reviewed Welplan cutover to verified cluster Gateway"})
        values = {"168.110.121.95"}
    for address in sorted(TARGETS - values):
        client.post("zones/records/add", {"zone": ZONE, "domain": HOST, "type": "A", "ipAddress": address,
            "ttl": 300, "overwrite": "false", "ptr": "false"})
    actual = {r["rData"]["ipAddress"] for r in records(client, HOST) if r["type"] == "A"}
    if actual != TARGETS:
        raise RuntimeError("Native Welplan A-record verification failed")


def main():
    spec = importlib.util.spec_from_file_location("dns_configuration", ROOT / "nameserver/configuration/configure.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def secret(name, field):
        data = json.loads(subprocess.check_output(["kubectl", "get", "secret", name, "-n", "nameserver", "-o", "json"]))["data"]
        return base64.b64decode(data[field]).decode()
    ca = secret("nameserver-tls-secret", "tls.crt")
    password = secret("nameserver-admin", "password")
    client = None
    forward = subprocess.Popen(["kubectl", "port-forward", "-n", "nameserver", "svc/nameserver", "15345:53443", "--address=127.0.0.1"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        if not select.select([forward.stdout], [], [], 30)[0] or "Forwarding from" not in forward.stdout.readline():
            raise RuntimeError("DNS TLS forwarding unavailable")
        def drain():
            for _ in forward.stdout:
                pass
        threading.Thread(target=drain, daemon=True).start()
        client = module.Client("https://127.0.0.1:15345", ca)
        client.token = client.post("user/login", {"user": "admin", "pass": password})["token"]
        def protected():
            return sorted(json.dumps({"type": r["type"], "data": r["rData"]}, sort_keys=True) for r in records(client, ZONE) if r["type"] in {"MX", "TXT", "NS", "DNSKEY"})
        before = protected()
        retarget(client)
        if protected() != before:
            raise RuntimeError("Unexpected mail/authority/DNSKEY change")
        print("Only reviewed Welplan A record moved to cluster Gateways; root mail/NS/DNSKEY and old external server/data untouched")
    finally:
        try:
            if client and client.token:
                client.post("user/logout")
        finally:
            forward.terminate()
            forward.wait(timeout=10)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        raise SystemExit(f"Welplan DNS cutover failed: {type(error).__name__}; credential-bearing details suppressed")
