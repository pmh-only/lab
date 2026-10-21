import json
import subprocess
import unittest

import yaml

from provision import ROOT, PROFILES


class BooksTests(unittest.TestCase):
    def test_fresh_storage_keys_and_separate_jwt_secrets(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "books")], text=True)))
        containers = {d["metadata"]["name"]: d["spec"]["template"]["spec"]["containers"][0] for d in docs if d["kind"] == "Deployment"}
        for name in ["books-backend", "books-worker"]:
            env = {e["name"]: e for e in containers[name]["env"]}
            self.assertEqual(env["S3_ACCESS_KEY_ID"]["valueFrom"]["secretKeyRef"], {"name": "books-secret", "key": "S3_ACCESS_KEY_ID"})
            self.assertNotIn("NODE_TLS_REJECT_UNAUTHORIZED", env)
            self.assertIn("@sha256:", containers[name]["image"])
        env = {e["name"]: e for e in containers["books-backend"]["env"]}
        self.assertEqual(env["JWT_REFRESH_SECRET"]["valueFrom"]["secretKeyRef"]["key"], "JWT_REFRESH_SECRET")
        self.assertEqual(env["JWT_ACCESS_SECRET"]["valueFrom"]["secretKeyRef"]["key"], "JWT_ACCESS_SECRET")

    def test_native_oidc_credentials_share_managed_vault_path(self):
        declaration = json.loads((ROOT / "bootstrap/services/oidc.json").read_text())["books"]
        path, fields = PROFILES["books"]
        self.assertEqual(path, declaration["vaultPath"])
        self.assertEqual(set(fields), {declaration["secretField"], *declaration["companionSecretFields"]})
        self.assertEqual(fields["DATABASE_URL"], "postgres:books")


if __name__ == "__main__":
    unittest.main()
