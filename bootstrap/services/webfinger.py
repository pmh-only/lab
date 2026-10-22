#!/usr/bin/env python3
"""Publish the reviewed public WebFinger object without replacing unknown data."""

import importlib.util
import io
import json
from pathlib import Path
import sys
import urllib.request

from minio.error import S3Error

from provision import ROOT
from s3 import Admin, public_download_policy


BUCKET = "www"
KEY = ".well-known/webfinger"


def publish(client, body):
    new_bucket = not client.bucket_exists(BUCKET)
    policy = public_download_policy(BUCKET)
    missing_policy, missing_object = True, True
    if not new_bucket:
        try:
            existing = json.loads(client.get_bucket_policy(BUCKET))
        except S3Error as error:
            if error.code != "NoSuchBucketPolicy":
                raise
            if any(o.object_name != KEY for o in client.list_objects(BUCKET, recursive=True)):
                raise RuntimeError("Existing unreviewed www data would become public; refusing policy change")
        else:
            if existing != policy:
                raise RuntimeError("Existing www policy differs; refusing permission changes")
            missing_policy = False
        try:
            response = client.get_object(BUCKET, KEY)
        except S3Error as error:
            if error.code not in {"NoSuchKey", "NoSuchObject"}:
                raise
        else:
            try:
                if json.loads(response.read()) != json.loads(body):
                    raise RuntimeError("Existing WebFinger object differs; refusing replacement")
                missing_object = False
            finally:
                response.close()
                response.release_conn()
    # Validate all existing content/policies before any create, publish or write.
    if new_bucket:
        client.make_bucket(BUCKET)
    if missing_policy:
        client.set_bucket_policy(BUCKET, json.dumps(policy))
    if missing_object:
        client.put_object(BUCKET, KEY, io.BytesIO(body), len(body), content_type="application/jrd+json")
    response = client.get_object(BUCKET, KEY)
    try:
        if json.loads(response.read()) != json.loads(body):
            raise RuntimeError("Native S3 WebFinger readback differs")
    finally:
        response.close()
        response.release_conn()


def main():
    document = ROOT / "minio_static/www/.well-known/webfinger"
    body = document.read_bytes()
    data = json.loads(body)
    declaration = json.loads(Path(__file__).with_name("oidc.json").read_text())["tailscale"]
    expected_issuer = "https://auth.pmh.codes/application/o/tailscale/"
    if data != {"subject": "acct:pmh_only@pmh.codes", "links": [{"rel": "http://openid.net/specs/connect/1.0/issuer", "href": expected_issuer}]}:
        raise RuntimeError("WebFinger differs from the reviewed domain and issuer")
    with urllib.request.urlopen(expected_issuer + ".well-known/openid-configuration", timeout=20) as response:
        discovery = json.load(response)
    if discovery["issuer"] != expected_issuer:
        raise RuntimeError("OIDC discovery issuer does not match WebFinger")
    with urllib.request.urlopen(discovery["jwks_uri"], timeout=20) as response:
        jwks = json.load(response)
    import base64
    rsa = [k for k in jwks["keys"] if k.get("kty") == "RSA"]
    if not rsa or max(int.from_bytes(base64.urlsafe_b64decode(k["n"] + "=" * (-len(k["n"]) % 4)), "big").bit_length() for k in rsa) < 2048:
        raise RuntimeError("Tailscale requires a supported signing key of sufficient strength")
    if declaration["redirectURI"] != "https://login.tailscale.com/a/oauth_response":
        raise RuntimeError("Unexpected Tailscale callback")
    spec = importlib.util.spec_from_file_location("dns01_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    root = vault.get("minio/minio-secrets")
    publish(Admin(root["MINIO_ROOT_USER"], root["MINIO_ROOT_PASSWORD"]).s3, body)
    print("www WebFinger published/read back through native S3; public object-read only, no public list/write; existing data preserved")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, S3Error) as error:
        print(f"WebFinger publication failed: {type(error).__name__}; details/credentials suppressed", file=sys.stderr)
        sys.exit(1)
