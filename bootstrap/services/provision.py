#!/usr/bin/env python3
"""Provision fresh local service credentials; never fabricate external API keys."""

import argparse
import base64
import importlib.util
import json
from pathlib import Path
import re
import secrets
import struct
import subprocess
import sys
import textwrap
import urllib.parse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey


ROOT = Path(__file__).resolve().parents[2]
PROFILES = {
    "speed": ("speed/speed-secret", {"PASSWORD": "random", "IPINFO_APIKEY": "optional-empty"}),
    "here": ("here/here-secret", {"SSH_PASSWORD": "random"}),
    "minio": ("minio/minio-secrets", {"MINIO_ROOT_USER": "random", "MINIO_ROOT_PASSWORD": "random"}),
    "heartbeat": ("heartbeat/heartbeat-secret", {"DATABASE_URL": "postgres:heartbeat"}),
    "keysboard": ("keysboard/keysboard-secret", {"DATABASE_URL": "postgres:keysboard", "REDIS_URL": "redis", "JWT_SECRET": "random"}),
    "mail": ("mail/mailui-secret", {"DATABASE_URL": "postgres:mailui", "BETTER_AUTH_SECRET": "random", "MAIL_SECRET_KEY": "random"}),
}


def generated(kind):
    if kind.startswith("postgres:"):
        role = kind.split(":", 1)[1]
        return f"postgresql://{role}:{secrets.token_urlsafe(48)}@pgsql-service.database.svc.cluster.local:5432/{role}"
    if kind == "redis":
        return "redis://redis-service.database.svc.cluster.local:6379/1"
    return secrets.token_urlsafe(48) if kind == "random" else ""


def valid_field(value, kind):
    if not isinstance(value, str):
        return False
    if kind == "random":
        return len(value) >= 48
    if kind.startswith("postgres:"):
        role = kind.split(":", 1)[1]
        parsed = urllib.parse.urlsplit(value)
        return parsed.scheme == "postgresql" and parsed.hostname == "pgsql-service.database.svc.cluster.local" and parsed.username == role and parsed.path == "/" + role and len(parsed.password or "") >= 48
    if kind == "redis":
        return value == generated("redis")
    return kind == "optional-empty"


