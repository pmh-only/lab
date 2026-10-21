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
    "codexlb": ("codexlb/bootstrap-login", {"ADMIN_PASSWORD": "random"}),
    "indexgen": ("indexgen/indexgen-secrets", {"S3_ACCESS_TOKEN": "s3-access:indexgen", "S3_SECRET_TOKEN": "random"}),
    "books": ("books/books-secret", {"DATABASE_URL": "postgres:books", "OIDC_CLIENT_SECRET": "random", "JWT_ACCESS_SECRET": "random", "JWT_REFRESH_SECRET": "random", "S3_ACCESS_KEY_ID": "s3-access:books", "S3_SECRET_ACCESS_KEY": "random"}),
    "monitoring": ("monitoring/monitoring-secret", {"GF_SECURITY_ADMIN_PASSWORD": "random", "GF_SECURITY_SECRET_KEY": "random", "GF_RENDERING_RENDERER_TOKEN": "random"}),
    "connect": ("connect/connect-secrets", {"COLLECT_TOKEN": "random", "MCP_TOKEN": "random", "ROSTACK_TOKEN": "random", "OIDC_CLIENT_SECRET": "random"}),
    "speed": ("speed/speed-secret", {"PASSWORD": "random", "IPINFO_APIKEY": "optional-empty"}),
    "here": ("here/here-secret", {"SSH_PASSWORD": "random"}),
    "minio": ("minio/minio-secrets", {"MINIO_ROOT_USER": "random", "MINIO_ROOT_PASSWORD": "random"}),
    "heartbeat": ("heartbeat/heartbeat-secret", {"DATABASE_URL": "mysql-dsn:heartbeat"}),
    "keysboard": ("keysboard/keysboard-secret", {"DATABASE_URL": "mysql-url:keysboard", "REDIS_URL": "redis", "JWT_SECRET": "random"}),
    "mail": ("mail/mailui-secret", {"DATABASE_URL": "postgres:mailui", "BETTER_AUTH_SECRET": "random", "MAIL_SECRET_KEY": "random"}),
    "office": ("office/office-secret", {"DB_PWD": "mysql-password:onlyoffice", "JWT_SECRET": "random"}),
    "remote": ("remote/remote-secret", {"POSTGRESQL_PASSWORD": "postgres-password:guacamole", "GUACAMOLE_ADMIN_USERNAME": "authentik-owner", "GUACAMOLE_ADMIN_PASSWORD": "random"}),
}


def generated(kind):
    if kind.startswith("s3-access:"):
        return "lab-" + kind.split(":", 1)[1] + "-" + secrets.token_hex(8)
    if kind.startswith(("mysql-password:", "postgres-password:")):
        return secrets.token_urlsafe(48)
    if kind.startswith(("mysql-url:", "mysql-dsn:")):
        style, role = kind.split(":", 1)
        password = secrets.token_urlsafe(48)
        if style == "mysql-url":
            return f"mysql://{role}:{password}@mysql-service.database.svc.cluster.local:3306/{role}"
        return f"{role}:{password}@tcp(mysql-service.database.svc.cluster.local:3306)/{role}?charset=utf8mb4&parseTime=true&loc=UTC"
    if kind.startswith("postgres:"):
        role = kind.split(":", 1)[1]
        return f"postgresql://{role}:{secrets.token_urlsafe(48)}@pgsql-service.database.svc.cluster.local:5432/{role}"
    if kind == "redis":
        return "redis://redis-service.database.svc.cluster.local:6379/1"
    return secrets.token_urlsafe(48) if kind == "random" else ""


