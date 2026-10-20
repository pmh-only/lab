#!/usr/bin/env python3
"""Initialize/unseal Vault without authenticating with its root token.

Run with Python 3 and PyYAML installed, after forwarding Vault's TLS port:
  kubectl -n vault port-forward svc/vault 8200:8200
  python3 bootstrap/vault/setup.py

Configuration is a separate, explicit step: pass --configure with a non-root
administrator token supplied through VAULT_TOKEN. Root tokens are rejected.
No application credentials are imported or generated. Bootstrap credentials are
stored outside Git with mode 0600. Move the unseal shares to separate secure
custodians. This script never authenticates using the saved bootstrap root token.
"""

import argparse
import base64
import json
import os
from pathlib import Path
import ssl
import stat
import subprocess
import sys
import urllib.error
import urllib.request

import yaml


class Vault:
    def __init__(self, address, ca):
        if not address.startswith("https://"):
            raise ValueError("Vault requires a TLS-verified HTTPS address")
        self.address = address.rstrip("/")
        self.context = ssl.create_default_context(cadata=ca)
        self.token = None

    def request(self, path, data=None, method=None):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["X-Vault-Token"] = self.token
        request = urllib.request.Request(
            f"{self.address}/v1/{path}",
            data=json.dumps(data).encode() if data is not None else None,
            headers=headers,
            method=method or ("POST" if data is not None else "GET"),
        )
        try:
            with urllib.request.urlopen(request, context=self.context, timeout=30) as response:
                body = response.read()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as error:
            # Never echo response bodies: they may contain credentials.
            raise RuntimeError(f"Vault {path}: HTTP {error.code}") from None


def protected_credentials(path, vault):
    if not path.parent.exists():
        path.parent.mkdir(mode=0o700, parents=True)
    parent = path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid() or parent.st_mode & 0o077:
        raise RuntimeError("Credential directory must be owned by this user with mode 0700")

    initialized = vault.request("sys/init")["initialized"]
    if path.exists() or path.is_symlink():
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
            raise RuntimeError("Credential file must be owned by this user with mode 0600")
        if not initialized:
            raise RuntimeError("Credential file already exists but Vault is not initialized; refusing reuse")
        credentials = json.loads(path.read_text())
    else:
        if initialized:
            raise RuntimeError("Vault is already initialized; supply its protected bootstrap credential file")
        # Reserve the protected file before the irreversible initialization call.
        # Retain it on failure: inspect Vault's state before retrying initialization.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            credentials = vault.request("sys/init", {"secret_shares": 5, "secret_threshold": 3}, "PUT")
            json.dump(credentials, output)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        print(f"New bootstrap credentials saved privately to {path}")
    if len(credentials.get("keys_base64", [])) < 3:
        raise RuntimeError("Bootstrap credential file is incomplete")
    return credentials


def authenticate_operator(vault, credentials, token):
    if not token:
        raise RuntimeError("--configure requires a non-root administrator token in VAULT_TOKEN")
    if token == credentials.get("root_token"):
        raise RuntimeError("The bootstrap root token must not be used")
    vault.token = token
    try:
        policies = vault.request("auth/token/lookup-self")["data"]["policies"]
        if "root" in policies:
            raise RuntimeError("Root-policy tokens must not be used")
    except Exception:
        vault.token = None
        raise


def configure(vault, root):
    audits = vault.request("sys/audit")["data"]
    if "stdout/" not in audits:
        vault.request("sys/audit/stdout", {
            "type": "file",
            "options": {"file_path": "stdout", "log_raw": "false"},
        })
    mounts = vault.request("sys/mounts")["data"]
    if "secret/" not in mounts:
        vault.request("sys/mounts/secret", {"type": "kv", "options": {"version": "2"}})
    elif mounts["secret/"].get("type") != "kv" or mounts["secret/"].get("options", {}).get("version") != "2":
        raise RuntimeError("Existing secret mount is not KV v2; refusing to replace it")

    auth = vault.request("sys/auth")["data"]
    if "kubernetes/" not in auth:
        vault.request("sys/auth/kubernetes", {"type": "kubernetes"})
    elif auth["kubernetes/"]["type"] != "kubernetes":
        raise RuntimeError("Existing kubernetes auth mount has a different type")
    vault.request("auth/kubernetes/config", {"kubernetes_host": "https://kubernetes.default.svc:443"})

    namespaces = set()
    for path in root.rglob("*.yml"):
        for document in yaml.safe_load_all(path.read_text()):
            if not isinstance(document, dict) or document.get("kind") != "VaultAuth":
                continue
            namespace = document["metadata"]["namespace"]
            config = document["spec"]["kubernetes"]
            if config["role"] != namespace or config["serviceAccount"] != "vault-auth":
                raise RuntimeError(f"Unexpected authentication contract in {path}")
            namespaces.add(namespace)
    if not namespaces:
        raise RuntimeError("No application VaultAuth definitions found")
    for namespace in sorted(namespaces):
        policy = f"lab-{namespace}"
        vault.request(f"sys/policies/acl/{policy}", {
            "policy": f'path "secret/data/{namespace}/*" {{ capabilities = ["read"] }}',
        })
        vault.request(f"auth/kubernetes/role/{namespace}", {
            "bound_service_account_names": ["vault-auth"],
            "bound_service_account_namespaces": [namespace],
            "audience": "vault",
            "token_policies": [policy],
            "token_ttl": 3600,
            "token_max_ttl": 14400,
        })
    print(f"KV v2 and Kubernetes authentication configured for {len(namespaces)} namespaces")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="https://127.0.0.1:8200")
    parser.add_argument("--credentials", type=Path, default=Path.home() / ".local/share/lab-vault/bootstrap.json")
    parser.add_argument("--configure", action="store_true", help="Configure Vault using a non-root VAULT_TOKEN")
    args = parser.parse_args()
    ca = base64.b64decode(subprocess.check_output([
        "kubectl", "get", "secret", "-n", "vault", "vault-server-tls",
        "-o", r"jsonpath={.data.ca\.crt}",
    ])).decode()
    vault = Vault(args.address, ca)
    credentials = protected_credentials(args.credentials, vault)
    sealed = vault.request("sys/seal-status")["sealed"]
    if sealed:
        for key in credentials["keys_base64"][:3]:
            result = vault.request("sys/unseal", {"key": key}, "PUT")
        if result["sealed"]:
            raise RuntimeError("Vault remains sealed")
    print("Vault is initialized and unsealed. No root token was used for authentication.")
    if args.configure:
        authenticate_operator(vault, credentials, os.environ.get("VAULT_TOKEN"))
        configure(vault, Path(__file__).resolve().parents[2])


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError, KeyError) as error:
        print(f"Bootstrap failed: {error}", file=sys.stderr)
        sys.exit(1)
