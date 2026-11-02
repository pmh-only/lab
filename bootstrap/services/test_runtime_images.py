"""Regression checks for image-build fixes replacing Pod-time code overlays."""
import runpy
import subprocess
import unittest
from unittest.mock import patch

import yaml

from provision import ROOT


class RuntimeImageTests(unittest.TestCase):
    def test_migrated_services_do_not_rewrite_application_code_at_startup(self):
        for app, image in [("solver", "solver"), ("trace", "lab-trace"), ("spotify", "lab-spotify"), ("thepool", "thepool"), ("keysboard", "keysboard")]:
            docs = list(yaml.safe_load_all(subprocess.check_output(
                ["kubectl", "kustomize", str(ROOT / app)], text=True)))
            found = False
            for doc in docs:
                if doc["kind"] not in {"Deployment", "Job"}:
                    continue
                pod = doc["spec"]["template"]["spec"]
                for container in pod["containers"]:
                    if f"ghcr.io/pmh-only/{image}:" not in container["image"]:
                        continue
                    found = True
                    self.assertIn("@sha256:", container["image"])
                    self.assertFalse(any(v["mountPath"].startswith("/app/") and v["mountPath"] != "/app/data"
                                         for v in container.get("volumeMounts", [])))
                for container in pod.get("initContainers", []):
                    self.assertNotIn(container["name"], ["native-client-compatibility", "prepare-native-api"])
            self.assertTrue(found, app)

    def test_keysboard_migrates_with_the_exact_application_image_and_no_downloads(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(
            ["kubectl", "kustomize", str(ROOT / "keysboard")], text=True)))
        app = next(d for d in docs if d["kind"] == "Deployment")["spec"]["template"]["spec"]["containers"][0]
        job = next(d for d in docs if d["kind"] == "Job")["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(app["image"], job["image"])
        self.assertEqual(job["command"], ["node", "/opt/migrator/node_modules/prisma/build/index.js", "migrate", "deploy", "--schema=/app/prisma/schema.prisma"])

    def test_resolver_handles_digest_pinned_inputs_without_corrupting_repository(self):
        digest = "sha256:" + "a" * 64
        with patch("sys.argv", ["resolve.py", "goaccess"]), \
                patch("subprocess.check_output", return_value=digest), \
                patch("builtins.print") as output:
            runpy.run_path(str(ROOT / "images/resolve.py"))
        lines = [call.args[0] for call in output.call_args_list]
        self.assertEqual(lines[0], "base=ghcr.io/pmh-only/goaccess@" + digest)
        self.assertRegex(lines[-1], r"^tag=inputs-[a-f0-9]{64}$")

    def test_downstream_image_updaters_cannot_bypass_reviewed_images(self):
        deployed = yaml.safe_load((ROOT / "image-updater/deployed.yml").read_text())
        expected = {"trace": "lab-trace", "spotify": "lab-spotify", "seafile": "lab-seafile", "traffic": "lab-goaccess"}
        for item in deployed["items"]:
            app = item["metadata"]["name"]
            if app not in expected:
                continue
            images = item["spec"]["applicationRefs"][0]["images"]
            self.assertTrue(any(i["imageName"] == f"ghcr.io/pmh-only/{expected[app]}:latest" for i in images))


if __name__ == "__main__":
    unittest.main()
