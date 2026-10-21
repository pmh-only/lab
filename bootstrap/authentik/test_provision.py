import copy
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock

import yaml

from provision import APP, BOOTSTRAP, LOGIN, ROOT, configure_reader, credentials, password_hash


class FakeVault:
    def __init__(self):
        self.data = {}
        self.writes = 0

    def get(self, path):
        return copy.deepcopy(self.data.get(path))

    def create(self, path, data):
        if path in self.data:
            raise RuntimeError("Refusing overwrite")
        self.data[path] = copy.deepcopy(data)
        self.writes += 1


class ProvisionTests(unittest.TestCase):
    def test_fresh_credentials_are_idempotent_and_password_not_in_worker_secret(self):
        vault = FakeVault()
        app = credentials(vault)
        before = copy.deepcopy(vault.data)
        self.assertEqual(credentials(vault), app)
        self.assertEqual(vault.writes, 3)
        self.assertEqual(before, vault.data)
        self.assertNotIn(vault.data[LOGIN]["password"], vault.data[BOOTSTRAP].values())
        hashed = vault.data[BOOTSTRAP]["AUTHENTIK_BOOTSTRAP_PASSWORD_HASH"]
        self.assertTrue(hashed.startswith("pbkdf2_sha256$1000000$"))

    def test_incomplete_or_mismatched_identity_is_not_replaced(self):
        vault = FakeVault()
        credentials(vault)
        del vault.data[LOGIN]
        with self.assertRaises(RuntimeError):
            credentials(vault)
        self.assertEqual(vault.writes, 3)

    def test_tampered_password_hash_is_rejected(self):
        vault = FakeVault()
        credentials(vault)
        vault.data[BOOTSTRAP]["AUTHENTIK_BOOTSTRAP_PASSWORD_HASH"] = password_hash("wrong-password")
        with self.assertRaises(RuntimeError):
            credentials(vault)

    def test_workload_reader_excludes_human_login_and_other_secrets(self):
        vault = Mock()
        configure_reader(vault)
        policy = vault.run.call_args_list[0].kwargs["payload"]
        self.assertIn('secret/data/' + APP, policy)
        self.assertIn('secret/data/' + BOOTSTRAP, policy)
        self.assertNotIn(LOGIN, policy)
        self.assertNotIn('*', policy)


class ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "authentik")], text=True)))

    def test_server_and_worker_are_unprivileged_pinned_and_colocated(self):
        deployments = [d for d in self.docs if d["kind"] == "Deployment"]
        self.assertEqual(len(deployments), 2)
        for deployment in deployments:
            pod = deployment["spec"]["template"]["spec"]
            self.assertFalse(pod["automountServiceAccountToken"])
            self.assertEqual(pod["nodeSelector"]["kubernetes.io/hostname"], "pmhoci2")
            self.assertTrue(pod["securityContext"]["runAsNonRoot"])
            for container in pod["containers"] + pod["initContainers"]:
                self.assertIn("@sha256:", container["image"])
            sources = {s["secretRef"]["name"] for s in pod["containers"][0]["envFrom"] if "secretRef" in s}
            if deployment["metadata"]["name"] == "authentik-server":
                self.assertEqual(sources, {"authentik-secrets"})
            else:
                self.assertEqual(sources, {"authentik-secrets", "authentik-bootstrap-worker"})

    def test_runtime_has_no_old_mail_or_redis_credentials(self):
        config = next(d["data"] for d in self.docs if d["kind"] == "ConfigMap")
        self.assertFalse(any("REDIS" in k or "EMAIL" in k for k in config))
        self.assertEqual(config["AUTHENTIK_WEB__BASE_URL"], "https://auth.pmh.codes")
        self.assertEqual(config["AUTHENTIK_STORAGE__FILE__PATH"], "/data")
        paths = {d["spec"]["path"] for d in self.docs if d["kind"] == "VaultStaticSecret"}
        self.assertEqual(paths, {APP, BOOTSTRAP})
        self.assertNotIn(LOGIN, paths)


if __name__ == "__main__":
    unittest.main()
