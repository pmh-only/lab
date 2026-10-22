#!/usr/bin/env python3
"""Preserve the supplied Photon key and prepare isolated native Dawarich credentials."""

import importlib.util
import json
from pathlib import Path
import secrets
import sys

from oidc import Authentik, provision_client
from provision import ROOT, reader


def main():
    spec = importlib.util.spec_from_file_location("dns01_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    path = "track/track-secret"
    data = vault.get(path)
    expected = {"PHOTON_API_KEY", "DATABASE_PASSWORD", "SECRET_KEY_BASE"}
    if not data or not isinstance(data.get("PHOTON_API_KEY"), str) or not data["PHOTON_API_KEY"] or set(data) - expected:
        raise RuntimeError("Expected the explicitly supplied Photon key; refusing unknown secret fields")
    complete = dict(data)
    complete.setdefault("DATABASE_PASSWORD", secrets.token_urlsafe(48))
    complete.setdefault("SECRET_KEY_BASE", secrets.token_hex(64))
    if len(complete["DATABASE_PASSWORD"]) < 48 or len(complete["SECRET_KEY_BASE"]) < 128:
        raise RuntimeError("Existing native database/session credentials need manual review")
    if complete != data:
        metadata = json.loads(vault.run("kv", "metadata", "get", "-format=json", "-mount=secret", path))["data"]
        vault.run("kv", "put", "-cas=" + str(metadata["current_version"]), "-mount=secret", path, "-", payload=json.dumps(complete))
    root_path = "track/db-admin"
    root = vault.get(root_path)
    if root is None:
        root = {"password": secrets.token_urlsafe(48)}
        vault.create(root_path, root)
    if set(root) != {"password"} or len(root["password"]) < 48:
        raise RuntimeError("Existing database administration credentials need review")
    api = Authentik(vault.get("authentik/bootstrap-worker")["AUTHENTIK_BOOTSTRAP_TOKEN"])
    desired = json.loads(Path(__file__).with_name("oidc.json").read_text())["track"]
    provision_client(vault, api, "track", desired)
    owner = api.request("core/users/me/")["user"]
    if not owner["is_active"] or not owner["is_superuser"] or not owner.get("email"):
        raise RuntimeError("Verified existing administrator principal is required")
    provider = next(p for p in api.list("providers/oauth2/") if p["client_id"] == desired["clientID"])
    claims = api.request(f"providers/oauth2/{provider['pk']}/preview_user/?for_user={owner['pk']}")["preview"]
    if claims.get("iss") != "https://auth.pmh.codes/application/o/track/" or claims.get("aud") != desired["clientID"] or not claims.get("sub") or claims.get("email", "").lower() != owner["email"].lower():
        raise RuntimeError("Native provider preview does not identify the verified administrator")
    login_path = "track/bootstrap-login"
    login = vault.get(login_path)
    if login is None:
        login = {"ADMIN_EMAIL": owner["email"].lower(), "ADMIN_NAME": owner.get("name") or owner["username"],
                 "ADMIN_PASSWORD": secrets.token_urlsafe(48), "OIDC_SUB": claims["sub"]}
        vault.create(login_path, login)
    if set(login) != {"ADMIN_EMAIL", "ADMIN_NAME", "ADMIN_PASSWORD", "OIDC_SUB"} or len(login["ADMIN_PASSWORD"]) < 48 or not secrets.compare_digest(login["OIDC_SUB"], claims["sub"]):
        raise RuntimeError("Existing owner identity differs; refusing an account/password reset")
    reader(vault, "track", desired["readerPaths"])
    print("track: supplied Photon key preserved; fresh database/session/OIDC credentials and native provider-preview owner binding verified; values suppressed")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, StopIteration) as error:
        print(f"Track provisioning failed: {type(error).__name__}; details/credentials suppressed", file=sys.stderr)
        sys.exit(1)
