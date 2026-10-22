#!/usr/bin/env python3
"""Verify the supplied native Operator OAuth client without changing tailnet ACLs."""

import importlib.util
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

from provision import ROOT, reader


def access_token(credentials):
    if set(credentials) != {"client_id", "client_secret"} or any(not isinstance(v, str) or not v for v in credentials.values()):
        raise RuntimeError("Expected the supplied Operator OAuth client pair")
    req = urllib.request.Request("https://api.tailscale.com/api/v2/oauth/token",
        data=urllib.parse.urlencode({"grant_type": "client_credentials", **credentials}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Tailscale OAuth HTTP {error.code}; response suppressed") from None
    if not {"devices:core", "auth_keys", "services"}.issubset(set(data.get("scope", "").split())):
        raise RuntimeError("Supplied client lacks the Operator's documented write scopes")
    return data["access_token"]


def devices(token):
    req = urllib.request.Request("https://api.tailscale.com/api/v2/tailnet/-/devices", headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)["devices"]
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Tailscale device API HTTP {error.code}; response suppressed") from None


def main():
    spec = importlib.util.spec_from_file_location("dns01_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    credentials = vault.get("tailscale/operator-oauth")
    if credentials is None:
        raise RuntimeError("The real external Operator OAuth client is not available")
    current = devices(access_token(credentials))
    # Keep the separate signup OIDC credentials accessible to the same managed
    # namespace. Never rotate either pair, request new scopes, or alter ACLs.
    reader(vault, "tailscale", ["tailscale/operator-oauth", "tailscale/tailscale-oidc"])
    print(f"tailscale: native OAuth/write scopes/device API verified; {len(current)} devices currently registered; credentials and token values suppressed")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        print(f"Tailscale provisioning failed: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
