#!/usr/bin/env python3
"""Verify Velero restore with only disposable namespaces and a non-secret ConfigMap."""

import hashlib
import json
import secrets
import subprocess
import time


def kubectl(*args, payload=None):
    result = subprocess.run(["kubectl", *args], input=None if payload is None else json.dumps(payload), text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError("Velero restore verification Kubernetes operation failed; output suppressed")
    return result.stdout


def wait(kind, name):
    for _ in range(120):
        item = json.loads(kubectl("-n", "velero", "get", kind, name, "-o", "json"))
        phase = item.get("status", {}).get("phase")
        if phase == "Completed":
            return
        if phase in {"Failed", "FailedValidation", "PartiallyFailed"}:
            raise RuntimeError("Disposable Velero " + kind + " ended in " + phase)
        time.sleep(5)
    raise RuntimeError("Disposable Velero verification timed out")


def main():
    identifier = secrets.token_hex(6)
    source, target = "backup-velero-source-" + identifier, "backup-velero-restore-" + identifier
    marker, body = secrets.token_hex(16), secrets.token_hex(32)
    created = []
    try:
        for namespace in [source, target]:
            kubectl("create", "-f", "-", payload={"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": namespace, "labels": {"lab.pmh.codes/restore-owner": marker}}})
            created.append(namespace)
        kubectl("create", "-f", "-", payload={"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "recovery-probe", "namespace": source}, "data": {"payload": body}})
        kubectl("create", "-f", "-", payload={"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "Role", "metadata": {"name": "restore-probe-only", "namespace": target}, "rules": [{"apiGroups": [""], "resources": ["configmaps"], "verbs": ["get", "list", "watch", "create", "patch", "update"]}]})
        kubectl("create", "-f", "-", payload={"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding", "metadata": {"name": "restore-probe-only", "namespace": target}, "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": "restore-probe-only"}, "subjects": [{"kind": "ServiceAccount", "name": "velero", "namespace": "velero"}]})
        backup = "restore-probe-" + identifier
        kubectl("create", "-f", "-", payload={"apiVersion": "velero.io/v1", "kind": "Backup", "metadata": {"name": backup, "namespace": "velero"}, "spec": {"includedNamespaces": [source], "includedResources": ["configmaps"], "includeClusterResources": False, "snapshotVolumes": False, "defaultVolumesToFsBackup": False, "storageLocation": "default", "ttl": "720h0m0s"}})
        wait("backup", backup)
        kubectl("create", "-f", "-", payload={"apiVersion": "velero.io/v1", "kind": "Restore", "metadata": {"name": backup, "namespace": "velero"}, "spec": {"backupName": backup, "includedResources": ["configmaps"], "includeClusterResources": False, "namespaceMapping": {source: target}, "restorePVs": False}})
        wait("restore", backup)
        actual = json.loads(kubectl("-n", target, "get", "configmap", "recovery-probe", "-o", "json"))["data"]["payload"]
        if hashlib.sha256(actual.encode()).digest() != hashlib.sha256(body.encode()).digest():
            raise RuntimeError("Velero restored ConfigMap bytes differ")
        print("Velero S3 backup and namespace-mapped ConfigMap restore completed; exact bytes verified; no production namespace or PVC restored")
    finally:
        for namespace in reversed(created):
            actual = json.loads(kubectl("get", "namespace", namespace, "-o", "json"))
            if actual["metadata"]["labels"].get("lab.pmh.codes/restore-owner") != marker:
                raise RuntimeError("Namespace owner changed; refusing cleanup")
            kubectl("delete", "namespace", namespace, "--wait=false")


if __name__ == "__main__":
    main()
