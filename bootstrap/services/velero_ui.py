#!/usr/bin/env python3
"""Provision the original Velero UI chart's native OAuth and JWT credentials."""

import importlib.util
import json
import sys

from kopia_ui import admin_policy
from backup_s3 import velero_credentials
from oidc import Authentik, provision_client
from provision import ROOT, reader


def main():
    spec = importlib.util.spec_from_file_location("dns01_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    api = Authentik(vault.get("authentik/bootstrap-worker")["AUTHENTIK_BOOTSTRAP_TOKEN"])
    desired = json.loads((ROOT / "bootstrap/services/oidc.json").read_text())["velero-ui"]
    provision_client(vault, api, "velero-ui", desired)
    admin_policy(api, "velero-ui")
    velero_credentials(vault)
    reader(vault, "velero", ["velero/s3", "velero/velero-ui-secrets"])
    print("Velero UI native OAuth/admin policy and fresh JWT secret configured; existing storage credentials preserved")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError):
        print("Velero UI provisioning failed; credential-bearing details suppressed", file=sys.stderr)
        sys.exit(1)
