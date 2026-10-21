#!/usr/bin/env python3
"""Create fresh Authentik credentials/DB with a verified non-root Vault login.

Never imports old credentials, reads bootstrap.json, prints secrets, or rotates
existing credentials. The human login password is not synchronized to Kubernetes.
"""

import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import secrets
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
APP = "authentik/authentik-secrets"
BOOTSTRAP = "authentik/bootstrap-worker"
LOGIN = "authentik/bootstrap-login"
MARKER = "lab-authentik-bootstrap-v1"


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 1000000)
    return f"pbkdf2_sha256$1000000${salt}${base64.b64encode(digest).decode()}"


def credentials(vault):
    application = vault.get(APP)
    if application is None:
        application = {"AUTHENTIK_SECRET_KEY": secrets.token_urlsafe(64), "AUTHENTIK_POSTGRESQL__PASSWORD": secrets.token_urlsafe(48)}
        vault.create(APP, application)
    if set(application) != {"AUTHENTIK_SECRET_KEY", "AUTHENTIK_POSTGRESQL__PASSWORD"} or any(not isinstance(v, str) or len(v) < 48 for v in application.values()):
        raise RuntimeError("Existing Authentik application credentials need manual review")
    bootstrap, login = vault.get(BOOTSTRAP), vault.get(LOGIN)
    if bootstrap is not None and login is None:
        raise RuntimeError("Existing bootstrap identity has no managed login; refusing to replace it")
    if login is None:
        login = {"username": "akadmin", "password": secrets.token_urlsafe(48)}
        vault.create(LOGIN, login)
    if set(login) != {"username", "password"} or login["username"] != "akadmin" or len(login["password"]) < 48:
        raise RuntimeError("Existing administrator login needs manual review")
    if bootstrap is None:
        bootstrap = {
            "AUTHENTIK_BOOTSTRAP_PASSWORD_HASH": password_hash(login["password"]),
            "AUTHENTIK_BOOTSTRAP_TOKEN": secrets.token_urlsafe(48),
            "AUTHENTIK_BOOTSTRAP_EMAIL": "pmh_only@pmh.codes",
        }
        vault.create(BOOTSTRAP, bootstrap)
    if set(bootstrap) != {"AUTHENTIK_BOOTSTRAP_PASSWORD_HASH", "AUTHENTIK_BOOTSTRAP_TOKEN", "AUTHENTIK_BOOTSTRAP_EMAIL"} or len(bootstrap["AUTHENTIK_BOOTSTRAP_TOKEN"]) < 48:
        raise RuntimeError("Existing bootstrap settings need manual review")
    parts = bootstrap["AUTHENTIK_BOOTSTRAP_PASSWORD_HASH"].split("$")
    if len(parts) != 4 or not secrets.compare_digest(password_hash(login["password"], parts[2]), bootstrap["AUTHENTIK_BOOTSTRAP_PASSWORD_HASH"]):
        raise RuntimeError("Stored administrator password does not match its bootstrap hash")
    return application


def configure_reader(vault):
    vault.run("policy", "write", "lab-authentik", "-", payload="".join(
        f'path "secret/data/{path}" {{ capabilities = ["read"] }}\n' for path in [APP, BOOTSTRAP]
    ))
    vault.run("write", "auth/kubernetes/role/authentik", "-", payload=json.dumps({
        "bound_service_account_names": ["vault-auth"], "bound_service_account_namespaces": ["authentik"],
        "audience": "vault", "token_policies": ["lab-authentik"], "token_ttl": 3600, "token_max_ttl": 14400,
    }))


def sql(statement, database="postgres"):
    result = subprocess.run([
        "kubectl", "exec", "-i", "-n", "database", "deployment/pgsql", "-c", "pgsql", "--",
        "psql", "-U", "admin", "-d", database, "-v", "ON_ERROR_STOP=1", "-At",
    ], input=statement, text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError("PostgreSQL provisioning failed; SQL/error bodies suppressed")
    return result.stdout.strip()


def database(application):
    metadata = json.loads(sql("""
SELECT json_build_object(
 'role', (SELECT row_to_json(r) FROM (SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolcanlogin,shobj_description(oid,'pg_authid') AS marker FROM pg_roles WHERE rolname='authentik') r),
 'database', (SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='authentik'),
 'memberships', (SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON m.member=r.oid WHERE r.rolname='authentik'));
"""))
    role = metadata["role"]
    if role and (role["marker"] != MARKER or any(role[k] for k in ["rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication"]) or not role["rolcanlogin"] or metadata["memberships"]):
        raise RuntimeError("Existing Authentik role is not safely managed; refusing modification")
    if metadata["database"] and (metadata["database"] != "authentik" or not role):
        raise RuntimeError("Existing Authentik database has an unexpected owner")
    if role is None:
        password = application["AUTHENTIK_POSTGRESQL__PASSWORD"].replace("'", "''")
        sql(f"CREATE ROLE authentik LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '{password}'; COMMENT ON ROLE authentik IS '{MARKER}';")
    if metadata["database"] is None:
        sql("CREATE DATABASE authentik OWNER authentik;")
    sql("REVOKE ALL ON DATABASE authentik FROM PUBLIC;")
    sql("REVOKE CREATE ON SCHEMA public FROM PUBLIC;", "authentik")
    # Send the password through stdin, never command arguments or logs.
    command = ["kubectl", "exec", "-i", "-n", "database", "deployment/pgsql", "-c", "pgsql", "--", "sh", "-c",
               'IFS= read -r PGPASSWORD; export PGPASSWORD; exec psql -h pgsql-service.database.svc.cluster.local -U authentik -d authentik -At -c "SELECT current_user"']
    good = subprocess.run(command, input=application["AUTHENTIK_POSTGRESQL__PASSWORD"] + "\n", text=True, capture_output=True, timeout=30)
    bad = subprocess.run(command, input=secrets.token_urlsafe(48) + "\n", text=True, capture_output=True, timeout=30)
    if good.returncode or good.stdout.strip() != "authentik" or not bad.returncode:
        raise RuntimeError("Authentik DB credential positive/negative verification failed")
    print("Dedicated non-superuser PostgreSQL role/database verified; wrong password rejected")


def main():
    spec = importlib.util.spec_from_file_location("dns01_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    application = credentials(vault)
    configure_reader(vault)
    database(application)
    print("Fresh Authentik credentials are in Vault; workload cannot read the human login password")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f"Authentik provisioning failed: {error}", file=sys.stderr)
        sys.exit(1)
