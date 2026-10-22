#!/usr/bin/env python3
"""Prepare real Spotify credentials and isolated MongoDB authentication."""

import argparse
import base64
import importlib.util
import json
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

from mongo import ensure_users, spotify_identity, verify_isolation
from provision import ROOT, reader


def verify_spotify(data):
    if any(not isinstance(data.get(k), str) or not data[k] for k in ["SPOTIFY_PUBLIC", "SPOTIFY_SECRET"]):
        raise RuntimeError("The real Spotify Client ID/Secret must be supplied")
    header = base64.b64encode((data["SPOTIFY_PUBLIC"] + ":" + data["SPOTIFY_SECRET"]).encode()).decode()
    request = urllib.request.Request("https://accounts.spotify.com/api/token",
        data=b"grant_type=client_credentials",
        headers={"Authorization": "Basic " + header, "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Spotify credentials rejected: HTTP {error.code}; response suppressed") from None
    if not result.get("access_token") or result.get("token_type", "").lower() != "bearer":
        raise RuntimeError("Unexpected Spotify token response")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-database", action="store_true")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("dns01_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    path = "spotify/spotify-secret"
    data = vault.get(path)
    if data is None or set(data) - {"SPOTIFY_PUBLIC", "SPOTIFY_SECRET", "MONGO_ENDPOINT"}:
        raise RuntimeError("Unexpected Spotify secret data; refusing unknown fields")
    verify_spotify(data)
    if args.verify_database:
        verify_isolation(data["MONGO_ENDPOINT"])
        return
    root_path = "database/mongo-root-password"
    root = vault.get(root_path)
    if root is None:
        root = {"username": "lab-admin", "password": secrets.token_urlsafe(48)}
        vault.create(root_path, root)
    if "MONGO_ENDPOINT" not in data:
        data = {**data, "MONGO_ENDPOINT": "mongodb://spotify:" + secrets.token_urlsafe(48) + "@mongo-service.database.svc.cluster.local:27017/your_spotify?authSource=your_spotify"}
        metadata = json.loads(vault.run("kv", "metadata", "get", "-format=json", "-mount=secret", path))["data"]
        vault.run("kv", "put", "-cas=" + str(metadata["current_version"]), "-mount=secret", path, "-", payload=json.dumps(data))
    spotify_identity(data["MONGO_ENDPOINT"])
    ensure_users(root, data["MONGO_ENDPOINT"])
    reader(vault, "spotify", path)
    print("spotify: supplied Spotify pair verified and preserved; dedicated MongoDB URI in Vault; no listening history/user tokens imported or fabricated")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        print(f"Spotify provisioning failed: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
