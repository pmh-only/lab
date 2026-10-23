#!/usr/bin/env python3
"""Provision native thepool storage without replacing credentials or existing data."""

import base64
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import secrets
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from minio.error import S3Error
from minio.signer import sign_v4_s3

from provision import ROOT, generated, mysql_database, mysql_sql, reader, valid_field
from s3 import Admin, provision as provision_s3, public_download_policy


PATH = "thepool/thepool-secret"
INTERNAL = {"DATABASE_PASSWORD": "random", "DISCORD_AUTH_TOKEN": "random", "MINIO_ACCESS_KEY_ID": "s3-access:thepool", "MINIO_SECRET_ACCESS_KEY": "random"}
CORS = b'''<CORSConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><CORSRule><AllowedOrigin>https://pool.pmh.codes</AllowedOrigin><AllowedMethod>GET</AllowedMethod><AllowedMethod>HEAD</AllowedMethod><AllowedHeader>*</AllowedHeader><ExposeHeader>ETag</ExposeHeader><ExposeHeader>Content-Length</ExposeHeader><ExposeHeader>Content-Range</ExposeHeader><ExposeHeader>Accept-Ranges</ExposeHeader></CORSRule></CORSConfiguration>'''


def complete_credentials(data):
    if not data or not isinstance(data.get("DISCORD_CLIENT_SECRET"), str) or not data["DISCORD_CLIENT_SECRET"].strip():
        raise RuntimeError("Genuine supplied Discord Client Secret is required")
    result = dict(data)
    for field, kind in INTERNAL.items():
        if field not in result:
            result[field] = generated(kind)
        elif not valid_field(result[field], kind):
            raise RuntimeError("Existing internal credential requires manual review")
    return result


def schema():
    manifest = json.loads((ROOT / "thepool/source.json").read_text())
    url = f"https://raw.githubusercontent.com/{manifest['repository']}/{manifest['commit']}/database.sql"
    body = urllib.request.urlopen(url, timeout=30).read()
    if hashlib.sha256(body).hexdigest() != manifest["files"]["database.sql"]:
        raise RuntimeError("Native schema hash differs")
    return body.decode()


def initialize_database(password):
    dsn = f"thepool:{password}@tcp(mysql-service.database.svc.cluster.local:3306)/thepool?charset=utf8mb4&parseTime=true&loc=UTC"
    mysql_database(dsn, "mysql-dsn:thepool")
    current = json.loads(mysql_sql("""SELECT JSON_OBJECT(
      'tables',(SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='thepool'),
      'triggers',(SELECT COUNT(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA='thepool'),
      'routines',(SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA='thepool'));"""))
    if current in [{"tables": 0, "triggers": 0, "routines": 0}, {"tables": 3, "triggers": 0, "routines": 0}]:
        body = schema()
        if current["tables"]:
            empty = json.loads(mysql_sql("SELECT JSON_OBJECT('chunks',(SELECT COUNT(*) FROM thepool.chunks),'collections',(SELECT COUNT(*) FROM thepool.collections),'totalsRows',(SELECT COUNT(*) FROM thepool.totals),'total',(SELECT total FROM thepool.totals WHERE id=1));"))
            if empty != {"chunks": 0, "collections": 0, "totalsRows": 1, "total": 0}:
                raise RuntimeError("Partial schema contains data; refusing automatic repair")
            # Resume only our empty managed bootstrap interrupted by MySQL's
            # log_bin_trust_function_creators=OFF restriction. Do not reset tables.
            body = body[body.index("DELIMITER $$"):]
        # Keep binary-log protections and global privileges unchanged. The
        # operator installs DDL with an explicit non-root service DEFINER.
        body = body.replace("CREATE TRIGGER ", "CREATE DEFINER=`thepool`@`%` TRIGGER ")
        body = body.replace("CREATE PROCEDURE ", "CREATE DEFINER=`thepool`@`%` PROCEDURE ")
        mysql_sql("USE thepool;\n"+body)
    elif current != {"tables": 3, "triggers": 3, "routines": 1}:
        raise RuntimeError("Existing database layout differs; refusing schema reset")
    proof = json.loads(mysql_sql("""SELECT JSON_OBJECT(
      'tables',(SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='thepool'),
      'triggers',(SELECT COUNT(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA='thepool'),
      'routines',(SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA='thepool'),
      'foreignDefiners',(SELECT COUNT(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA='thepool' AND DEFINER<>'thepool@%')+(SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA='thepool' AND DEFINER<>'thepool@%'),
      'totalMatches',(SELECT total=(SELECT COALESCE(SUM(chunk_size),0) FROM thepool.chunks) FROM thepool.totals WHERE id=1));"""))
    if proof != {"tables": 3, "triggers": 3, "routines": 1, "foreignDefiners": 0, "totalMatches": 1}:
        raise RuntimeError("Native schema/retention trigger verification failed")


