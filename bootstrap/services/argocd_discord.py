#!/usr/bin/env python3
"""Import a supplied Discord webhook into Vault without replacing the GitHub key."""

import argparse
import importlib.util
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
VAULT_PATH = "argocd/notifications-github"


def validate_url(value):
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != "https" or parsed.netloc not in {"discord.com", "discordapp.com"}
            or parsed.fragment or not re.fullmatch(r"/api(?:/v\d+)?/webhooks/\d+/[A-Za-z0-9_-]+/?", parsed.path)):
        raise RuntimeError("Expected an HTTPS Discord webhook URL; value suppressed")
    for key, values in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items():
        if len(values) != 1 or not ((key == "wait" and values[0] in {"true", "false"})
                                   or (key == "thread_id" and values[0].isdigit())):
            raise RuntimeError("Unsupported Discord webhook query parameters; values suppressed")
    return parsed.path.rstrip("/").split("/")[-2]


def validate_webhook(value):
    webhook_id = validate_url(value)
    request = urllib.request.Request(value, headers={"User-Agent": "lab-argocd-notifications"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Discord webhook validation returned HTTP {error.code}; URL and response suppressed") from None
    if data.get("id") != webhook_id or data.get("type") != 1:
        raise RuntimeError("Expected an incoming Discord webhook; response suppressed")


def provision(vault, value):
    validate_url(value)
    stored = vault.get(VAULT_PATH)
    if not stored or not stored.get("github-privateKey"):
        raise RuntimeError("Existing managed GitHub notifications credentials are required")
    if "discord-webhook-url" in stored:
        if not secrets.compare_digest(stored["discord-webhook-url"], value):
            raise RuntimeError("Existing Discord webhook differs; refusing an uncoordinated rotation")
        return
    version = json.loads(vault.run("kv", "metadata", "get", "-format=json", "-mount=secret", VAULT_PATH))["data"]["current_version"]
    vault.run("kv", "put", "-cas=" + str(version), "-mount=secret", VAULT_PATH, "-",
              payload=json.dumps({**stored, "discord-webhook-url": value}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("webhook_file", type=Path)
    args = parser.parse_args()
    if args.webhook_file.stat().st_mode & 0o077:
        raise RuntimeError("Webhook file must not be accessible to group/others")
    value = args.webhook_file.read_text().strip()
    validate_webhook(value)
    spec = importlib.util.spec_from_file_location("dns01_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    provision(vault, value)
    print("Discord webhook verified and stored in Vault; GitHub credentials preserved; no credential values printed")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f"Discord provisioning failed: {type(error).__name__}; URL, credentials and response suppressed", file=sys.stderr)
        sys.exit(1)
