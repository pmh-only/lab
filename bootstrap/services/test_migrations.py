from pathlib import Path
import subprocess
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


class MigrationTests(unittest.TestCase):
    def test_migrations_use_pinned_images_and_only_application_db_credentials(self):
        for namespace in ["keysboard", "mail"]:
            docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / namespace)], text=True)))
            job = next(d for d in docs if d["kind"] == "Job")
            self.assertEqual(job["metadata"]["annotations"]["argocd.argoproj.io/hook"], "Sync")
            pod = job["spec"]["template"]["spec"]
            self.assertFalse(pod["automountServiceAccountToken"])
            container = pod["containers"][0]
            self.assertIn("@sha256:", container["image"])
            self.assertEqual([e["name"] for e in container["env"]], ["DATABASE_URL"])
            for deployment in [d for d in docs if d["kind"] == "Deployment"]:
                self.assertGreater(int(deployment["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]), int(job["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]))

    def test_keysboard_schema_matches_pinned_runtime_source_not_unverified_latest(self):
        script = (ROOT / "keysboard/migrate.cjs").read_text()
        self.assertIn("b90e6d723413f7bdb7fe150268bdea0f873acc0f", script)
        self.assertIn("prisma@5.6.0", script)
        self.assertIn("583d8befa496bb91fefd56561b94eff6e04e7504a8bf7729e5b24b570997adb8", script)
        self.assertIn("2024131f5206499a77a48e337d3eee323790c3a5296c3ef6ff91507c92a1b7b6", script)
        self.assertNotIn("migrate', 'reset", script)


if __name__ == "__main__":
    unittest.main()
