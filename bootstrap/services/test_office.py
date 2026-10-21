import json
from pathlib import Path
import re
import subprocess
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


class OfficeTests(unittest.TestCase):
    def test_only_managed_s3_downloads_exclude_outgoing_jwt(self):
        config = yaml.safe_load((ROOT / "office/configmap.yml").read_text())
        data = json.loads(config["data"]["local-production-linux.json"])
        token = data["services"]["CoAuthoring"]["token"]
        self.assertNotIn("enable", token)
        pattern = re.compile(token["outbox"]["urlExclusionRegex"])
        self.assertTrue(pattern.match("https://hello.s3.pmh.codes/index.html"))
        self.assertTrue(pattern.match("https://s3.pmh.codes/hello/index.html"))
        self.assertFalse(pattern.match("https://drive.pmh.codes/callback"))
        self.assertFalse(pattern.match("https://hello.s3.pmh.codes.attacker.example/test"))

    def test_storage_initialization_does_not_overwrite_existing_data(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "office")], text=True)))
        deployment = next(d for d in docs if d["kind"] == "Deployment")
        self.assertEqual(deployment["spec"]["strategy"]["type"], "Recreate")
        pod = deployment["spec"]["template"]["spec"]
        host = next(v["hostPath"] for v in pod["volumes"] if "hostPath" in v)
        self.assertEqual(host, {"path": "/mnt/data/office", "type": "DirectoryOrCreate"})
        env = {e["name"]: e for e in pod["containers"][0]["env"]}
        self.assertEqual(env["JWT_ENABLED"]["value"], "true")
        self.assertIn("secretKeyRef", env["JWT_SECRET"]["valueFrom"])


if __name__ == "__main__":
    unittest.main()
