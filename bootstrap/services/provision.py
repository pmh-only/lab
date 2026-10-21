#!/usr/bin/env python3
"""Provision fresh local service credentials; never fabricate external API keys."""

import argparse
import base64
import importlib.util
import json
from pathlib import Path
import secrets
import struct
import sys
import textwrap

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey


ROOT = Path(__file__).resolve().parents[2]
PROFILES = {
    "speed": ("speed/speed-secret", {"PASSWORD": "random", "IPINFO_APIKEY": "optional-empty"}),
    "here": ("here/here-secret", {"SSH_PASSWORD": "random"}),
}


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
            data = {field: secrets.token_urlsafe(48) if kind == "random" else "" for field, kind in fields.items()}
            vault.create(path, data)
        if set(data) != set(fields) or any(not isinstance(data[field], str) or (kind == "random" and len(data[field]) < 48) for field, kind in fields.items()):
            raise RuntimeError("Existing service credentials need manual review")
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
