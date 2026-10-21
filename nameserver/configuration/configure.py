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
    def __init__(self, address, certificate):
        self.address = address.rstrip("/")
        self.context = ssl.create_default_context(cadata=certificate)
        self.token = None

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
            with urllib.request.urlopen(request, context=self.context, timeout=20) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"DNS API {path}: HTTP {error.code}") from None
        if result.get("status") != "ok":
            raise RuntimeError(f"DNS API {path} rejected the request")
        return result


def normalized(value):
    return sorted(value) if isinstance(value, list) else value


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


def configure(client, desired, password):
    result = client.post("user/login", {"user": "admin", "pass": password})
    client.token = result.get("token")
    if not client.token:
        raise RuntimeError("DNS login did not return a session token")
    try:
        reconcile(client, desired)
    finally:
        try:
            client.post("user/logout")
        finally:
            client.token = None


def main():
    client = Client(
        "https://nameserver.nameserver.svc.cluster.local:53443",
        Path("/run/secrets/nameserver-ca/tls.crt").read_text(),
    )
    configure(
        client,
        json.loads(Path("/configuration/settings.json").read_text()),
        Path("/run/secrets/nameserver-admin/password").read_text(),
    )


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        print(f"DNS configuration failed: {error}", file=sys.stderr)
        sys.exit(1)
