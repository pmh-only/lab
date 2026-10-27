#!/usr/bin/env python3
"""Validate the supplied GitHub App key and provision its Vault-only reader."""

import argparse
import base64
import importlib.util
import json
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


ROOT = Path(__file__).resolve().parents[2]
APP_ID = 5488198
INSTALLATION_ID = 175649535
VAULT_PATH = "argocd/notifications-github"


def github(path, token, data=None):
    request = urllib.request.Request("https://api.github.com" + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"GitHub {path}: HTTP {error.code}; response suppressed") from None


def validate_key(key):
    private_key = serialization.load_pem_private_key(key.encode(), password=None)
    if not isinstance(private_key, rsa.RSAPrivateKey):
        raise RuntimeError("Expected an RSA GitHub App private key")
    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=")
    now = int(time.time())
    payload = b".".join(encode(json.dumps(value).encode()) for value in (
        {"alg": "RS256", "typ": "JWT"}, {"iat": now - 60, "exp": now + 540, "iss": APP_ID}))
    signature = private_key.sign(payload, padding.PKCS1v15(), hashes.SHA256())
    jwt = (payload + b"." + encode(signature)).decode()
    if github("/app", jwt)["id"] != APP_ID:
        raise RuntimeError("GitHub App identity differs")
    installation = github(f"/app/installations/{INSTALLATION_ID}", jwt)
    if installation["account"]["login"].lower() != "pmh-only":
        raise RuntimeError(f"GitHub App is installed on {installation['account']['login']}, not pmh-only")
    if any(installation["permissions"].get(name) != "write" for name in ("statuses", "deployments")):
        raise RuntimeError("GitHub App requires Commit statuses and Deployments write permissions")
    # Request a token restricted to this repository and only the needed rights.
    token = github(f"/app/installations/{INSTALLATION_ID}/access_tokens", jwt, {
        "repositories": ["lab"], "permissions": {"statuses": "write", "deployments": "write"},
    })
    if [repo["full_name"] for repo in token.get("repositories", [])] != ["pmh-only/lab"]:
        raise RuntimeError("GitHub App token is not scoped to the lab repository")


def provision(vault, key):
    stored = vault.get(VAULT_PATH)
    desired = {"github-privateKey": key}
    if stored is None:
        vault.create(VAULT_PATH, desired)
    elif (set(stored) not in (set(desired), {"github-privateKey", "discord-webhook-url"})
          or not secrets.compare_digest(stored["github-privateKey"], key)):
        raise RuntimeError("Existing GitHub App key differs; refusing an uncoordinated rotation")
    vault.run("policy", "write", "lab-argocd-notifications", "-", payload=(
        f'path "secret/data/{VAULT_PATH}" {{ capabilities = ["read"] }}\n'))
    vault.run("write", "auth/kubernetes/role/argocd-notifications", "-", payload=json.dumps({
        "bound_service_account_names": ["notifications-vault-auth"],
        "bound_service_account_namespaces": ["argocd"],
        "audience": "vault", "token_policies": ["lab-argocd-notifications"],
        "token_ttl": 3600, "token_max_ttl": 14400,
    }))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("key_file", type=Path)
    args = parser.parse_args()
    if args.key_file.stat().st_mode & 0o077:
        raise RuntimeError("Private key file must not be accessible to group/others")
    key = args.key_file.read_text()
    validate_key(key)
    spec = importlib.util.spec_from_file_location("dns01_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    provision(vault, key)
    print("argocd-notifications: GitHub App identity, lab access and write permissions verified; key stored in Vault; credential values suppressed")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f"Argo CD notifications provisioning failed: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