def valid_field(value, kind):
    if not isinstance(value, str):
        return False
    if kind.startswith("s3-access:"):
        return re.fullmatch("lab-" + re.escape(kind.split(":", 1)[1]) + "-[a-f0-9]{16}", value) is not None
    if kind == "random" or kind.startswith(("mysql-password:", "postgres-password:")):
        return len(value) >= 48
    if kind == "authentik-owner":
        return 0 < len(value) <= 128 and not any(c in value for c in ['\n', '\r', '\0'])
    if kind.startswith(("mysql-url:", "mysql-dsn:")):
        try:
            mysql_identity(value, kind)
            return True
        except RuntimeError:
            return False
    if kind.startswith("postgres:"):
        role = kind.split(":", 1)[1]
        parsed = urllib.parse.urlsplit(value)
        return parsed.scheme == "postgresql" and parsed.hostname == "pgsql-service.database.svc.cluster.local" and parsed.username == role and parsed.path == "/" + role and len(parsed.password or "") >= 48
    if kind == "redis":
        return value == generated("redis")
    return kind == "optional-empty"


def mysql_identity(value, kind):
    style, role = kind.split(":", 1)
    if not re.fullmatch("[a-z][a-z0-9_]*", role):
        raise RuntimeError("Unsafe MySQL identity")
    if style == "mysql-url":
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme != "mysql" or parsed.username != role or parsed.hostname != "mysql-service.database.svc.cluster.local" or parsed.path != "/" + role:
            raise RuntimeError("Unexpected managed MySQL URL")
        password = parsed.password or ""
    else:
        prefix = role + ":"
        suffix = "@tcp(mysql-service.database.svc.cluster.local:3306)/" + role + "?charset=utf8mb4&parseTime=true&loc=UTC"
        if not value.startswith(prefix) or not value.endswith(suffix):
            raise RuntimeError("Unexpected managed Go MySQL DSN")
        password = value[len(prefix):-len(suffix)]
    if not re.fullmatch("[A-Za-z0-9_-]{48,}", password):
        raise RuntimeError("Unexpected managed MySQL password")
    return role, password


