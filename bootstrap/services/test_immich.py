import json
import subprocess
import unittest

import yaml

from provision import ROOT, PROFILES


class ImmichTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "immich")], text=True)))

    def test_persistent_writers_are_single_and_old_pv_binding_is_not_imported(self):
        for doc in self.docs:
            if doc["kind"] == "Deployment":
                self.assertEqual(doc["spec"]["strategy"]["type"], "Recreate")
                pod = doc["spec"]["template"]["spec"]
                self.assertFalse(pod["automountServiceAccountToken"])
                self.assertNotIn("backpack", [c["name"] for c in pod.get("initContainers", [])])
                for container in pod.get("initContainers", []) + pod["containers"]:
                    self.assertIn("@sha256:", container["image"])
        pvc = next(d for d in self.docs if d["kind"] == "PersistentVolumeClaim")
        self.assertNotIn("volumeName", pvc["spec"])
        self.assertEqual(pvc["metadata"]["annotations"]["argocd.argoproj.io/sync-options"], "Prune=false")

    def test_native_database_init_gives_app_no_superuser_or_admin_password(self):
        script = (ROOT / "immich/db-init.sh").read_text()
        self.assertIn("NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION", script)
        self.assertIn("CREATE EXTENSION IF NOT EXISTS vchord CASCADE", script)
        self.assertIn("CREATE EXTENSION IF NOT EXISTS earthdistance CASCADE", script)
        self.assertNotIn("DROP ", script)
        app = next(d for d in self.docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "immich")
        env = {e["name"]: e for e in app["spec"]["template"]["spec"]["containers"][0]["env"]}
        self.assertEqual(env["DB_VECTOR_EXTENSION"]["value"], "vectorchord")
        self.assertEqual(env["IMMICH_MEDIA_LOCATION"]["value"], "/usr/src/app/upload")
        self.assertNotIn("DB_ADMIN_PASSWORD", env)
        self.assertNotIn("IMMICH_CONFIG_FILE", env)
        self.assertEqual(PROFILES["immich"][1], {"DB_PASSWORD": "random", "DB_ADMIN_PASSWORD": "random"})

    def test_secret_pvc_and_owner_waves_cannot_expose_first_admin_setup(self):
        wave = lambda d: int(d["metadata"].get("annotations", {}).get("argocd.argoproj.io/sync-wave", "0"))
        deployments = {d["metadata"]["name"]: d for d in self.docs if d["kind"] == "Deployment"}
        db = deployments["pgsql"]
        for doc in self.docs:
            if doc["kind"] in {"VaultStaticSecret", "VaultAuth", "ServiceAccount", "PersistentVolumeClaim"}:
                self.assertLess(wave(doc), wave(db))
        job = next(d for d in self.docs if d["kind"] == "Job")
        self.assertGreater(wave(job), wave(deployments["immich"]))
        ingress = yaml.safe_load((ROOT / "immich/ingress.yml").read_text())
        self.assertGreater(wave(ingress), wave(job))
        script = (ROOT / "immich/initialize-owner.py").read_text()
        self.assertIn('created = not state["isInitialized"]', script)
        self.assertIn('if created:', script)
        self.assertIn('request("/auth/logout"', script)
        self.assertNotIn('request("/auth/change-password"', script)
        config = json.loads((ROOT / "immich/bootstrap.json").read_text())
        self.assertIn("app.immich:///oauth-callback", config["oauth"]["redirectURIs"])


if __name__ == "__main__":
    unittest.main()
