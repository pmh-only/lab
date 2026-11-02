"""Resolve immutable build inputs; never require registry access during startup."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.request

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
    repository = image.split("@", 1)[0]
    if ":" in repository.rsplit("/", 1)[-1]:
        repository = repository.rsplit(":", 1)[0]
    resolved[key] = repository + "@" + digest
sources = [root / "images" / name / "Dockerfile"]
sources.extend(sorted(p for p in (root / "images" / name).glob("*") if p.name != "Dockerfile"))
extras = {"trace": ["trace/prepare-clickhouse-client.mjs"], "spotify": ["spotify/prepare-api.mjs"], "seafile": ["seafile/prepare_mysql_plugins.py"]}
sources.extend(root / p for p in extras.get(name, []))
fingerprint = hashlib.sha256(json.dumps(resolved, sort_keys=True).encode())
requirements = []
packages_file = root / "images" / name / "packages.json"
if packages_file.exists():
    for package in json.loads(packages_file.read_text()):
        with urllib.request.urlopen(f"https://pypi.org/pypi/{package}/json", timeout=30) as response:
            release = json.load(response)
        wheels = [f for f in release["urls"] if f["filename"].endswith("-py3-none-any.whl") and not f.get("yanked")]
        if len(wheels) != 1:
            raise RuntimeError("Expected one non-yanked pure Python wheel")
        requirements.append(f'{package}=={release["info"]["version"]} --hash=sha256:{wheels[0]["digests"]["sha256"]}')
fingerprint.update(json.dumps(requirements).encode())
for path in sources:
    fingerprint.update(str(path.relative_to(root)).encode())
    fingerprint.update(path.read_bytes())
print("base=" + resolved["base"])
print("geoip=" + resolved.get("geoip", resolved["base"]))
print("python_requirements=" + json.dumps(requirements))
print("tag=inputs-" + fingerprint.hexdigest())
