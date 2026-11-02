"""Obtain a sealed Raft snapshot with a short-lived, snapshot-read-only token."""

import hashlib
import io
import json
import os
from pathlib import Path
import ssl
import tarfile
import urllib.request
import uuid
from datetime import datetime, timezone


def validate_snapshot(data):
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        members = {m.name: m for m in archive.getmembers()}
        required = {"meta.json", "state.bin", "SHA256SUMS", "SHA256SUMS.sealed"}
        if not required.issubset(members) or not all(members[n].isfile() for n in required):
            raise RuntimeError("Invalid native Raft snapshot structure")
        verified = set()
        for line in archive.extractfile("SHA256SUMS").read().decode().splitlines():
            checksum, name = line.split(None, 1)
            name = name.strip().lstrip("*")
            if name not in members or not members[name].isfile():
                raise RuntimeError("Invalid native Raft snapshot checksum entry")
            if hashlib.sha256(archive.extractfile(name).read()).hexdigest() != checksum:
                raise RuntimeError("Native Raft snapshot checksum mismatch")
            verified.add(name)
        if not {"meta.json", "state.bin"}.issubset(verified) or not members["SHA256SUMS.sealed"].size:
            raise RuntimeError("Native Raft snapshot lacks verified sealed state")


def main():
    os.umask(0o077)
    context = ssl.create_default_context(cafile="/vault-ca/ca.crt")
    token = None

    def request(path, payload=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Vault-Token"] = token
        req = urllib.request.Request("https://vault.vault.svc.cluster.local:8200/v1/" + path,
                                     data=None if payload is None else json.dumps(payload).encode(), headers=headers)
        with urllib.request.urlopen(req, context=context, timeout=180) as response:
            return response.read()

    try:
        login = json.loads(request("auth/kubernetes/login", {"role": "vault-snapshot", "jwt": Path("/identity/token").read_text()}))
        token = login["auth"]["client_token"]
        data = request("sys/storage/raft/snapshot")
        validate_snapshot(data)
        root = Path("/backup")
        (root / "vault.snap").write_bytes(data)
        (root / "SHA256SUMS").write_text(hashlib.sha256(data).hexdigest() + "  ./vault.snap\n")
        (root / "started-at").write_text(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "\n" + str(uuid.uuid4()) + "\n")
        print("Native sealed Raft snapshot captured; archive structure and internal checksums verified")
    finally:
        if token:
            try:
                request("auth/token/revoke-self", {})
            except OSError:
                pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Vault snapshot failed; credential-bearing details suppressed")
