#!/usr/bin/env python3
"""Back up fresh primary DNS data without plaintext files or a Vault root token.

Encrypts the DNS configuration with a non-exportable Vault Transit key, then
saves an encrypted Raft snapshot outside the cluster. Recovery requires both
artifacts and the original unseal shares; a full restore drill is still required.
Never reads or exports unseal shares. Does not restore or mutate DNS records.
"""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import select
import ssl
import stat
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
MOUNT = "backup-transit"
KEY = "lab-dns-backup"


def operator_token(identity):
    if "root" in set(identity.get("policies", [])) | set(identity.get("identity_policies", [])) or not identity.get("path", "").startswith("auth/userpass/"):
        raise RuntimeError("A non-root userpass operator login is required")
    if not identity.get("id"):
        raise RuntimeError("Operator token lookup did not return a usable identity")
    return identity["id"]


def validate_dns_archive(data, zones):
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        files = {}
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
                raise RuntimeError("DNS archive contains an unsafe member")
            if member.isfile():
                files[str(path)] = member.size
    required = {"dns.config", "auth.config", "webservice.config"} | {f"zones/{zone}.zone" for zone in zones}
    if not required.issubset(files) or any(files[name] <= 0 for name in required):
        raise RuntimeError("DNS archive is missing required configuration/zone files")
    if any(name.startswith(("stats/", "logs/", "cache.bin")) for name in files):
        raise RuntimeError("DNS archive unexpectedly includes volatile statistics/logs/cache")
    return len(files)


def validate_snapshot(data):
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        members = {member.name: member for member in archive.getmembers()}
        if not {"meta.json", "state.bin", "SHA256SUMS", "SHA256SUMS.sealed"}.issubset(members):
            raise RuntimeError("Unexpected Raft snapshot structure")
        sums = archive.extractfile(members["SHA256SUMS"]).read().decode()
        verified = set()
        for line in sums.splitlines():
            checksum, name = line.split(None, 1)
            name = name.strip().lstrip("*")
            if name not in members or not members[name].isfile():
                raise RuntimeError("Raft snapshot checksum references a missing file")
            body = archive.extractfile(members[name]).read()
            if hashlib.sha256(body).hexdigest() != checksum:
                raise RuntimeError("Raft snapshot internal checksum mismatch")
            verified.add(name)
        if not {"meta.json", "state.bin"}.issubset(verified) or members["SHA256SUMS.sealed"].size <= 0:
            raise RuntimeError("Raft snapshot does not include verified sealed state")


def private_directory(path):
    if path.resolve().is_relative_to(ROOT.resolve()):
        raise RuntimeError("Backup files must be stored outside the Git checkout")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        raise RuntimeError("Backup directory must be owned by this user with mode 0700")


def write_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


