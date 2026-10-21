from pathlib import Path
import subprocess
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


class DatabaseSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "database")], text=True)))

    def test_persistent_database_writers_do_not_overlap(self):
        deployments = {d["metadata"]["name"]: d for d in self.docs if d["kind"] == "Deployment"}
        for name in ["pgsql", "mysql", "mongo", "clickhouse"]:
            strategy = deployments[name]["spec"]["strategy"]
            self.assertEqual(strategy["type"], "Recreate")
            self.assertIsNone(strategy.get("rollingUpdate"))

    def test_original_and_recovery_volumes_are_retained(self):
        claims = {d["metadata"]["name"]: d for d in self.docs if d["kind"] == "PersistentVolumeClaim"}
        for name in ["pgsql-pvc", "pgsql-recovery-work", "pgsql-recovery-clean"]:
            self.assertEqual(claims[name]["metadata"]["annotations"]["argocd.argoproj.io/sync-options"], "Prune=false")
        postgres = next(d for d in self.docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "pgsql")
        pod = postgres["spec"]["template"]["spec"]
        self.assertEqual(pod["volumes"][0]["persistentVolumeClaim"]["claimName"], "pgsql-recovery-clean")
        self.assertIn("startupProbe", pod["containers"][0])
        self.assertIn("readinessProbe", pod["containers"][0])


if __name__ == "__main__":
    unittest.main()
