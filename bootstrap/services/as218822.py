#!/usr/bin/env python3
"""Prepare fresh local AS218822 identities; never activate peers or host routes."""

import base64
import importlib.util
import json
from pathlib import Path
import secrets
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from provision import ROOT, reader


ROUTER_PATH = "as218822/as218822-router-wireguard"
PORTAL_PATH = "as218822/wireguard-portal-key"
MARKER = "lab-as218822-fresh-wireguard-v1"
PRIVATE_FIELDS = (
    "WG_CORE_PRIVATE_KEY", "WG_GRE_GATEWAY_PRIVATE_KEY",
    "WG_UPSTREAM_PRIVATE_KEY", "WG_BGPTUNNEL_NO_PRIVATE_KEY",
    "WG_BGPTUNNEL_ES_PRIVATE_KEY", "WG_ROUTE64_SG_PRIVATE_KEY",
    "WG_VULTR_CORE_PRIVATE_KEY", "WG_LUNALIGHT_PRIVATE_KEY",
)
REQUIRED_SCOPES = {"auth_keys", "devices:core:read", "devices:routes"}


def fresh_private_key():
    raw = bytearray(secrets.token_bytes(32))
    raw[0] &= 248
    raw[31] &= 127
    raw[31] |= 64
    return base64.b64encode(raw).decode()


def public_key(value):
    raw = base64.b64decode(value, validate=True)
    if len(raw) != 32 or raw[0] & 7 or raw[31] & 128 or not raw[31] & 64:
        raise RuntimeError("Existing WireGuard identity is not a recognized managed key")
    key = X25519PrivateKey.from_private_bytes(raw)
    return base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def complete_identity(current, fields, external=()):
    if current is not None and current.get("MANAGED_BY") != MARKER:
        raise RuntimeError("Existing identity has no fresh managed marker; refusing takeover or rotation")
    result = dict(current or {"MANAGED_BY": MARKER})
    if set(result) - {"MANAGED_BY", *fields, *external}:
        raise RuntimeError("Existing identity has unexpected fields")
    for name in fields:
        if name not in result:
            result[name] = fresh_private_key()
        public_key(result[name])
    for name in external:
        if name in result and len(base64.b64decode(result[name], validate=True)) != 32:
            raise RuntimeError("Supplied external peer PSK has invalid WireGuard encoding")
    return result


def ensure_identity(vault, path, fields, external=()):
    current = vault.get(path)
    updated = complete_identity(current, fields, external)
    if current is None:
        vault.create(path, updated)
    elif updated != current:
        version = json.loads(vault.run("kv", "metadata", "get", "-format=json", "-mount=secret", path))["data"]["current_version"]
        vault.run("kv", "put", "-cas="+str(version), "-mount=secret", path, "-", payload=json.dumps(updated))
    return updated


def verify_oauth(vault):
    credentials = vault.get("as218822/tailscale-oauth")
    if not credentials or any(not isinstance(credentials.get(k), str) or not credentials[k] for k in ["client_id", "client_secret"]):
        raise RuntimeError("Genuine dedicated Tailscale OAuth credentials are required")
    request = urllib.request.Request("https://api.tailscale.com/api/v2/oauth/token",
        data=urllib.parse.urlencode({"grant_type": "client_credentials", "scope": " ".join(sorted(REQUIRED_SCOPES)), "client_id": credentials["client_id"], "client_secret": credentials["client_secret"]}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(request, timeout=30) as response:
        token = json.load(response)
    if not REQUIRED_SCOPES <= set(token.get("scope", "").split()):
        raise RuntimeError("Dedicated OAuth client lacks required scopes")
    request = urllib.request.Request("https://api.tailscale.com/api/v2/tailnet/-/devices", headers={"Authorization": "Bearer "+token["access_token"]})
    with urllib.request.urlopen(request, timeout=30) as response:
        devices = json.load(response)["devices"]
    if not devices or any(not d.get("name", "").endswith(".tail712416.ts.net") for d in devices):
        raise RuntimeError("OAuth client does not identify the verified new tailnet")
    print("Dedicated OAuth scopes and new tailnet verified; no device/route/ACL changes")


def provision(vault):
    verify_oauth(vault)
    router = ensure_identity(vault, ROUTER_PATH, PRIVATE_FIELDS, ["WG_LUNALIGHT_PRESHARED_KEY"])
    portal = ensure_identity(vault, PORTAL_PATH, ["WG_PORTAL_PRIVATE_KEY"])
    reader(vault, "as218822", [ROUTER_PATH, PORTAL_PATH, "as218822/tailscale-oauth", "as218822/console-oidc"])
    result = {name.replace("_PRIVATE_KEY", "_PUBLIC_KEY"): public_key(value) for data in [router, portal] for name, value in data.items() if name.endswith("_PRIVATE_KEY")}
    return result


def main():
    spec = importlib.util.spec_from_file_location("dns_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    public = provision(vault)
    # Public material only. Private keys and external PSKs stay exclusively in Vault.
    Path("/tmp/opencode/as218822-fresh-public-keys.json").write_text(json.dumps(public, indent=2)+"\n")
    print(json.dumps(public, indent=2))
    print("Fresh local identities prepared; external peer acceptance/PSK remains required; no BGP or exit routes activated")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        raise SystemExit(f"AS218822 identity preparation failed: {type(error).__name__}; credentials and response bodies suppressed")
