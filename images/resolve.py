"""Resolve immutable build inputs; never require registry access during startup."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

name = sys.argv[1]
root = Path(__file__).resolve().parents[1]
target = json.loads((root / "images/targets.json").read_text())[name]
resolved = {}
for key, image in target.items():
    digest = subprocess.check_output([
        "docker", "buildx", "imagetools", "inspect", image,
        "--format", "{{.Manifest.Digest}}",
    ], text=True).strip()
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise RuntimeError("Registry returned an invalid image digest")
    resolved[key] = image.rsplit(":", 1)[0] + "@" + digest
sources = [root / "images" / name / "Dockerfile"]
sources.extend(sorted(p for p in (root / "images" / name).glob("*") if p.name != "Dockerfile"))
extras = {"trace": ["trace/prepare-clickhouse-client.mjs"], "spotify": ["spotify/prepare-api.mjs"], "seafile": ["seafile/prepare_mysql_plugins.py"]}
sources.extend(root / p for p in extras.get(name, []))
fingerprint = hashlib.sha256(json.dumps(resolved, sort_keys=True).encode())
for path in sources:
    fingerprint.update(str(path.relative_to(root)).encode())
    fingerprint.update(path.read_bytes())
print("base=" + resolved["base"])
print("geoip=" + resolved.get("geoip", resolved["base"]))
print("tag=inputs-" + fingerprint.hexdigest())
