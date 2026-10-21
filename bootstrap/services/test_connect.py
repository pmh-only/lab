import json
import subprocess
import unittest

import yaml

from provision import ROOT, PROFILES


class ConnectTests(unittest.TestCase):
    def test_persistent_writer_and_data_path(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "connect")], text=True)))
        deployment = next(d for d in docs if d["kind"] == "Deployment")
        self.assertEqual(deployment["spec"]["strategy"]["type"], "Recreate")
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        env = {e["name"]: e for e in container["env"]}
        self.assertEqual(env["DATA_FILE"]["value"], "/data/collections.jsonl")
        self.assertEqual(env["ROSTACK_API_VERSION"]["value"], "2026-08-13")
        self.assertEqual(container["readinessProbe"]["httpGet"]["path"], "/healthz")
        self.assertIn("@sha256:", container["image"])
        pvc = next(d for d in docs if d["kind"] == "PersistentVolumeClaim")
        self.assertEqual(pvc["metadata"]["annotations"]["argocd.argoproj.io/sync-options"], "Prune=false")

    def test_internal_tokens_and_oidc_share_declared_vault_path(self):
        desired = json.loads((ROOT / "bootstrap/services/oidc.json").read_text())["connect"]
        path, fields = PROFILES["connect"]
        self.assertEqual(path, desired["vaultPath"])
        self.assertEqual(set(fields), {desired["secretField"], *desired["companionSecretFields"]})
        self.assertTrue(all(kind == "random" for kind in fields.values()))


if __name__ == "__main__":
    unittest.main()
