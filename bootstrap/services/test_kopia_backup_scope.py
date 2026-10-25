import subprocess
import unittest

import yaml

from provision import ROOT


class KopiaBackupScopeTests(unittest.TestCase):
    def test_original_single_persistent_server_mounts_only_mnt_data(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "kopia")], text=True)))
        self.assertFalse(any(d["kind"] == "CronJob" for d in docs))
        deployments = [d for d in docs if d["kind"] == "Deployment"]
        self.assertEqual(len(deployments), 1)
        deployment = deployments[0]
        self.assertEqual(deployment["spec"]["replicas"], 1)
        pod = deployment["spec"]["template"]["spec"]
        self.assertEqual(pod["hostname"], "pmhoci")
        self.assertEqual(pod["nodeSelector"], {"kubernetes.io/hostname": "pmhoci"})
        self.assertEqual(len(pod["containers"]), 1)
        self.assertEqual([v for v in pod["volumes"] if "hostPath" in v], [{"name": "target", "hostPath": {"path": "/mnt/data/", "type": "Directory"}}])
        native = pod["containers"][0]
        self.assertEqual(next(m for m in native["volumeMounts"] if m["name"] == "target"), {"name": "target", "mountPath": "/data", "readOnly": True})
        self.assertTrue(any(v.get("persistentVolumeClaim", {}).get("claimName") == "kopia-pvc" for v in pod["volumes"]))
        self.assertEqual({m["mountPath"] for m in native["volumeMounts"] if m["name"] == "persistent"}, {"/app/config", "/app/cache", "/app/logs", "/tmp"})
        self.assertNotIn("/var/lib/rancher", str(pod))
        self.assertNotIn("--readonly", str(native))
