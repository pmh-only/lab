#!/usr/bin/env python3
"""Connect a read-only Kopia console to existing backups and admin-only OIDC.

Never initializes repositories, mounts live source data, rotates existing keys,
or changes the backup workers' Vault role. Remote credentials remain secret.
"""

import base64
import importlib.util
import io
import json
import secrets
import sys
import urllib.parse

from minio import Minio
from minio.error import S3Error

from oidc import Authentik, provision_client
from provision import ROOT
from s3 import Admin


ADMIN_EXPRESSION = 'return request.user.is_authenticated and request.user.is_active and request.user.is_superuser and request.user.type == "internal"'


def read_policy():
    return {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["s3:ListBucket", "s3:GetBucketLocation"], "Resource": ["arn:aws:s3:::kopia"]},
        {"Effect": "Allow", "Action": ["s3:GetObject"], "Resource": ["arn:aws:s3:::kopia/*"]},
    ]}


def read_identity(vault, admin):
    path = "kopia/ui-s3"
    data = vault.get(path)
    if data is None:
        data = {"access-key": "lab-kopia-ui-" + secrets.token_hex(8), "secret-key": secrets.token_urlsafe(48)}
        vault.create(path, data)
    if set(data) != {"access-key", "secret-key"} or not data["access-key"].startswith("lab-kopia-ui-") or len(data["secret-key"]) < 48:
        raise RuntimeError("Unmanaged UI S3 credential; refusing takeover")
    access = data["access-key"]
    policy_name = access + "-readonly"
    users, policies = admin.request("list-users"), admin.request("list-canned-policies")
    if access in users and users[access].get("policyName") not in {None, "", policy_name}:
        raise RuntimeError("UI identity has unexpected policies")
    if policy_name in policies:
        actual = admin.request("info-canned-policy?" + urllib.parse.urlencode({"name": policy_name}))["policy"]
        if actual != read_policy():
            raise RuntimeError("Existing read-only UI policy differs")
    else:
        admin.request("add-canned-policy?" + urllib.parse.urlencode({"name": policy_name}), read_policy(), "PUT")
    if access not in users:
        admin.request("add-user?" + urllib.parse.urlencode({"accessKey": access}), {"secretKey": data["secret-key"], "status": "enabled"}, "PUT")
    admin.request("idp/builtin/policy/attach", {"policies": [policy_name], "user": access}, "POST")
    client = Minio("127.0.0.1:19000", access_key=access, secret_key=data["secret-key"], secure=False, region="us-east-1")
    client.stat_object("kopia", "kopia.repository")
    key = "lab-ui-denied-probe/" + secrets.token_hex(16)
    try:
        client.put_object("kopia", key, io.BytesIO(b"denied write probe"), 18)
    except S3Error as error:
        if error.code != "AccessDenied":
            raise
    else:
        admin.s3.remove_object("kopia", key)
        raise RuntimeError("UI identity unexpectedly permits writes")
    try:
        client.remove_object("kopia", key)
    except S3Error as error:
        if error.code != "AccessDenied":
            raise
    else:
        raise RuntimeError("UI identity unexpectedly permits deletion")


def admin_policy(api):
    name = "lab bootstrap: kopia console administrators only"
    matches = [p for p in api.list("policies/expression/") if p["name"] == name]
    if len(matches) > 1:
        raise RuntimeError("Ambiguous application access policy")
    if matches:
        policy = matches[0]
        if policy["expression"] != ADMIN_EXPRESSION or policy.get("execution_logging", False):
            raise RuntimeError("Existing application access policy differs")
    else:
        policy = api.request("policies/expression/", {"name": name, "expression": ADMIN_EXPRESSION, "execution_logging": False})
    app = api.request("core/applications/kopia/")
    if app["policy_engine_mode"] != "all":
        raise RuntimeError("Application must require all access policies")
    bindings = api.list("policies/bindings/?target=" + app["pk"])
    existing = [b for b in bindings if b.get("policy") == policy["pk"]]
    if len(existing) > 1:
        raise RuntimeError("Ambiguous application policy binding")
    desired = {"policy": policy["pk"], "target": app["pk"], "order": 0, "enabled": True, "negate": False, "dry_run": False, "failure_result": False, "timeout": 30}
    if existing:
        # Older Authentik APIs omit dry_run entirely (policies are enforced).
        # Still reject an explicitly enabled dry-run binding if supported.
        if any(existing[0].get(k, False if k == "dry_run" else None) != value for k, value in desired.items()):
            raise RuntimeError("Application access binding differs")
    else:
        api.request("policies/bindings/", desired)
    users = api.list("core/users/")
    allowed = [u for u in users if u["is_active"] and u["is_superuser"] and u["type"] == "internal"]
    denied = [u for u in users if not (u["is_active"] and u["is_superuser"] and u["type"] == "internal")]
    if not allowed or not denied:
        raise RuntimeError("Existing admin and non-admin subjects are required for native policy tests")
    for user, expected in [(allowed[0], True), (denied[0], False)]:
        result = api.request("policies/all/" + policy["pk"] + "/test/", {"user": user["pk"]})
        if result["passing"] is not expected:
            raise RuntimeError("Native application authorization test failed")


def ui_secrets(vault):
    repository_password = vault.get("kopia/s3")["REPOSITORY_PASSWORD"]
    path = "kopia/ui-auth"
    data = vault.get(path)
    if data is None:
        password = secrets.token_urlsafe(48)
        data = {"server-password": password, "repository-password": repository_password,
                "proxy-authorization": "Basic " + base64.b64encode(("lab-console:" + password).encode()).decode()}
        vault.create(path, data)
    desired_header = "Basic " + base64.b64encode(("lab-console:" + data["server-password"]).encode()).decode()
    if (set(data) != {"server-password", "repository-password", "proxy-authorization"} or len(data["server-password"]) < 48
            or data["repository-password"] != repository_password or data["proxy-authorization"] != desired_header):
        raise RuntimeError("Existing console passwords differ; refusing implicit changes")
    paths = ["kopia/ui-s3", "kopia/ui-auth", "kopia/kopia-auth-secret"]
    vault.run("policy", "write", "lab-kopia-ui", "-", payload="".join('path "secret/data/' + p + '" { capabilities = ["read"] }\n' for p in paths))
    vault.run("write", "auth/kubernetes/role/kopia-ui", "-", payload=json.dumps({
        "bound_service_account_names": ["kopia-ui-auth"], "bound_service_account_namespaces": ["kopia"],
        "audience": "vault", "token_policies": ["lab-kopia-ui"], "token_ttl": 3600, "token_max_ttl": 14400,
    }))


def main():
    spec = importlib.util.spec_from_file_location("dns01_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    supplied = vault.get("backup/rustfs-admin")
    admin = Admin(supplied["access_key"], supplied["secret_key"], "http://127.0.0.1:19000")
    if not admin.s3.bucket_exists("kopia"):
        raise RuntimeError("Existing initialized backup repository is required")
    read_identity(vault, admin)
    api = Authentik(vault.get("authentik/bootstrap-worker")["AUTHENTIK_BOOTSTRAP_TOKEN"])
    declaration = json.loads((ROOT / "bootstrap/services/oidc.json").read_text())["kopia"]
    provision_client(vault, api, "kopia", declaration)
    admin_policy(api)
    ui_secrets(vault)
    print("Kopia UI: read-only S3 enforced; native admin/non-admin access tests passed; backup worker keys and reader permissions unchanged")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, S3Error):
        print("Kopia UI provisioning failed; credential-bearing details suppressed", file=sys.stderr)
        sys.exit(1)
