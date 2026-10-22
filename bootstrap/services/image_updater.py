#!/usr/bin/env python3
"""Import the explicitly supplied updater SSH key into non-root-managed Vault."""

import argparse
import importlib.util
import json
from pathlib import Path
import secrets
import subprocess
import sys

from provision import ROOT


VAULT_PATH = "argocd/image-updater-git"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("key_file", type=Path)
    args = parser.parse_args()
    if args.key_file.stat().st_mode & 0o077:
        raise RuntimeError("Dedicated key file must not be accessible to group/others")
    check = subprocess.run(["ssh-keygen", "-y", "-P", "", "-f", str(args.key_file)], capture_output=True, text=True, timeout=10)
    if check.returncode or not check.stdout.startswith("ssh-ed25519 "):
        raise RuntimeError("Expected the approved unencrypted dedicated ED25519 key; parser output suppressed")
    key = args.key_file.read_text()
    spec = importlib.util.spec_from_file_location("dns01_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    stored = vault.get(VAULT_PATH)
    if stored is None:
        vault.create(VAULT_PATH, {"sshPrivateKey": key})
    elif set(stored) != {"sshPrivateKey"} or not secrets.compare_digest(stored["sshPrivateKey"], key):
        raise RuntimeError("Existing updater key differs; refusing an uncoordinated rotation")
    vault.run("policy", "write", "lab-image-updater", "-", payload=(
        f'path "secret/data/{VAULT_PATH}" {{ capabilities = ["read"] }}\n'))
    vault.run("write", "auth/kubernetes/role/image-updater", "-", payload=json.dumps({
        "bound_service_account_names": ["image-updater-vault-auth"],
        "bound_service_account_namespaces": ["argocd"],
        "audience": "vault", "token_policies": ["lab-image-updater"],
        "token_ttl": 3600, "token_max_ttl": 14400,
    }))
    print("image-updater: dedicated SSH key preserved in Vault; namespace/SA-scoped read-only policy configured; key values suppressed")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Image updater key provisioning failed: {type(error).__name__}; details suppressed", file=sys.stderr)
        sys.exit(1)
