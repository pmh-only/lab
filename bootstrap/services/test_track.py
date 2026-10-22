import subprocess
import unittest

import yaml

from provision import ROOT


class TrackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "track")], text=True)))
        cls.deployments = {d["metadata"]["name"]: d for d in cls.docs if d["kind"] == "Deployment"}

    def test_single_writers_and_retained_local_storage_have_safe_ordering(self):
        for name, deployment in self.deployments.items():
            self.assertEqual(deployment["spec"]["strategy"]["type"], "Recreate")
            pod = deployment["spec"]["template"]["spec"]
            self.assertFalse(pod["automountServiceAccountToken"])
            for container in pod["containers"]:
                self.assertIn("@sha256:", container["image"])
            wave = deployment["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]
            self.assertEqual(wave, "-1" if name in {"track-postgis", "track-redis"} else "1")
        pvc = next(d for d in self.docs if d["kind"] == "PersistentVolumeClaim")
        self.assertEqual(pvc["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "-1")
        self.assertEqual(pvc["metadata"]["annotations"]["argocd.argoproj.io/sync-options"], "Prune=false")
        self.assertNotIn("volumeName", pvc["spec"])
        job = next(d for d in self.docs if d["kind"] == "Job")
        self.assertEqual(job["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "0")

    def test_native_postgis_initializer_is_not_hidden_and_app_is_not_superuser(self):
        script = (ROOT / "track/db-init.sh").read_text()
        self.assertIn("NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION", script)
        self.assertNotIn("DROP ", script)
        pod = self.deployments["track-postgis"]["spec"]["template"]["spec"]
        mounts = pod["containers"][0]["volumeMounts"]
        self.assertIn("/docker-entrypoint-initdb.d/20-lab-track.sh", [v["mountPath"] for v in mounts])
        self.assertNotIn("/docker-entrypoint-initdb.d", [v["mountPath"] for v in mounts])
        for name in ["track", "track-sidekiq"]:
            container = self.deployments[name]["spec"]["template"]["spec"]["containers"][0]
            env = {e["name"]: e for e in container["env"]}
            self.assertEqual(env["DATABASE_USERNAME"]["value"], "dawarich")
            self.assertNotIn("track-db-admin", str(container))
            self.assertNotIn("/dawarich_db_data", [v["mountPath"] for v in container["volumeMounts"]])
        web = self.deployments["track"]["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(web["startupProbe"]["httpGet"]["path"], "/api/v1/health")
        self.assertEqual(web["readinessProbe"]["httpGet"]["path"], "/api/v1/ready")

    def test_auth_and_original_geocoding_are_preserved_with_real_key_and_free_plan_rate(self):
        values = dict(line.split("=", 1) for line in (ROOT / "track/runtime.env").read_text().splitlines())
        self.assertEqual(values["PHOTON_API_HOST"], "app.chibigeo.com/v1/photon")
        self.assertEqual(values["REVERSE_GEOCODING_RPS"], "1")
        self.assertEqual(values["STORE_GEODATA"], "true")
        self.assertEqual(values["ALLOW_EMAIL_PASSWORD_REGISTRATION"], "false")
        self.assertEqual(values["ALLOW_EMAIL_PASSWORD_LOGIN"], "false")
        self.assertEqual(values["OIDC_PKCE_ENABLED"], "true")
        source = (ROOT / "bootstrap/services/track.py").read_text()
        self.assertIn('complete = dict(data)', source)
        self.assertIn('"-cas="', source)
        self.assertIn('preview_user/?for_user=', source)

    def test_native_owner_precedes_upstream_seeds_and_never_resets_existing_users(self):
        code = (ROOT / "track/initialize.sh").read_text()
        self.assertLess(code.index("initialize-owner.rb"), code.index("rails db:seed"))
        owner = (ROOT / "track/initialize-owner.rb").read_text()
        self.assertIn("unless User.unscoped.none?", owner)
        self.assertIn("provider: 'openid_connect', uid: subject", owner)
        self.assertNotIn("update!", owner)
        self.assertNotIn("destroy", owner)
        self.assertNotIn("delete", owner)


if __name__ == "__main__":
    unittest.main()
