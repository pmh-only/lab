#!/usr/bin/env python3
"""Preserve supplied vendor credentials and provision native Solver web identity."""

import importlib.util
import json
import secrets

from oidc import Authentik, provision_client
from provision import ROOT


EXTERNAL = ("DISCORD_TOKEN", "IMAP_PASS", "FIRECRAWL_API_KEY", "OPENAI_API_KEY", "OPENAI_ADMIN_KEY")


def provision(vault, api):
    external = vault.get("solver/solver-secret")
    if not external or any(not isinstance(external.get(k), str) or not external[k].strip() for k in EXTERNAL):
        raise RuntimeError("Required real external credentials are missing")
    internal = vault.get("solver/internal")
    if internal is None:
        owners = [u for u in api.list("core/users/") if u.get("is_active") and u.get("is_superuser") and u.get("type") == "internal"]
        if not owners:
            raise RuntimeError("No existing active human Authentik administrator")
        subjects = sorted({u["username"] for u in owners})
        if any(not s or any(c.isspace() or c == ',' for c in s) for s in subjects):
            raise RuntimeError("Native subject-list format requires reviewed usernames")
        internal = {"WEB_SESSION_SECRET": secrets.token_urlsafe(48), "WEB_ADMIN_SUBJECTS": ",".join(subjects)}
        vault.create("solver/internal", internal)
    if set(internal) != {"WEB_SESSION_SECRET", "WEB_ADMIN_SUBJECTS"} or len(internal["WEB_SESSION_SECRET"]) < 48 or not internal["WEB_ADMIN_SUBJECTS"]:
        raise RuntimeError("Existing native web identity requires review")
    declaration = json.loads((ROOT / "bootstrap/services/oidc.json").read_text())["solver"]
    provision_client(vault, api, "solver", declaration)
    print("Solver: supplied external credentials untouched; fresh web identity and existing human administrator subjects preserved")


def main():
    spec = importlib.util.spec_from_file_location("dns_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    api = Authentik(vault.get("authentik/bootstrap-worker")["AUTHENTIK_BOOTSTRAP_TOKEN"])
    provision(vault, api)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        raise SystemExit(f"Solver provisioning failed: {type(error).__name__}; credential-bearing details suppressed")
