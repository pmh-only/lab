#!/usr/bin/env python3
"""Initialize only the managed remote repository and verify an encrypted restore.

The test Pod has no hostPath, production PVC, API token, or administrator secret.
The probe snapshot is retained; only this invocation's temporary Pod is removed.
"""

import importlib.util
import json
import secrets
import subprocess

from minio import Minio
import yaml

from provision import ROOT


def command(*args, payload=None, timeout=120):
    result = subprocess.run(["kubectl", *args], input=payload, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("Kopia repository check failed; credential-bearing output suppressed")
    return result.stdout


def main():
    spec = importlib.util.spec_from_file_location("dns01_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    credentials = vault.get("kopia/s3")
    client = Minio("127.0.0.1:19000", access_key=credentials["S3_ACCESS_TOKEN"], secret_key=credentials["S3_SECRET_TOKEN"], secure=False, region="us-east-1")
    objects = [o.object_name for o in client.list_objects("kopia", recursive=True)]
    create = not objects
    if not create and "kopia.repository" not in objects:
        raise RuntimeError("Remote bucket contains unmanaged data; refusing repository creation")
    docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "kopia/backup")], text=True)))
    cronjob = next(d for d in docs if d["kind"] == "CronJob")
    pod = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    pod["volumes"] = [v for v in pod["volumes"] if v["name"] in {"work", "tmp"}]
    pod.pop("nodeSelector", None)
    pod["securityContext"].update({"runAsNonRoot": True, "runAsUser": 1000, "runAsGroup": 1000, "fsGroup": 1000})
    container = pod["containers"][0]
    container["securityContext"]["capabilities"].pop("add", None)
    container["volumeMounts"] = [v for v in container["volumeMounts"] if v["name"] in {"work", "tmp"}]
    container["command"] = ["sleep", "3600"]
    name = "kopia-restore-probe-" + secrets.token_hex(6)
    item = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, "namespace": "kopia"}, "spec": pod}
    created = json.loads(command("create", "-f", "-", "-o", "json", payload=json.dumps(item)))
    uid = created["metadata"]["uid"]
    try:
        command("-n", "kopia", "wait", "--for=condition=Ready", "pod/" + name, "--timeout=180s", timeout=190)
        mode = "create" if create else "connect"
        script = """set -eu
umask 077
kopia repository MODE s3 --bucket=kopia --endpoint=pmhraspberry.tailscale.svc.cluster.local:9000 --disable-tls --region=us-east-1 --no-check-for-updates --override-hostname=restore-probe --override-username=lab > /work/connect.log 2>&1
kopia maintenance set --enable-quick=false --enable-full=false > /work/maintenance.log 2>&1
printf 'lab encrypted repository recovery probe\\n' > /work/recovery-probe
kopia snapshot create --fail-fast --pin=restore-probe --json /work/recovery-probe > /work/probe.json 2>/work/snapshot.log
cat /work/probe.json
""".replace("MODE", mode)
        raw = command("-n", "kopia", "exec", "-i", name, "--", "sh", "-s", payload=script)
        result = json.loads(raw)
        if isinstance(result, list):
            result = result[0]
        snapshot = result["id"]
        if not isinstance(snapshot, str) or not snapshot.isalnum():
            raise RuntimeError("Unexpected native snapshot identifier")
        script = """set -eu
kopia snapshot verify --verify-files-percent=100 SNAPSHOT > /work/verify.log 2>&1
kopia snapshot restore SNAPSHOT /work/restored-probe > /work/restore.log 2>&1
cmp /work/recovery-probe /work/restored-probe
echo 'Kopia encrypted repository and 100-percent probe verification/restore succeeded'
""".replace("SNAPSHOT", snapshot)
        print(command("-n", "kopia", "exec", "-i", name, "--", "sh", "-s", payload=script).strip())
    finally:
        actual = json.loads(command("-n", "kopia", "get", "pod", name, "-o", "json"))
        if actual["metadata"]["uid"] != uid:
            raise RuntimeError("Temporary Kopia Pod identity changed; refusing cleanup")
        command("-n", "kopia", "delete", "pod", name, "--wait=true", "--timeout=60s")


if __name__ == "__main__":
    main()
