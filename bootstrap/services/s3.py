#!/usr/bin/env python3
"""Provision fresh bucket-scoped RustFS identities through its native admin API."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

from minio import Minio
from minio.credentials import Credentials
from minio.error import S3Error
from minio.signer import sign_v4_s3

from provision import ROOT, generated, reader, valid_field


PROFILES = {
    "indexgen": {"namespace": "indexgen", "path": "indexgen/indexgen-secrets", "access": "S3_ACCESS_TOKEN", "secret": "S3_SECRET_TOKEN", "bucket": "pub", "delete": False},
    "books": {"namespace": "books", "path": "books/books-secret", "access": "S3_ACCESS_KEY_ID", "secret": "S3_SECRET_ACCESS_KEY", "bucket": "books", "delete": True},
    "monitoring": {"namespace": "monitoring", "path": "monitoring/thanos-secrets", "access": "access_key", "secret": "secret_key", "bucket": "thanos", "delete": True},
}


def bucket_policy(bucket, delete=False):
    actions = ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"]
    if delete:
        actions.append("s3:DeleteObject")
    return {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["s3:ListBucket", "s3:GetBucketLocation", "s3:ListBucketMultipartUploads"], "Resource": ["arn:aws:s3:::" + bucket]},
        {"Effect": "Allow", "Action": actions, "Resource": ["arn:aws:s3:::" + bucket + "/*"]},
    ]}


def public_download_policy(bucket):
    return {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"AWS": ["*"]},
        "Action": ["s3:GetObject"], "Resource": ["arn:aws:s3:::" + bucket + "/*"]}]}


class Admin:
    def __init__(self, access, secret):
        self.credentials = Credentials(access, secret)
        self.s3 = Minio("s3.pmh.codes", access_key=access, secret_key=secret, secure=True, region="us-east-1")

    def request(self, path, data=None, method="GET"):
        body = None if data is None else json.dumps(data, separators=(",", ":")).encode()
        url = urllib.parse.urlsplit("https://s3.pmh.codes/rustfs/admin/v3/" + path)
        now = datetime.now(timezone.utc)
        digest = hashlib.sha256(body or b"").hexdigest()
        headers = {"Host": url.netloc, "X-Amz-Date": now.strftime("%Y%m%dT%H%M%SZ"), "X-Amz-Content-Sha256": digest}
        if body is not None:
            headers["Content-Type"] = "application/json"
        headers = sign_v4_s3(method=method, url=url, region="us-east-1", headers=headers,
                             credentials=self.credentials, content_sha256=digest, date=now)
        try:
            with urllib.request.urlopen(urllib.request.Request(url.geturl(), data=body, headers=headers, method=method), timeout=30) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"RustFS admin HTTP {error.code}; credentials and response suppressed") from None


def verify_credentials(admin, profile, data):
    access, secret, bucket = data[profile["access"]], data[profile["secret"]], profile["bucket"]
    client = Minio("s3.pmh.codes", access_key=access, secret_key=secret, secure=True, region="us-east-1")
    key = "lab-credential-check/" + secrets.token_hex(16)
    body = b"fresh scoped S3 identity check\n"
    try:
        list(client.list_objects(bucket, prefix=key))
        client.put_object(bucket, key, io.BytesIO(body), len(body))
        response = client.get_object(bucket, key)
        try:
            assert response.read() == body
        finally:
            response.close()
            response.release_conn()
    finally:
        # Only our unique smoke-test key is removed; application data is untouched.
        admin.s3.remove_object(bucket, key)
    foreign = "hello"
    try:
        client.put_object(foreign, key, io.BytesIO(body), len(body))
    except S3Error as error:
        assert error.code == "AccessDenied", "Unexpected S3 authorization error"
    else:
        admin.s3.remove_object(foreign, key)
        raise RuntimeError("Scoped S3 identity unexpectedly wrote to another bucket")
    bad = Minio("s3.pmh.codes", access_key=access, secret_key=secrets.token_urlsafe(48), secure=True, region="us-east-1")
    try:
        list(bad.list_objects(bucket, prefix=key))
    except S3Error as error:
        assert error.code in {"SignatureDoesNotMatch", "AccessDenied", "InvalidAccessKeyId"}
    else:
        raise RuntimeError("Invalid S3 credential unexpectedly succeeded")


def provision(vault, admin, name):
    profile = PROFILES[name]
    data = vault.get(profile["path"])
    if data is None:
        if name != "monitoring":
            raise RuntimeError("Provision the service's other fresh credentials first")
        data = {profile["access"]: generated("s3-access:" + name), profile["secret"]: secrets.token_urlsafe(48)}
        vault.create(profile["path"], data)
    access = data[profile["access"]]
    if not valid_field(access, "s3-access:" + name) or not valid_field(data[profile["secret"]], "random"):
        raise RuntimeError("Existing S3 credentials are not a recognized fresh managed identity")
    policy_name = access + "-bucket"
    desired = bucket_policy(profile["bucket"], profile["delete"])
    users = admin.request("list-users")
    policies = admin.request("list-canned-policies")
    if access in users and users[access].get("policyName") not in {None, "", policy_name}:
        raise RuntimeError("Existing S3 identity has unrelated policies; refusing takeover")
    if policy_name in policies:
        existing = admin.request("info-canned-policy?" + urllib.parse.urlencode({"name": policy_name}))["policy"]
        if existing != desired:
            raise RuntimeError("Existing scoped policy differs; refusing silent privilege changes")
    else:
        admin.request("add-canned-policy?" + urllib.parse.urlencode({"name": policy_name}), desired, "PUT")
    if access not in users:
        admin.request("add-user?" + urllib.parse.urlencode({"accessKey": access}), {"secretKey": data[profile["secret"]], "status": "enabled"}, "PUT")
    admin.request("idp/builtin/policy/attach", {"policies": [policy_name], "user": access}, "POST")
    bucket = profile["bucket"]
    if not admin.s3.bucket_exists(bucket):
        admin.s3.make_bucket(bucket)
    if name == "indexgen":
        # pub is the original public download/index bucket; books and thanos
        # stay private. Never replace an unrelated existing bucket policy.
        public_policy = public_download_policy(bucket)
        try:
            existing = json.loads(admin.s3.get_bucket_policy(bucket))
        except S3Error as error:
            if error.code != "NoSuchBucketPolicy":
                raise
            admin.s3.set_bucket_policy(bucket, json.dumps(public_policy))
        else:
            if existing != public_policy:
                raise RuntimeError("Existing public bucket policy differs; refusing replacement")
    verify_credentials(admin, profile, data)
    paths = [profile["path"]]
    if name == "monitoring":
        paths.append("monitoring/monitoring-secret")
    reader(vault, profile["namespace"], paths)
    print(f"{name}: bucket-scoped S3 read/write verified; foreign bucket writes and invalid credentials rejected; values suppressed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("services", nargs="+", choices=sorted(PROFILES))
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("dns01_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    root = vault.get("minio/minio-secrets")
    admin = Admin(root["MINIO_ROOT_USER"], root["MINIO_ROOT_PASSWORD"])
    for name in args.services:
        provision(vault, admin, name)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, S3Error) as error:
        print(f"S3 provisioning failed: {type(error).__name__}; details suppressed", file=sys.stderr)
        sys.exit(1)
