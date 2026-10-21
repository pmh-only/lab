#!/usr/bin/env python3
"""Provision fresh private Rybbit dependencies before publishing its routes."""

import importlib.util
import secrets
import sys

from clickhouse import provision as clickhouse_provision
from oidc import Authentik
from provision import ROOT, provision, reader


def main():
    spec = importlib.util.spec_from_file_location("dns01_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    provision(vault, "trace")
    clickhouse_provision(vault, vault.get("trace/trace-secrets"))
    path = "trace/trace-auth-secrets"
    credentials = vault.get(path)
    if credentials is None:
        bootstrap = vault.get("authentik/bootstrap-worker")
        owner = Authentik(bootstrap["AUTHENTIK_BOOTSTRAP_TOKEN"]).request("core/users/me/")["user"]
        if not owner["is_active"] or not owner["is_superuser"] or not owner.get("email"):
            raise RuntimeError("Current administrator has no usable verified owner identity")
        credentials = {"ADMIN_EMAIL": owner["email"], "ADMIN_NAME": owner.get("name") or owner["username"], "ADMIN_PASSWORD": secrets.token_urlsafe(48)}
        vault.create(path, credentials)
    if set(credentials) != {"ADMIN_EMAIL", "ADMIN_NAME", "ADMIN_PASSWORD"} or "@" not in credentials["ADMIN_EMAIL"] or not credentials["ADMIN_NAME"] or len(credentials["ADMIN_PASSWORD"]) < 48:
        raise RuntimeError("Existing Rybbit administrator credentials need manual review")
    reader(vault, "trace", ["trace/trace-secrets", path])
    print("trace: current administrator identity and fresh native recovery password preserved in Vault; values suppressed")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, AssertionError) as error:
        print(f"Trace dependency provisioning failed: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
