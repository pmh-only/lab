#!/usr/bin/env python3
"""Connect Technitium's native web-console OIDC to the existing Authentik.

Only changes native SSO settings. No DNS records, keys, ACLs, users or local
passwords are changed. The client secret stays in Vault and native auth config;
it is not mounted in DNS pods or added to the namespace's existing Vault policy.
"""

import base64
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import select
import subprocess
import sys
import threading
import time
import urllib.error

from oidc import Authentik, provision_client
from provision import ROOT


SETTINGS = ROOT / "nameserver/configuration/oidc.json"


def zone_identity(client):
    zones = client.post("zones/list")["response"]["zones"]
    return sorted((z["name"], z["type"], z.get("disabled"), z.get("dnssecStatus")) for z in zones)


def matches(actual, desired):
    return all(
        set(actual.get(key, [])) == set(value) if key == "ssoScopes" else actual.get(key) == value
        for key, value in desired.items()
    )


def reconcile(client, desired, secret):
    current = client.post("admin/sso/get", {"includeGroups": "true"})["response"]
    if "ssoScopes" not in current or "Administrators" not in current.get("localGroups", []):
        raise RuntimeError("Native SSO scopes and administrator group support are required")
    if current.get("ssoAuthority") not in {None, "", desired["ssoAuthority"]} or current.get("ssoClientId") not in {None, "", desired["ssoClientId"]}:
        raise RuntimeError("Unmanaged OIDC configuration exists; refusing to replace it")
    if current.get("ssoGroupMap") and current["ssoGroupMap"] != desired["ssoGroupMap"]:
        raise RuntimeError("Unmanaged SSO group mappings exist; refusing privilege changes")
    if matches(current, desired):
        print("Technitium OIDC already matches Git; native configuration left unchanged")
        return
    if not isinstance(secret, str) or len(secret) < 48:
        raise RuntimeError("A managed confidential-client secret is required")
    zones = zone_identity(client)
    admin = client.post("admin/users/get", {"user": "admin"})["response"]
    local_fields = {key: admin.get(key) for key in ["username", "disabled", "memberOfGroups", "type", "isSsoUser"]}
    parameters = dict(desired)
    parameters["ssoClientSecret"] = secret
    parameters["ssoMetadataAddress"] = desired["ssoMetadataAddress"] or ""
    parameters["ssoScopes"] = "|".join(desired["ssoScopes"])
    parameters["ssoGroupMap"] = "|".join(v for row in desired["ssoGroupMap"] for v in [row["remoteGroup"], row["localGroup"]])
    for key, value in parameters.items():
        if isinstance(value, bool):
            parameters[key] = str(value).lower()
    # This endpoint notifies the native cluster and restarts only the web
    # service if needed. Never restart the DNS deployment to apply OIDC.
    client.post("admin/sso/set", parameters)
    actual = None
    for attempt in range(10):
        try:
            actual = client.post("admin/sso/get")["response"]
            break
        except (OSError, urllib.error.URLError):
            if attempt == 9:
                raise
            time.sleep(1)
    if not matches(actual, desired):
        raise RuntimeError("Native SSO configuration verification failed")
    if zone_identity(client) != zones:
        raise RuntimeError("DNS zone identity changed during SSO configuration; stop and review")
    after = client.post("admin/users/get", {"user": "admin"})["response"]
    if any(after.get(key) != value for key, value in local_fields.items()):
        raise RuntimeError("Local administrator identity changed; stop and review")
    print("Technitium native OIDC configured; mapped administrators only; local login and DNS zone identity preserved")


@contextmanager
def administrator():
    spec = importlib.util.spec_from_file_location("dns_configuration", ROOT / "nameserver/configuration/configure.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def secret(name, field):
        raw = json.loads(subprocess.check_output(["kubectl", "get", "secret", name, "-n", "nameserver", "-o", "json"]))["data"][field]
        return base64.b64decode(raw).decode()
    password = secret("nameserver-admin", "password")
    certificate = secret("nameserver-tls-secret", "tls.crt")
    forward = subprocess.Popen([
        "kubectl", "port-forward", "-n", "nameserver", "deployment/nameserver",
        "15343:53443", "--address=127.0.0.1",
    ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    client = None
    try:
        if not select.select([forward.stdout], [], [], 30)[0] or "Forwarding from" not in forward.stdout.readline():
            raise RuntimeError("Native DNS TLS API forwarding failed")
        def drain():
            for _ in forward.stdout:
                pass
        threading.Thread(target=drain, daemon=True).start()
        client = module.Client("https://127.0.0.1:15343", certificate)
        client.token = client.post("user/login", {"user": "admin", "pass": password})["token"]
        yield client
    finally:
        if client and client.token:
            try:
                client.post("user/logout")
            except (RuntimeError, OSError):
                pass
            finally:
                client.token = None
        forward.terminate()
        try:
            forward.wait(timeout=10)
        except subprocess.TimeoutExpired:
            forward.kill()
            forward.wait(timeout=10)


def main():
    desired = json.loads(SETTINGS.read_text())
    declaration = json.loads(Path(__file__).with_name("oidc.json").read_text())["technitium"]
    spec = importlib.util.spec_from_file_location("dns01_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    api = Authentik(vault.get("authentik/bootstrap-worker")["AUTHENTIK_BOOTSTRAP_TOKEN"])
    # A generic profile's ordinary groups must not collide with this reserved
    # admin-only role claim, since Technitium accepts both roles and groups.
    remote_group = desired["ssoGroupMap"][0]["remoteGroup"]
    if any(g["name"] == remote_group for g in api.list("core/groups/")):
        raise RuntimeError("An identity-provider group collides with the reserved role claim")
    provision_client(vault, api, "technitium", declaration)
    stored = vault.get(declaration["vaultPath"])
    with administrator() as client:
        reconcile(client, desired, stored["client-secret"])


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f"Technitium OIDC configuration failed: {type(error).__name__}; details suppressed", file=sys.stderr)
        sys.exit(1)