def mysql_sql(statement):
    command = ["kubectl", "exec", "-i", "-n", "database", "deployment/mysql", "-c", "mysql", "--", "sh", "-c",
               'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mysql -uroot --batch --skip-column-names']
    result = subprocess.run(command, input=statement, text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError("MySQL provisioning failed; SQL/error bodies suppressed")
    return result.stdout.strip()


def mysql_database(value, kind):
    role, password = mysql_identity(value, kind)
    state = json.loads(mysql_sql(f"""SELECT JSON_OBJECT(
 'userCount',(SELECT COUNT(*) FROM mysql.user WHERE User='{role}'),
 'marker',(SELECT COALESCE(JSON_UNQUOTE(JSON_EXTRACT(User_attributes,'$.metadata.lab_managed')),JSON_UNQUOTE(JSON_EXTRACT(User_attributes,'$.lab_managed'))) FROM mysql.user WHERE User='{role}' AND Host='%'),
 'databaseCount',(SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='{role}'),
 'globalPrivileges',(SELECT COUNT(*) FROM information_schema.USER_PRIVILEGES WHERE GRANTEE=CONCAT(QUOTE('{role}'),'@',QUOTE('%')) AND PRIVILEGE_TYPE <> 'USAGE'));"""))
    if state["userCount"] and (state["userCount"] != 1 or state["marker"] != role or state["globalPrivileges"]):
        raise RuntimeError("Existing MySQL role is not safely managed; refusing modification")
    if state["databaseCount"] and not state["userCount"]:
        raise RuntimeError("Existing database has no managed MySQL owner")
    if not state["userCount"]:
        attribute = json.dumps({"lab_managed": role})
        mysql_sql(f"CREATE USER '{role}'@'%' IDENTIFIED BY '{password}' ATTRIBUTE '{attribute}';")
    if not state["databaseCount"]:
        mysql_sql(f"CREATE DATABASE `{role}`;")
    mysql_sql(f"GRANT ALL PRIVILEGES ON `{role}`.* TO '{role}'@'%';")
    command = ["kubectl", "exec", "-i", "-n", "database", "deployment/mysql", "-c", "mysql", "--", "sh", "-c",
               f'IFS= read -r MYSQL_PWD; export MYSQL_PWD; exec mysql --protocol=TCP -h mysql-service.database.svc.cluster.local -u {role} -D {role} --batch --skip-column-names -e "SELECT CURRENT_USER()"']
    good = subprocess.run(command, input=password + "\n", text=True, capture_output=True, timeout=30)
    bad = subprocess.run(command, input=secrets.token_urlsafe(48) + "\n", text=True, capture_output=True, timeout=30)
    if good.returncode or good.stdout.strip() != role + "@%" or not bad.returncode:
        raise RuntimeError("MySQL credential positive/negative verification failed")
    print(f"{role}: dedicated MySQL database verified; wrong password rejected")


def repair_unused_bootstrap_driver(vault, name, path, data, fields):
    # Correct only our two unused initial bootstrap URLs, not user-managed data.
    if name not in {"heartbeat", "keysboard"} or not fields["DATABASE_URL"].startswith("mysql-"):
        return data
    if not valid_field(data.get("DATABASE_URL"), "postgres:" + name):
        return data
    state = json.loads(sql(f"SELECT json_build_object('marker',(SELECT shobj_description(oid,'pg_authid') FROM pg_roles WHERE rolname='{name}'))"))
    count = sql("SELECT COUNT(*) FROM pg_tables WHERE schemaname !~ '^pg_' AND schemaname <> 'information_schema'", name)
    if state["marker"] != "lab-service-bootstrap-v1:" + name or count != "0":
        raise RuntimeError("Refusing to change a non-empty or unrelated bootstrap database")
    version = json.loads(vault.run("kv", "metadata", "get", "-format=json", "-mount=secret", path))["data"]["current_version"]
    updated = {**data, "DATABASE_URL": generated(fields["DATABASE_URL"])}
    mysql_database(updated["DATABASE_URL"], fields["DATABASE_URL"])
    vault.run("kv", "put", "-cas=" + str(version), "-mount=secret", path, "-", payload=json.dumps(updated))
    print(f"{name}: corrected unused bootstrap driver to the application's verified MySQL backend; original empty PG database retained")
    return updated


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
    paths = [path] if isinstance(path, str) else path
    policy = "".join(f'path "secret/data/{item}" {{ capabilities = ["read"] }}\n' for item in paths)
    vault.run("policy", "write", "lab-" + namespace, "-", payload=policy)
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
            if name == "remote":
                from oidc import Authentik

                bootstrap = vault.get("authentik/bootstrap-worker")
                owner = Authentik(bootstrap["AUTHENTIK_BOOTSTRAP_TOKEN"]).request("core/users/me/")["user"]
                if not owner["is_active"] or not owner["is_superuser"]:
                    raise RuntimeError("Refusing to assign remote administration to a non-administrator")
                data["GUACAMOLE_ADMIN_USERNAME"] = owner["username"]
            vault.create(path, data)
        data = repair_unused_bootstrap_driver(vault, name, path, data, fields)
        if set(data) != set(fields) or any(not valid_field(data[field], kind) for field, kind in fields.items()):
            raise RuntimeError("Existing service credentials need manual review")
        for field, kind in fields.items():
            if kind.startswith("postgres:"):
                postgres_database(data[field])
            elif kind.startswith(("mysql-url:", "mysql-dsn:")):
                mysql_database(data[field], kind)
            elif kind.startswith("mysql-password:"):
                role = kind.split(":", 1)[1]
                value = f"mysql://{role}:{data[field]}@mysql-service.database.svc.cluster.local:3306/{role}"
                mysql_database(value, "mysql-url:" + role)
            elif kind.startswith("postgres-password:"):
                role = kind.split(":", 1)[1]
                value = f"postgresql://{role}:{data[field]}@pgsql-service.database.svc.cluster.local:5432/{role}"
                postgres_database(value)
    reader(vault, name, [path, "monitoring/thanos-secrets"] if name == "monitoring" else path)
    print(f"{name}: managed credentials verified; values suppressed")


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
