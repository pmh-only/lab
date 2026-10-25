import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

import yaml

from backup_s3 import PROFILES, reconcile
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
            self.assertEqual("s3:DeleteObject" in text, name != "database")
            resources = [r for s in policy["Statement"] for r in s["Resource"]]
            self.assertTrue(all(r.startswith("arn:aws:s3:::" + profile["bucket"]) for r in resources))

    def test_unmanaged_identity_is_not_replaced(self):
        vault, admin = Mock(), Mock()
        vault.get.return_value = {"S3_ACCESS_TOKEN": "unmanaged", "S3_SECRET_TOKEN": "x" * 64}
        with self.assertRaisesRegex(RuntimeError, "Unmanaged"):
            reconcile(vault, admin, "database", "http://127.0.0.1:19000")
        admin.request.assert_not_called()
        vault.create.assert_not_called()

    def test_database_jobs_are_suspended_hardened_pinned_and_do_not_mount_live_volumes(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "database")], text=True)))
        jobs = [d for d in docs if d["kind"] == "CronJob"]
        self.assertEqual({j["metadata"]["name"] for j in jobs}, {"backup-" + n for n in ["pgsql", "mysql", "mongo", "clickhouse"]})
        for job in jobs:
            self.assertTrue(job["spec"]["suspend"])
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
