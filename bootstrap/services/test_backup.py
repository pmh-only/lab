import json
import hashlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import tarfile
import unittest
from unittest.mock import Mock

import yaml

from backup_s3 import PROFILES, backup_policy, reconcile, vault_snapshot_roles
from backup_restore import RESTORE, restore_pod
from provision import ROOT
from s3 import Admin, bucket_policy


class BackupTests(unittest.TestCase):
    def test_remote_origin_is_explicit_and_default_service_origin_unchanged(self):
        self.assertEqual(Admin("a", "b").endpoint, "https://s3.pmh.codes")
        remote = Admin("a", "b", "http://127.0.0.1:19000")
        self.assertEqual(remote.endpoint, "http://127.0.0.1:19000")
        for url in ["ftp://localhost", "https://s3.example/path", "https://user@s3.example", "https://s3.example/?token=x"]:
            with self.assertRaises(ValueError):
                Admin("a", "b", url)

    def test_scoped_policies_do_not_allow_database_backup_deletion(self):
        for name, profile in PROFILES.items():
            policy = bucket_policy(profile["bucket"], profile["delete"])
            text = json.dumps(policy)
            self.assertNotIn('"s3:*"', text)
            self.assertEqual("s3:DeleteObject" in text, profile["delete"])
            resources = [r for s in policy["Statement"] for r in s["Resource"]]
            self.assertTrue(all(r.startswith("arn:aws:s3:::" + profile["bucket"]) for r in resources))

    def test_unmanaged_identity_is_not_replaced(self):
        vault, admin = Mock(), Mock()
        vault.get.return_value = {"S3_ACCESS_TOKEN": "unmanaged", "S3_SECRET_TOKEN": "x" * 64}
        with self.assertRaisesRegex(RuntimeError, "Unmanaged"):
            reconcile(vault, admin, "database", "http://127.0.0.1:19000")
        admin.request.assert_not_called()
        vault.create.assert_not_called()

    def test_database_backup_only_allows_native_temporary_lock_deletion(self):
        policy = backup_policy(PROFILES["database"])
        deletes = [r for statement in policy["Statement"] if "s3:DeleteObject" in statement["Action"] for r in statement["Resource"]]
        self.assertEqual(deletes, ["arn:aws:s3:::dbdump/clickhouse/*/.lock"])

    def test_database_jobs_only_enable_verified_schedules_and_never_mount_live_volumes(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "database")], text=True)))
        jobs = [d for d in docs if d["kind"] == "CronJob"]
        self.assertEqual({j["metadata"]["name"] for j in jobs}, {"backup-" + n for n in ["pgsql", "mysql", "mongo", "clickhouse", "immich"]})
        for job in jobs:
            self.assertEqual(job["spec"]["suspend"], job["metadata"]["name"] == "backup-clickhouse")
            self.assertEqual(job["metadata"]["annotations"]["reloader.stakater.com/auto"], "false")
            self.assertEqual(job["spec"]["concurrencyPolicy"], "Forbid")
            pod = job["spec"]["jobTemplate"]["spec"]["template"]["spec"]
            self.assertFalse(pod["automountServiceAccountToken"])
            self.assertTrue(pod["securityContext"]["runAsNonRoot"])
            self.assertTrue(all("persistentVolumeClaim" not in v and "hostPath" not in v for v in pod["volumes"]))
            for c in pod.get("initContainers", []) + pod["containers"]:
                self.assertIn("@sha256:", c["image"])
                self.assertFalse(c["securityContext"]["allowPrivilegeEscalation"])
                self.assertEqual(c["securityContext"]["capabilities"]["drop"], ["ALL"])
            if job["metadata"]["name"] == "backup-clickhouse":
                self.assertFalse(pod.get("initContainers"))
            elif job["metadata"]["name"] == "backup-immich":
                immich = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "immich")], text=True)))
                deployment = next(d for d in immich if d["kind"] == "Deployment" and d["metadata"]["name"] == "pgsql")
                self.assertEqual(pod["initContainers"][0]["image"], deployment["spec"]["template"]["spec"]["containers"][0]["image"])
            else:
                native = pod["initContainers"][0]["image"]
                deployment = next(d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == job["metadata"]["name"].removeprefix("backup-"))
                self.assertEqual(native, deployment["spec"]["template"]["spec"]["containers"][0]["image"])
        for d in docs:
            if d["kind"] == "Deployment":
                self.assertNotIn("backpack", str(d["spec"]["template"]["spec"].get("initContainers", [])))
        self.assertTrue(any(d["kind"] == "VaultStaticSecret" and d["metadata"]["name"] == "backpack-secrets" for d in docs))

    def test_export_failure_stops_before_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            script = (ROOT / "database/backup/export.sh").read_text().replace("/backup", str(tmp))
            fake = tmp / "mysqldump"
            fake.write_text("#!/bin/sh\nexit 31\n")
            fake.chmod(0o700)
            import os
            env = {**os.environ, "PATH": str(tmp) + ":" + os.environ["PATH"], "ENGINE": "mysql", "DATABASE_PASSWORD": "test", "DATABASE_HOST": "invalid", "DATABASE_USER": "test"}
            result = subprocess.run(["sh", "-c", script], env=env, capture_output=True)
            self.assertEqual(result.returncode, 31)
            self.assertFalse((tmp / "SHA256SUMS").exists())
            self.assertFalse((tmp / "_COMPLETE").exists())

    def test_scripts_fail_closed_and_do_not_expire_remote_objects(self):
        for name in ["export.sh", "upload.sh", "clickhouse.sh"]:
            text = (ROOT / "database/backup" / name).read_text()
            self.assertIn("set -eu", text)
            self.assertIn("umask 077", text)
            self.assertNotIn("s3 rm", text)
            self.assertNotIn("--delete", text)
            subprocess.run(["sh", "-n"], input=text, text=True, check=True)
        text = (ROOT / "database/backup/upload.sh").read_text()
        self.assertLess(text.index('test "$actual" = "$expected"'), text.index("/backup/_COMPLETE"))
        self.assertNotIn("--system=users", (ROOT / "database/backup/export.sh").read_text())

    def test_restore_can_only_target_new_ephemeral_local_databases(self):
        for script in RESTORE.values():
            subprocess.run(["sh", "-n"], input=script, text=True, check=True)
        for engine in ["pgsql", "mysql", "mongo"]:
            pod = restore_pod("backup-restore-test", engine, engine + "/20261025T000000Z-uuid/", "native@sha256:test", "uploader@sha256:test")
            spec = pod["spec"]
            self.assertFalse(spec["automountServiceAccountToken"])
            self.assertTrue(all("emptyDir" in v for v in spec["volumes"]))
            restore = spec["containers"][0]
            self.assertNotIn("envFrom", restore)
            self.assertNotIn("env", restore)
            self.assertNotIn("-service", restore["command"][-1])
            self.assertIn("127.0.0.1", restore["command"][-1])
            self.assertNotIn("--drop", restore["command"][-1])
            self.assertIn("RESTORE_OK " + engine, restore["command"][-1])
        for prefix in ["../", "pgsql/../../", "mysql/20261025T000000Z-uuid/", "pgsql/x/;echo unsafe"]:
            with self.assertRaises(RuntimeError):
                restore_pod("backup-restore-test", "pgsql", prefix, "native", "uploader")

    def test_velero_restores_original_node_agent_and_default_pvc_backup_settings(self):
        app = next(yaml.safe_load_all((ROOT / "apps/velero.yml").read_text()))
        chart = app["spec"]["sources"][1]
        self.assertEqual(chart["targetRevision"], "12.2.1")
        values = chart["helm"]["valuesObject"]
        self.assertTrue(values["deployNodeAgent"])
        self.assertFalse(values["snapshotsEnabled"])
        self.assertTrue(values["rbac"]["clusterAdministrator"])
        self.assertFalse(values["nodeAgent"]["containerSecurityContext"]["privileged"])
        self.assertFalse(values["containerSecurityContext"]["readOnlyRootFilesystem"])
        self.assertEqual(values["podSecurityContext"]["runAsUser"], 0)
        self.assertTrue(values["configuration"]["defaultVolumesToFsBackup"])
        self.assertEqual(values["configuration"]["fsBackupTimeout"], "12h")
        self.assertFalse(values["cleanUpCRDs"])
        self.assertIn("sha256:", values["image"]["digest"])
        self.assertIn("@sha256:", values["initContainers"][0]["image"])
        self.assertEqual(values["credentials"]["existingSecret"], "velero-s3")
        schedule = values["schedules"]["backup"]
        self.assertFalse(schedule["paused"])
        self.assertFalse(schedule["skipImmediately"])
        self.assertFalse(schedule["template"]["snapshotVolumes"])
        self.assertTrue(schedule["template"]["defaultVolumesToFsBackup"])
        self.assertEqual(schedule["template"]["uploaderConfig"]["parallelFilesUpload"], 16)

    def test_kopia_source_is_read_only_pinned_to_one_node_and_not_privileged(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "kopia")], text=True)))
        deployments = [d for d in docs if d["kind"] == "Deployment"]
        self.assertEqual(len(deployments), 1)
        for deployment in deployments:
            pod = deployment["spec"]["template"]["spec"]
            self.assertEqual(pod["nodeSelector"], {"kubernetes.io/hostname": "pmhoci"})
            self.assertFalse(pod["automountServiceAccountToken"])
            self.assertNotIn("hostNetwork", pod)
            c = pod["containers"][0]
            self.assertFalse(c["securityContext"]["privileged"])
            self.assertFalse(c["securityContext"]["allowPrivilegeEscalation"])
            self.assertEqual(c["securityContext"]["capabilities"], {"drop": ["ALL"], "add": ["DAC_READ_SEARCH"]})
            self.assertIn("@sha256:", c["image"])
            sources = {v["name"] for v in pod["volumes"] if "hostPath" in v}
            self.assertTrue(all(m["readOnly"] for m in c["volumeMounts"] if m["name"] in sources))
            self.assertTrue(all(v["hostPath"]["type"] == "Directory" for v in pod["volumes"] if "hostPath" in v))
            self.assertEqual(c["args"][:2], ["server", "start"])

    def test_vault_snapshot_only_gets_ca_and_dedicated_snapshot_identity(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "vault-backup")], text=True)))
        job = next(d for d in docs if d["kind"] == "CronJob")
        self.assertFalse(job["spec"]["suspend"])
        pod = job["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        self.assertEqual(pod["serviceAccountName"], "vault-snapshot")
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertTrue(all("hostPath" not in v and "persistentVolumeClaim" not in v for v in pod["volumes"]))
        ca = next(v for v in pod["volumes"] if v["name"] == "ca")
        self.assertEqual(ca["secret"]["items"], [{"key": "ca.crt", "path": "ca.crt"}])
        self.assertNotIn("env", pod["initContainers"][0])
        self.assertNotIn("identity", [m["name"] for m in pod["containers"][0]["volumeMounts"]])
        for c in pod["initContainers"] + pod["containers"]:
            self.assertIn("@sha256:", c["image"])
        vault = Mock()
        vault_snapshot_roles(vault)
        policy = next(c.kwargs["payload"] for c in vault.run.call_args_list if c.args[:3] == ("policy", "write", "lab-vault-snapshot"))
        self.assertEqual(policy, 'path "sys/storage/raft/snapshot" { capabilities = ["read", "sudo"] }\n')
        code = (ROOT / "vault-backup/snapshot.py").read_text()
        self.assertNotIn('request("sys/storage/raft/snapshot",', code)
        self.assertNotIn("snapshot-force", code)
        self.assertNotIn("unseal", code)
        self.assertIn('ssl.create_default_context(cafile=', code)

    def test_native_vault_snapshot_validates_sealed_state_and_internal_hashes(self):
        spec = importlib.util.spec_from_file_location("vault_backup_snapshot", ROOT / "vault-backup/snapshot.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for corrupt in [False, True]:
            output = io.BytesIO()
            content = {"meta.json": b"{}", "state.bin": b"sealed-state", "SHA256SUMS.sealed": b"sealed-checksum"}
            content["SHA256SUMS"] = b"".join((hashlib.sha256(body).hexdigest() + "  " + name + "\n").encode() for name, body in list(content.items())[:2])
            if corrupt:
                content["state.bin"] = b"changed"
            with tarfile.open(fileobj=output, mode="w:gz") as archive:
                for name, body in content.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(body)
                    archive.addfile(info, io.BytesIO(body))
            if corrupt:
                with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                    module.validate_snapshot(output.getvalue())
            else:
                module.validate_snapshot(output.getvalue())
