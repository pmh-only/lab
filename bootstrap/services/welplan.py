#!/usr/bin/env python3
"""Preserve supplied Welstory/Webshare/Slack credentials and prepare native DB/OIDC."""

import importlib.util
import json
from pathlib import Path
import re
import secrets
import sys

from oidc import Authentik, provision_client
from provision import ROOT, postgres_database, reader


EXTERNAL = {"WELSTORY_USERNAME", "WELSTORY_PASSWORD", "WEBSHARE_API_TOKEN", "SLACK_CLIENT_ID", "SLACK_CLIENT_SECRET"}


def complete_credentials(data):
    internal = {"PGPASSWORD", "INDEXNOW_KEY", "REVIEW_JWT_SECRET"}
    if not data or set(data) - EXTERNAL - internal or any(not isinstance(data.get(k), str) or not data[k] for k in EXTERNAL):
        raise RuntimeError("Required real external credentials are missing or unknown fields require review")
    if not re.fullmatch(r"\d+\.\d+", data["SLACK_CLIENT_ID"]):
        raise RuntimeError("Expected the actual Slack OAuth Client ID, not an App ID or token")
    desired = dict(data)
    desired.setdefault("PGPASSWORD", secrets.token_urlsafe(48))
    desired.setdefault("INDEXNOW_KEY", secrets.token_hex(32))
    desired.setdefault("REVIEW_JWT_SECRET", secrets.token_urlsafe(48))
    if not re.fullmatch(r"[A-Za-z0-9_-]{48,}", desired["PGPASSWORD"]) or len(desired["REVIEW_JWT_SECRET"]) < 48 or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", desired["INDEXNOW_KEY"]):
        raise RuntimeError("Existing generated credentials need coordinated review; refusing rotation")
    return desired


def main():
    spec = importlib.util.spec_from_file_location("dns01_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    path = "welplan/welplan-secret"
    data = vault.get(path)
    desired = complete_credentials(data)
    if desired != data:
        version = json.loads(vault.run("kv", "metadata", "get", "-format=json", "-mount=secret", path))["data"]["current_version"]
        vault.run("kv", "put", "-cas=" + str(version), "-mount=secret", path, "-", payload=json.dumps(desired))
    postgres_database("postgresql://welplan:" + desired["PGPASSWORD"] + "@pgsql-service.database.svc.cluster.local:5432/welplan")
    declaration = json.loads(Path(__file__).with_name("oidc.json").read_text())["welplan"]
    api = Authentik(vault.get("authentik/bootstrap-worker")["AUTHENTIK_BOOTSTRAP_TOKEN"])
    provision_client(vault, api, "welplan", declaration)
    reader(vault, "welplan", declaration["readerPaths"])
    print("welplan: supplied external credentials preserved; fresh scoped PG/IndexNow/review secret and original admin OIDC binding prepared; values suppressed")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        print(f"Welplan provisioning failed: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
