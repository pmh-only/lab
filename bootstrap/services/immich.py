#!/usr/bin/env python3
"""Prepare fresh native Immich credentials and its confidential OIDC client."""

import importlib.util
import json
from pathlib import Path
import secrets
import sys

from oidc import Authentik, provision_client
from provision import ROOT, provision, reader


def main():
    spec = importlib.util.spec_from_file_location("dns01_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    provision(vault, "immich")
    bootstrap = vault.get("authentik/bootstrap-worker")
    api = Authentik(bootstrap["AUTHENTIK_BOOTSTRAP_TOKEN"])
    declaration = json.loads(Path(__file__).with_name("oidc.json").read_text())["immich"]
    provision_client(vault, api, "immich", declaration)
    path = "immich/bootstrap-login"
    credentials = vault.get(path)
    if credentials is None:
        owner = api.request("core/users/me/")["user"]
        if not owner["is_active"] or not owner["is_superuser"] or not owner.get("email"):
            raise RuntimeError("No active administrator email available for native recovery ownership")
        credentials = {"ADMIN_EMAIL": owner["email"], "ADMIN_NAME": owner.get("name") or owner["username"], "ADMIN_PASSWORD": secrets.token_urlsafe(48)}
        vault.create(path, credentials)
    if set(credentials) != {"ADMIN_EMAIL", "ADMIN_NAME", "ADMIN_PASSWORD"} or "@" not in credentials["ADMIN_EMAIL"] or not credentials["ADMIN_NAME"] or len(credentials["ADMIN_PASSWORD"]) < 48:
        raise RuntimeError("Existing Immich recovery credentials need manual review")
    reader(vault, "immich", declaration["readerPaths"])
    print("immich: fresh isolated database/recovery credentials and strict web/mobile OIDC client verified; values suppressed")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        print(f"Immich credential provisioning failed: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
