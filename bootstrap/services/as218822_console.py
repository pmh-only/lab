#!/usr/bin/env python3
"""Prepare the native AS console login; never activate routing or rotate keys."""

import importlib.util
import json
import subprocess
import sys

from kopia_ui import admin_policy
from oidc import Authentik, provision_client
from provision import ROOT, reader


def ensure_tunnel_state():
    # Native console can update only this existing Secret. Bootstrap an empty
    # state once; never reconcile its data from Git or overwrite live clients.
    existing = subprocess.check_output([
        "kubectl", "-n", "as218822", "get", "secret", "wireguard-tunnels",
        "--ignore-not-found=true", "-o", "name"], text=True).strip()
    if existing:
        return
    secret = {"apiVersion": "v1", "kind": "Secret", "metadata": {
        "name": "wireguard-tunnels", "namespace": "as218822",
        "annotations": {"argocd.argoproj.io/sync-options": "Prune=false"}},
        "type": "Opaque", "stringData": {"state.json": "[]", "peers.conf": ""}}
    subprocess.run(["kubectl", "create", "-f", "-"], input=json.dumps(secret).encode(), check=True)


def main():
    spec = importlib.util.spec_from_file_location("dns01_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    api = Authentik(vault.get("authentik/bootstrap-worker")["AUTHENTIK_BOOTSTRAP_TOKEN"])
    desired = json.loads((ROOT / "bootstrap/services/oidc.json").read_text())["as218822"]
    provision_client(vault, api, "as218822", desired)
    admin_policy(api, "as218822")
    reader(vault, "as218822", ["as218822/as218822-router-wireguard", "as218822/wireguard-portal-key",
           "as218822/tailscale-oauth", "as218822/console-oidc", "as218822/bird-dotenvx"])
    ensure_tunnel_state()
    print("Native AS console OIDC restricted to existing active internal administrators; routing not activated")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError):
        print("AS console provisioning failed; credential-bearing details suppressed", file=sys.stderr)
        sys.exit(1)
