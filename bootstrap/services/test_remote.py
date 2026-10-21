from pathlib import Path
import subprocess
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


class RemoteBootstrapTests(unittest.TestCase):
    def test_native_schema_and_private_owner_initialized_before_server(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "remote")], text=True)))
        job = next(d for d in docs if d["kind"] == "Job")
        pod = job["spec"]["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertIn("initdb.sh --postgresql", " ".join(pod["initContainers"][0]["command"]))
        for container in pod["containers"] + pod["initContainers"]:
            self.assertIn("@sha256:", container["image"])
        for deployment in [d for d in docs if d["kind"] == "Deployment"]:
            self.assertEqual(deployment["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "1")
        sql = (ROOT / "remote/initialize.sql").read_text()
        self.assertIn("pg_advisory_lock", sql)
        self.assertIn("\\if :initialize", sql)
        self.assertIn("disabled = (:'owner_name' <> 'guacadmin')", sql)
        self.assertIn("upper(:'salt')", sql)
        self.assertIn("\\getenv owner_password", sql)


if __name__ == "__main__":
    unittest.main()