def sql(statement, database="postgres"):
    result = subprocess.run(["kubectl", "exec", "-i", "-n", "database", "deployment/pgsql", "-c", "pgsql", "--", "psql", "-U", "admin", "-d", database, "-v", "ON_ERROR_STOP=1", "-At"],
                            input=statement, text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError("Service database provisioning failed; SQL/error bodies suppressed")
    return result.stdout.strip()


def postgres_database(url):
    parsed = urllib.parse.urlsplit(url)
    role = parsed.username
    if not role or not re.fullmatch("[a-z][a-z0-9_]*", role) or parsed.path != "/" + role:
        raise RuntimeError("Unsafe managed PostgreSQL identity")
    marker = "lab-service-bootstrap-v1:" + role
    state = json.loads(sql(f"""SELECT json_build_object(
 'role', (SELECT row_to_json(r) FROM (SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolcanlogin,shobj_description(oid,'pg_authid') AS marker FROM pg_roles WHERE rolname='{role}') r),
 'database', (SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='{role}'),
 'memberships', (SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON m.member=r.oid WHERE r.rolname='{role}'));"""))
    existing = state["role"]
    if existing and (existing["marker"] != marker or any(existing[k] for k in ["rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication"]) or not existing["rolcanlogin"] or state["memberships"]):
        raise RuntimeError("Existing PostgreSQL role is not safely managed; refusing modification")
    if state["database"] and (state["database"] != role or not existing):
        raise RuntimeError("Existing service database has an unexpected owner")
    if not existing:
        password = parsed.password.replace("'", "''")
        sql(f"CREATE ROLE {role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '{password}'; COMMENT ON ROLE {role} IS '{marker}';")
    if not state["database"]:
        sql(f"CREATE DATABASE {role} OWNER {role};")
    sql(f"REVOKE ALL ON DATABASE {role} FROM PUBLIC;")
    sql("REVOKE CREATE ON SCHEMA public FROM PUBLIC;", role)
    command = ["kubectl", "exec", "-i", "-n", "database", "deployment/pgsql", "-c", "pgsql", "--", "sh", "-c",
               f'IFS= read -r PGPASSWORD; export PGPASSWORD; exec psql -h pgsql-service.database.svc.cluster.local -U {role} -d {role} -At -c "SELECT current_user"']
    good = subprocess.run(command, input=parsed.password + "\n", text=True, capture_output=True, timeout=30)
    bad = subprocess.run(command, input=secrets.token_urlsafe(48) + "\n", text=True, capture_output=True, timeout=30)
    if good.returncode or good.stdout.strip() != role or not bad.returncode:
        raise RuntimeError("Service DB credential positive/negative verification failed")
    print(f"{role}: dedicated non-superuser database verified; wrong password rejected")


def fresh_ech(public_name="pmh.codes"):
    private = X25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    name = public_name.encode("ascii")
    content = struct.pack("!BHH", secrets.randbelow(256), 0x20, len(public)) + public
    content += struct.pack("!HHHHH", 8, 1, 1, 1, 3)  # HKDF-SHA256 / AES128-GCM and ChaCha20-Poly1305
    content += bytes([0, len(name)]) + name + b"\0\0"
    config = struct.pack("!HH", 0xfe0d, len(content)) + content
    config_list = struct.pack("!H", len(config)) + config
    encoded = base64.b64encode(config_list).decode()
    pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    pem += "-----BEGIN ECHCONFIG-----\n" + "\n".join(textwrap.wrap(encoded, 64)) + "\n-----END ECHCONFIG-----\n"
    return {"server.ech.pem": pem}


def validate_ech(data):
    if set(data) != {"server.ech.pem"}:
        raise RuntimeError("Existing ECH data has unexpected fields")
    pem = data["server.ech.pem"]
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, X25519PrivateKey):
        raise RuntimeError("Existing ECH key is not X25519")
    encoded = pem.split("-----BEGIN ECHCONFIG-----\n", 1)[1].split("-----END ECHCONFIG-----", 1)[0]
    raw = base64.b64decode(encoded, validate=False)
    if len(raw) < 45 or struct.unpack("!H", raw[:2])[0] != len(raw) - 2 or raw[2:4] != b"\xfe\x0d":
        raise RuntimeError("Existing ECHConfigList is malformed")
    if struct.unpack("!HH", raw[7:11]) != (0x20, 32):
        raise RuntimeError("Existing ECH key parameters differ")
    if raw[11:43] != key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw):
        raise RuntimeError("Existing ECH public/private keys do not match")


def reader(vault, namespace, path):
    vault.run("policy", "write", "lab-" + namespace, "-", payload=f'path "secret/data/{path}" {{ capabilities = ["read"] }}\n')
    vault.run("write", "auth/kubernetes/role/" + namespace, "-", payload=json.dumps({
        "bound_service_account_names": ["vault-auth"], "bound_service_account_namespaces": [namespace],
        "audience": "vault", "token_policies": ["lab-" + namespace], "token_ttl": 3600, "token_max_ttl": 14400,
    }))


def provision(vault, name):
    if name == "gateway":
        path = "gateway/gateway-ech-secrets"
        data = vault.get(path)
        if data is None:
            data = fresh_ech()
            validate_ech(data)
            vault.create(path, data)
        validate_ech(data)
    else:
        path, fields = PROFILES[name]
        data = vault.get(path)
        if data is None:
            data = {field: generated(kind) for field, kind in fields.items()}
            vault.create(path, data)
        if set(data) != set(fields) or any(not valid_field(data[field], kind) for field, kind in fields.items()):
            raise RuntimeError("Existing service credentials need manual review")
        for field, kind in fields.items():
            if kind.startswith("postgres:"):
                postgres_database(data[field])
    reader(vault, name, path)
    print(f"{name}: managed fresh credentials present; no values printed or rotated")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("services", nargs="+", choices=[*PROFILES, "gateway"])
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("dns01_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    for name in args.services:
        provision(vault, name)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, IndexError) as error:
        print(f"Service provisioning failed: {error}", file=sys.stderr)
        sys.exit(1)