def cors_identity(xml):
    root = ET.fromstring(xml)
    return sorted(tuple(sorted((child.tag.split('}')[-1], child.text or '') for child in rule)) for rule in root)


def cors_request(admin, method, body=None):
    url = urllib.parse.urlsplit("https://s3.pmh.codes/a-s?cors=")
    now = datetime.now(timezone.utc)
    digest = hashlib.sha256(body or b"").hexdigest()
    headers = {"Host": url.netloc, "X-Amz-Date": now.strftime("%Y%m%dT%H%M%SZ"), "X-Amz-Content-Sha256": digest}
    if body is not None:
        headers.update({"Content-Type": "application/xml", "Content-MD5": base64.b64encode(hashlib.md5(body).digest()).decode()})
    headers = sign_v4_s3(method=method, url=url, region="us-east-1", headers=headers, credentials=admin.credentials, content_sha256=digest, date=now)
    try:
        with urllib.request.urlopen(urllib.request.Request(url.geturl(), data=body, headers=headers, method=method), timeout=30) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if method == "GET" and error.code == 404:
            code = ET.fromstring(error.read()).findtext("Code")
            if code == "NoSuchCORSConfiguration":
                return None
        raise RuntimeError("Native bucket CORS operation failed; details suppressed") from None


def initialize_downloads(admin):
    client = admin.s3
    desired = public_download_policy("a-s")
    try:
        existing = json.loads(client.get_bucket_policy("a-s"))
    except S3Error as error:
        if error.code != "NoSuchBucketPolicy":
            raise
        if next(client.list_objects("a-s", recursive=True), None) is not None:
            raise RuntimeError("Existing unreviewed data would become public")
        client.set_bucket_policy("a-s", json.dumps(desired))
    else:
        if existing != desired:
            raise RuntimeError("Existing bucket policy differs; refusing changes")
    current = cors_request(admin, "GET")
    if current is None:
        cors_request(admin, "PUT", CORS)
    elif cors_identity(current) != cors_identity(CORS):
        raise RuntimeError("Existing download CORS differs; refusing overwrite")
    if cors_identity(cors_request(admin, "GET")) != cors_identity(CORS):
        raise RuntimeError("Native bucket CORS readback differs")


def provision(vault, admin):
    original = vault.get(PATH)
    updated = complete_credentials(original)
    if updated != original:
        version = json.loads(vault.run("kv", "metadata", "get", "-format=json", "-mount=secret", PATH))["data"]["current_version"]
        vault.run("kv", "put", "-cas="+str(version), "-mount=secret", PATH, "-", payload=json.dumps(updated))
    initialize_database(updated["DATABASE_PASSWORD"])
    provision_s3(vault, admin, "thepool")
    initialize_downloads(admin)
    reader(vault, "thepool", PATH)
    print("thepool: native schema/retention and bucket-scoped storage initialized; supplied Discord secret and existing data preserved")


def main():
    spec = importlib.util.spec_from_file_location("dns_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    root = vault.get("minio/minio-secrets")
    provision(vault, Admin(root["MINIO_ROOT_USER"], root["MINIO_ROOT_PASSWORD"]))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, S3Error) as error:
        raise SystemExit(f"thepool provisioning failed: {type(error).__name__}; credentials and response bodies suppressed")
