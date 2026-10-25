#!/usr/bin/env python3
"""Provision remote backup-only identities without changing existing backups.

Use a loopback port-forward through the temporary cluster relay. Never put
remote administrator credentials in Kubernetes workloads or overwrite policies.
"""

import argparse
import importlib.util
import io
import json
import secrets
import sys
import urllib.parse

from minio import Minio
from minio.error import S3Error

from provision import ROOT
from s3 import Admin, bucket_policy


PROFILES = {
    "database": {"path": "database/backpack-secrets", "bucket": "dbdump", "delete": False},
    "velero": {"path": "velero/s3", "bucket": "velero", "delete": True},
    "kopia": {"path": "kopia/s3", "bucket": "kopia", "delete": True},
}


def mongo_backup_user(vault):
    from mongo import shell

    path = PROFILES["database"]["path"]
    data = vault.get(path)
    if "MONGO_BACKPACK_PASSWORD" not in data:
        metadata = json.loads(vault.run("kv", "metadata", "get", "-format=json", "-mount=secret", path))["data"]
        data = {**data, "MONGO_BACKPACK_PASSWORD": secrets.token_urlsafe(48)}
        vault.run("kv", "put", "-cas=" + str(metadata["current_version"]), "-mount=secret", path, "-", payload=json.dumps(data))
    root = vault.get("database/mongo-root-password")
    payload = json.dumps({"root": root, "password": data["MONGO_BACKPACK_PASSWORD"]})
    shell("const input=" + payload + ";\n" + r"""
const admin = db.getSiblingDB('admin');
if (admin.auth(input.root.username, input.root.password).ok !== 1) throw new Error('Administrator authentication failed');
let user = admin.getUser('backpack');
if (!user) {
  admin.createUser({user:'backpack', pwd:input.password, roles:[{role:'backup', db:'admin'}],
    customData:{managedBy:'lab-remote-backup-v1'}});
  user = admin.getUser('backpack');
}
if (user.customData?.managedBy !== 'lab-remote-backup-v1' || user.roles.length !== 1 ||
    user.roles[0].role !== 'backup' || user.roles[0].db !== 'admin') throw new Error('Unmanaged backup user; no takeover');
const uri = 'mongodb://backpack:' + encodeURIComponent(input.password) + '@127.0.0.1:27017/admin';
const backup = new Mongo(uri).getDB('admin');
if (backup.runCommand({listDatabases:1, nameOnly:true}).ok !== 1) throw new Error('Backup login failed');
let denied = false;
try { backup.getSiblingDB('your_spotify').getCollection('lab_backup_denied_probe').insertOne({probe:true}); }
catch (error) { if (error.code !== 13) throw error; denied = true; }
if (!denied) throw new Error('Backup identity has unexpected write privileges');
print('LAB_MONGO_OK');
""")
    print("MongoDB dedicated backup role provisioned; authentication succeeds and application writes are denied")


def reconcile(vault, admin, name, endpoint):
    profile = PROFILES[name]
    data = vault.get(profile["path"])
    if data is None:
        data = {"S3_ACCESS_TOKEN": "lab-backup-" + name + "-" + secrets.token_hex(8),
                "S3_SECRET_TOKEN": secrets.token_urlsafe(48)}
        vault.create(profile["path"], data)
    access, secret = data["S3_ACCESS_TOKEN"], data["S3_SECRET_TOKEN"]
    if not access.startswith("lab-backup-" + name + "-") or len(secret) < 48:
        raise RuntimeError("Unmanaged backup identity; refusing takeover")
    policy_name = access + "-bucket"
    policy = bucket_policy(profile["bucket"], delete=profile["delete"])
    users, policies = admin.request("list-users"), admin.request("list-canned-policies")
    if access in users and users[access].get("policyName") not in {None, "", policy_name}:
        raise RuntimeError("Backup identity has unrelated policies")
    if policy_name in policies:
        actual = admin.request("info-canned-policy?" + urllib.parse.urlencode({"name": policy_name}))["policy"]
        if actual != policy:
            raise RuntimeError("Existing backup policy differs; refusing replacement")
    else:
        admin.request("add-canned-policy?" + urllib.parse.urlencode({"name": policy_name}), policy, "PUT")
    if access not in users:
        admin.request("add-user?" + urllib.parse.urlencode({"accessKey": access}), {"secretKey": secret, "status": "enabled"}, "PUT")
    admin.request("idp/builtin/policy/attach", {"policies": [policy_name], "user": access}, "POST")
    if not admin.s3.bucket_exists(profile["bucket"]):
        admin.s3.make_bucket(profile["bucket"])
    url = urllib.parse.urlsplit(endpoint)
    client = Minio(url.netloc, access_key=access, secret_key=secret, secure=url.scheme == "https", region="us-east-1")
    key, body = "lab-credential-check/" + secrets.token_hex(16), b"backup scoped identity check\n"
    try:
        client.put_object(profile["bucket"], key, io.BytesIO(body), len(body))
        response = client.get_object(profile["bucket"], key)
        try:
            if response.read() != body:
                raise RuntimeError("Backup S3 round-trip mismatch")
        finally:
            response.close()
            response.release_conn()
        if not profile["delete"]:
            try:
                client.remove_object(profile["bucket"], key)
            except S3Error as error:
                if error.code != "AccessDenied":
                    raise
            else:
                raise RuntimeError("Append-only database backup identity unexpectedly allows deletion")
    finally:
        admin.s3.remove_object(profile["bucket"], key)
    print(name + ": remote backup-only S3 identity verified; existing objects and policies preserved")
    return client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:19000")
    args = parser.parse_args()
    if urllib.parse.urlsplit(args.endpoint).hostname != "127.0.0.1":
        raise RuntimeError("Only the private loopback relay is accepted")
    spec = importlib.util.spec_from_file_location("dns01_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    supplied = vault.get("backup/rustfs-admin")
    if not supplied or set(supplied) != {"access_key", "secret_key"}:
        raise RuntimeError("Supplied remote RustFS administrator credential is missing")
    admin = Admin(supplied["access_key"], supplied["secret_key"], args.endpoint)
    clients = {name: reconcile(vault, admin, name, args.endpoint) for name in PROFILES}
    for name, client in clients.items():
        foreign = next(p["bucket"] for n, p in PROFILES.items() if n != name)
        key, body = "lab-credential-check/" + secrets.token_hex(16), b"isolation check\n"
        try:
            client.put_object(foreign, key, io.BytesIO(body), len(body))
        except S3Error as error:
            if error.code != "AccessDenied":
                raise
        else:
            admin.s3.remove_object(foreign, key)
            raise RuntimeError("Backup identity can write to a foreign bucket")
    print("All three identities reject foreign-bucket writes; administrator credential is not mounted in any workload")
    mongo_backup_user(vault)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, S3Error):
        print("Remote backup provisioning failed; credential-bearing details suppressed", file=sys.stderr)
        sys.exit(1)
