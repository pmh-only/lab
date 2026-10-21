#!/usr/bin/env python3
"""Create secondary DNS passwords and a TSIG key with a non-root Vault login.

Existing credentials are validated, never overwritten. Values are not printed.
"""

import base64
import importlib.util
from pathlib import Path
import secrets
import sys


ROOT = Path(__file__).resolve().parents[2]


def ensure_credentials(vault):
    declarations = [
        ("nameserver/nameserver-secondary-admin", "password"),
        ("nameserver/nameserver-secondary-tls-keystore", "password"),
        ("nameserver/nameserver-zone-transfer", "key"),
    ]
    for path, field in declarations:
        existing = vault.get(path)
        if existing is not None:
            if set(existing) != {field} or not isinstance(existing[field], str) or len(existing[field]) < 32:
                raise RuntimeError(f"Existing credential has an unexpected format: {path}")
            if field == "key" and len(base64.b64decode(existing[field], validate=True)) < 32:
                raise RuntimeError("Existing TSIG key is too short")
            continue
        value = base64.b64encode(secrets.token_bytes(32)).decode() if field == "key" else secrets.token_urlsafe(48)
        vault.create(path, {field: value})
    print("Secondary DNS credentials and TSIG key are present in Vault; values not printed")


def main():
    spec = importlib.util.spec_from_file_location("dns01_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    ensure_credentials(vault)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        print(f"Secondary DNS credential provisioning failed: {error}", file=sys.stderr)
        sys.exit(1)
