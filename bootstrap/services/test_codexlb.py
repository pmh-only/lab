import subprocess
import unittest

import yaml

from provision import ROOT, PROFILES


class CodexTests(unittest.TestCase):
    def test_native_setup_is_isolated_from_upstream_credentials(self):
        path, fields = PROFILES["codexlb"]
        self.assertEqual(path, "codexlb/bootstrap-login")
        self.assertEqual(fields, {"ADMIN_PASSWORD": "random", "BOOTSTRAP_TOKEN": "random"})
        script = (ROOT / "codexlb/initialize.py").read_text()
        self.assertIn('if not state.get("passwordRequired"):', script)
        self.assertIn('/api/dashboard-auth/password/setup', script)
        self.assertNotIn('/api/dashboard-auth/password/change', script)
        self.assertNotIn('OPENAI_API_KEY', script)
        self.assertIn('"bootstrapToken": bootstrap', script)

    def test_persistent_writer_and_bootstrap_job_are_safe(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "codexlb")], text=True)))
        deployment = next(d for d in docs if d["kind"] == "Deployment")
        self.assertEqual(deployment["spec"]["strategy"]["type"], "Recreate")
        self.assertFalse(deployment["spec"]["template"]["spec"]["automountServiceAccountToken"])
        job = next(d for d in docs if d["kind"] == "Job")
        self.assertEqual(job["metadata"]["annotations"]["argocd.argoproj.io/hook"], "PostSync")
        self.assertFalse(job["spec"]["template"]["spec"]["automountServiceAccountToken"])
        pvc = next(d for d in docs if d["kind"] == "PersistentVolumeClaim")
        self.assertEqual(pvc["metadata"]["annotations"]["argocd.argoproj.io/sync-options"], "Prune=false")


if __name__ == "__main__":
    unittest.main()
