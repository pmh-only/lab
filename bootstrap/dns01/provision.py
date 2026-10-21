#!/usr/bin/env python3
"""Provision fresh DNS01 credentials through a non-root Vault CLI login.

Requires an existing userpass CLI login in vault-0. Does not read bootstrap.json
or use root tokens. Credentials travel through stdin and are never printed.
DNS zone data and permissions are reconciled separately by the GitOps hook.
"""

import base64
import importlib.util
import json
from pathlib import Path
import secrets
import select
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
ACCOUNT_PATH = "nameserver/technitium-dns01-account"
TOKEN_PATH = "cert-manager/technitium-api-token"


class VaultCLI:
    def __init__(self):
        self.verified = False

    def run(self, *args, payload=None, missing_ok=False):
        if not self.verified and args != ("token", "lookup", "-format=json"):
            raise RuntimeError("Non-root operator authentication has not been verified")
        result = subprocess.run(
            ["kubectl", "exec", "-i", "-n", "vault", "vault-0", "--", "vault", *args],
            input=payload, text=True, capture_output=True, check=False, timeout=30,
        )
        if result.returncode:
            if missing_ok and result.returncode == 2 and "No value found" in result.stdout + result.stderr:
                return None
            raise RuntimeError(f"Vault command failed: {' '.join(args)}")
        return result.stdout

    def verify(self):
        data = json.loads(self.run("token", "lookup", "-format=json"))["data"]
        policies = set(data.get("policies", [])) | set(data.get("identity_policies", []))
        if "root" in policies or not data.get("path", "").startswith("auth/userpass/"):
            raise RuntimeError("Only a non-root userpass operator login is allowed")
        self.verified = True

    def get(self, path):
        result = self.run("kv", "get", "-format=json", "-mount=secret", path, missing_ok=True)
        return json.loads(result)["data"]["data"] if result is not None else None

    def create(self, path, data):
        self.run("kv", "put", "-cas=0", "-mount=secret", path, "-", payload=json.dumps(data))

    def configure_reader(self):
        self.run("policy", "write", "lab-cert-manager", "-", payload=(
            'path "secret/data/cert-manager/technitium-api-token" { capabilities = ["read"] }\n'
        ))
        self.run("write", "auth/kubernetes/role/cert-manager", "-", payload=json.dumps({
            "bound_service_account_names": ["vault-auth"],
            "bound_service_account_namespaces": ["cert-manager"],
            "audience": "vault",
            "token_policies": ["lab-cert-manager"],
            "token_ttl": 3600,
            "token_max_ttl": 14400,
        }))


def provision(vault, administrator, make_client, desired):
    username = desired["username"]
    users = administrator.post("admin/users/list")["response"]["users"]
    existing = next((user for user in users if user["username"] == username), None)
    credentials = vault.get(ACCOUNT_PATH)
    if existing and not credentials:
        raise RuntimeError("An existing DNS01 account has no managed Vault credentials; refusing to overwrite it")
    if credentials and (credentials.get("username") != username or not credentials.get("password")):
        raise RuntimeError("Stored DNS01 account credentials do not match the declared account")
    if existing and existing.get("displayName") != desired["displayName"]:
        raise RuntimeError("An existing DNS01 account has an unexpected owner; refusing to change it")
    if credentials is None:
        credentials = {"username": username, "password": secrets.token_urlsafe(48)}
        vault.create(ACCOUNT_PATH, credentials)
    if existing is None:
        administrator.post("admin/users/create", {
            "user": username, "pass": credentials["password"], "displayName": desired["displayName"],
        })
    user = administrator.post("admin/users/get", {"user": username})["response"]
    if user.get("disabled") or set(user.get("memberOfGroups", [])) - {"Everyone"}:
        raise RuntimeError("DNS01 service account is disabled or belongs to unexpected groups")
    stored = vault.get(TOKEN_PATH)
    if stored is not None:
        if set(stored) != {"api-token"} or not stored["api-token"]:
            raise RuntimeError("Existing API-token data has an unexpected format")
        print("Managed DNS01 credentials already exist; no token was rotated")
        return
    # No administrator bearer token: create the token for the service user only.
    client = make_client()
    result = client.post("user/createToken", {
        "user": username, "pass": credentials["password"], "tokenName": "cert-manager-dns01",
    })
    if result.get("username") != username or not result.get("token"):
        raise RuntimeError("API token was not issued for the expected DNS01 service user")
    token = result["token"]
    try:
        vault.create(TOKEN_PATH, {"api-token": token})
    except Exception:
        # If persistence succeeded but the response was lost, do not revoke it.
        persisted = vault.get(TOKEN_PATH)
        if not persisted or persisted.get("api-token") != token:
            client.token = token
            try:
                client.post("user/logout")
            finally:
                client.token = None
            raise
    print("Fresh DNS01 account password and separate API token stored in Vault; no credential values printed")


def main():
    vault = VaultCLI()
    vault.verify()
    vault.configure_reader()
    desired = json.loads((ROOT / "nameserver/configuration/dns01.json").read_text())
    module_spec = importlib.util.spec_from_file_location("dns_configuration", ROOT / "nameserver/configuration/configure.py")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    def secret(name):
        return json.loads(subprocess.check_output([
            "kubectl", "get", "secret", name, "-n", "nameserver", "-o", "json",
        ]))["data"]
    password = base64.b64decode(secret("nameserver-admin")["password"]).decode()
    certificate = base64.b64decode(secret("nameserver-tls-secret")["tls.crt"]).decode()
    forward = None
    administrator = None
    try:
        forward = subprocess.Popen([
            "kubectl", "port-forward", "-n", "nameserver", "svc/nameserver",
            "15343:53443", "--address=127.0.0.1",
        ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if not select.select([forward.stdout], [], [], 30)[0] or "Forwarding from" not in forward.stdout.readline():
            raise RuntimeError("DNS TLS port-forward could not be established")
        make_client = lambda: module.Client("https://127.0.0.1:15343", certificate)
        administrator = make_client()
        administrator.token = administrator.post("user/login", {"user": "admin", "pass": password})["token"]
        provision(vault, administrator, make_client, desired)
    finally:
        if administrator and administrator.token:
            try:
                administrator.post("user/logout")
            finally:
                administrator.token = None
        if forward:
            forward.terminate()
            try:
                forward.wait(timeout=10)
            except subprocess.TimeoutExpired:
                forward.kill()
                forward.wait(timeout=10)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f"DNS01 credential provisioning failed: {error}", file=sys.stderr)
        sys.exit(1)