class Vault:
    def __init__(self, token, certificate):
        self.token = token
        self.context = ssl.create_default_context(cadata=certificate)

    def request(self, path, data=None, missing_ok=False, binary=False):
        request = urllib.request.Request(
            "https://127.0.0.1:18200/v1/" + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers={"X-Vault-Token": self.token, "Content-Type": "application/json"},
            method="POST" if data is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, context=self.context, timeout=120) as response:
                body = response.read(128 * 1024 * 1024 + 1)
                if len(body) > 128 * 1024 * 1024:
                    raise RuntimeError("Backup exceeds this helper's size limit; use a streaming snapshot workflow")
                return body if binary else (json.loads(body) if body else {})
        except urllib.error.HTTPError as error:
            if missing_ok and error.code == 404:
                return None
            raise RuntimeError(f"Vault {path}: HTTP {error.code}") from None

    def key(self):
        mounts = self.request("sys/mounts")["data"]
        if MOUNT + "/" not in mounts:
            self.request("sys/mounts/" + MOUNT, {"type": "transit"})
        elif mounts[MOUNT + "/"]["type"] != "transit":
            raise RuntimeError("Backup mount already has an incompatible type")
        path = f"{MOUNT}/keys/{KEY}"
        key = self.request(path, missing_ok=True)
        if key is None:
            self.request(path, {"type": "aes256-gcm96", "exportable": False, "allow_plaintext_backup": False})
            key = self.request(path)
        data = key["data"]
        if data["type"] != "aes256-gcm96" or data.get("exportable") or data.get("allow_plaintext_backup") or data.get("deletion_allowed"):
            raise RuntimeError("Existing backup key does not have the required safety settings")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path.home() / ".local/share/lab-dns-backups")
    parser.add_argument("--deployment", choices=["nameserver", "nameserver-secondary"], default="nameserver")
    args = parser.parse_args()
    private_directory(args.output_root)
    # Inspect the token returned by the already-established userpass CLI login;
    # never fall back to bootstrap.json or a root token.
    result = subprocess.run(["kubectl", "exec", "-n", "vault", "vault-0", "--", "vault", "token", "lookup", "-format=json"], capture_output=True, check=True, timeout=30)
    identity = json.loads(result.stdout)["data"]
    token = operator_token(identity)
    ca = json.loads(subprocess.check_output(["kubectl", "get", "secret", "vault-server-tls", "-n", "vault", "-o", "json"]))["data"]["ca.crt"]
    vault = Vault(token, base64.b64decode(ca).decode())
    forward = None
    try:
        forward = subprocess.Popen(["kubectl", "port-forward", "-n", "vault", "svc/vault", "18200:8200", "--address=127.0.0.1"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if not select.select([forward.stdout], [], [], 30)[0] or "Forwarding from" not in forward.stdout.readline():
            raise RuntimeError("Vault TLS forwarding failed")
        vault.key()
        result = subprocess.run([
            "kubectl", "exec", "-n", "nameserver", "deployment/" + args.deployment, "--", "tar",
            "--exclude=./logs", "--exclude=./stats", "--exclude=./cache.bin*", "-C", "/etc/dns", "-czf", "-", ".",
        ], capture_output=True, check=True, timeout=60)
        archive = result.stdout
        zones = json.loads((ROOT / "nameserver/configuration/dns01.json").read_text())["zones"]
        file_count = validate_dns_archive(archive, zones)
        archive_digest = hashlib.sha256(archive).hexdigest()
        encrypted = vault.request(f"{MOUNT}/encrypt/{KEY}", {"plaintext": base64.b64encode(archive).decode()})["data"]["ciphertext"]
        recovered = vault.request(f"{MOUNT}/decrypt/{KEY}", {"ciphertext": encrypted})["data"]["plaintext"]
        if hashlib.sha256(base64.b64decode(recovered)).hexdigest() != archive_digest:
            raise RuntimeError("Encrypted DNS backup round-trip verification failed")
        output = args.output_root / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4))
        output.mkdir(mode=0o700)
        encrypted_data = (json.dumps({"format": "lab-dns-transit-v1", "keyPath": f"{MOUNT}/keys/{KEY}", "ciphertext": encrypted, "archiveSha256": archive_digest}, indent=2) + "\n").encode()
        write_private(output / "dns-config.encrypted.json", encrypted_data)
        snapshot = vault.request("sys/storage/raft/snapshot", binary=True)
        write_private(output / "vault-raft.snap", snapshot)
        validate_snapshot(snapshot)
        manifest = {
            "format": "lab-dns-backup-v1", "deployment": args.deployment, "zones": zones, "configurationFiles": file_count,
            "archiveSha256": archive_digest, "encryptedArchiveSha256": hashlib.sha256(encrypted_data).hexdigest(),
            "snapshotSha256": hashlib.sha256(snapshot).hexdigest(),
            "dnsRoundTripVerified": True, "snapshotInternalChecksumsVerified": True,
            "fullRestoreTested": False, "requiresOriginalUnsealShares": True, "unsealSharesExported": False,
        }
        write_private(output / "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())
        print(f"Encrypted DNS configuration and encrypted Vault Raft snapshot saved privately to {output}")
        print("Encryption round-trip and snapshot checksums verified; full disaster restore NOT tested; original unseal shares required")
    finally:
        if forward:
            forward.terminate()
            try:
                forward.wait(timeout=10)
            except subprocess.TimeoutExpired:
                forward.kill()
                forward.wait(timeout=10)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, tarfile.TarError, subprocess.SubprocessError) as error:
        print(f"DNS backup failed: {error}", file=sys.stderr)
        sys.exit(1)
