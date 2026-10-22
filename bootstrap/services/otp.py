#!/usr/bin/env python3
"""Wire native Mail/Connect credentials and a fresh passkey setup token into Vault."""

import importlib.util
import json
from pathlib import Path
import secrets
import subprocess
import sys

from provision import ROOT, reader


FIELDS = {"CONNECT_ROSTACK_TOKEN", "MAIL_ROSTACK_TOKEN", "PASSKEY_SETUP_TOKEN"}


def mail_token(command):
    code = Path(__file__).with_name("otp-mail-token.mjs").read_text()
    result = subprocess.run(["kubectl", "exec", "-i", "-n", "mail", "deployment/mailui", "--", "node", "--input-type=module", "-e", code],
                            input=json.dumps(command), capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError("Native Mail API key operation failed; output suppressed")
    return json.loads(result.stdout)


def main():
    spec = importlib.util.spec_from_file_location("dns01_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    connect = vault.get("connect/connect-secrets")["ROSTACK_TOKEN"]
    if len(connect) < 48:
        raise RuntimeError("Managed Connect token is incomplete")
    destination = "otp/otp-inbox"
    data = vault.get(destination)
    if data is None:
        created = mail_token({"mode": "create"})
        try:
            data = {"CONNECT_ROSTACK_TOKEN": connect, "MAIL_ROSTACK_TOKEN": created["token"], "PASSKEY_SETUP_TOKEN": secrets.token_urlsafe(48)}
            vault.create(destination, data)
        except BaseException:
            # Only undo the unique key issued by this invocation if persistence
            # failed. Never revoke existing user/API keys or change account state.
            if vault.get(destination) is None:
                mail_token({"mode": "revoke-new", "id": created["id"], "owner": created["owner"]})
            raise
    if set(data) != FIELDS or any(not isinstance(value, str) or len(value) < 32 for value in data.values()):
        raise RuntimeError("Existing managed OTP credentials need manual review")
    if not secrets.compare_digest(connect, data["CONNECT_ROSTACK_TOKEN"]):
        raise RuntimeError("Connect/OTP token rotation needs coordinated review")
    if not mail_token({"mode": "verify", "token": data["MAIL_ROSTACK_TOKEN"]})["verified"]:
        raise RuntimeError("Native Mail credential verification failed")
    reader(vault, "otp", destination)
    print("otp: dedicated native Mail key/current Connect token/fresh passkey setup token verified; existing owner, API keys and passkeys preserved; values suppressed")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f"OTP provisioning failed: {type(error).__name__}; details/credentials suppressed", file=sys.stderr)
        sys.exit(1)
