import subprocess
import unittest

import yaml

from provision import ROOT
from register_image_updaters import REVIEWED, DEPLOYED, HELM, ENABLED


class ImageUpdaterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "image-updater")], text=True)))

    def test_pinned_controller_uses_dedicated_vault_key_and_signed_bot_identity(self):
        config = next(d for d in self.docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "argocd-image-updater-config")["data"]
        self.assertEqual(config["git.user"], "ArgoCD")
        self.assertEqual(config["git.email"], "lab@pmh.codes")
        self.assertEqual(config["git.commit-signing-method"], "ssh")
        self.assertEqual(config["git.commit-signing-key"], "/app/ssh-keys/id_rsa")
        pod = next(d for d in self.docs if d["kind"] == "Deployment")["spec"]["template"]["spec"]
        self.assertIn("@sha256:", pod["containers"][0]["image"])
        self.assertEqual(pod["securityContext"]["fsGroup"], 1000)
        self.assertEqual(pod["containers"][0]["startupProbe"]["httpGet"], {"path": "/readyz", "port": 8081})
        self.assertGreaterEqual(pod["containers"][0]["startupProbe"]["failureThreshold"] * pod["containers"][0]["startupProbe"]["periodSeconds"], 600)
        secret = next(v["secret"] for v in pod["volumes"] if v["name"] == "ssh-signing-key")
        self.assertEqual(secret["secretName"], "git")
        self.assertFalse(secret["optional"])
        self.assertEqual(secret["defaultMode"], 0o440)
        vss = next(d for d in self.docs if d["kind"] == "VaultStaticSecret")
        self.assertEqual(vss["spec"]["path"], "argocd/image-updater-git")
        self.assertEqual(vss["spec"]["destination"]["name"], "git")

    def test_mail_is_single_owned_and_does_not_track_removed_bridge(self):
        updater = next(d for d in self.docs if d["kind"] == "ImageUpdater" and d["metadata"]["name"] == "mail")
        self.assertEqual(updater["spec"]["writeBackConfig"]["method"], "git:secret:argocd/git")
        ref = updater["spec"]["applicationRefs"][0]
        self.assertEqual(ref["namePattern"], "mail")
        self.assertEqual({i["alias"] for i in ref["images"]}, {"mail", "mail-worker"})
        self.assertTrue(all(i["commonUpdateSettings"]["updateStrategy"] == "digest" for i in ref["images"]))
        app_docs = list(yaml.safe_load_all((ROOT / "apps/mail.yml").read_text()))
        self.assertFalse(any(d and d["kind"] == "ImageUpdater" for d in app_docs))

    def test_all_enabled_apps_have_one_owned_digest_updater_without_paused_workloads(self):
        managed = {d["metadata"]["name"]: d for d in self.docs if d["kind"] == "ImageUpdater"}
        self.assertEqual(set(managed), ENABLED)
        self.assertEqual(len(managed), 43)
        self.assertTrue(ENABLED.isdisjoint({"as218822", "welplan", "kopia", "velero", "velero-ui", "ghost"}))
        apps = {}
        for path in (ROOT / "apps").glob("*.yml"):
            for d in yaml.safe_load_all(path.read_text()):
                if d and d["kind"] == "ImageUpdater":
                    self.assertNotIn(d["metadata"]["name"], ENABLED)
                if d and d["kind"] == "Application":
                    apps[d["metadata"]["name"]] = d
        for name in ENABLED:
            self.assertIn(name, apps)
            updater = managed[name]
            self.assertEqual(updater["spec"]["writeBackConfig"]["method"], "git:secret:argocd/git")
            self.assertEqual(updater["spec"]["applicationRefs"][0]["namePattern"], name)
            for image in updater["spec"]["applicationRefs"][0]["images"]:
                self.assertFalse(image["imageName"].startswith("gchcr.io/"))
                self.assertEqual(image["commonUpdateSettings"]["updateStrategy"], "digest")
                self.assertIn(":", image["imageName"].rsplit("/", 1)[-1])
                self.assertNotIn("backpack-", image["imageName"])
            if name in HELM:
                target = updater["spec"]["writeBackConfig"]["gitConfig"]["writeBackTarget"]
                self.assertEqual(target, f"helmvalues:/image-updater/helm-values/{name}.yml")
                sources = apps[name]["spec"]["sources"]
                self.assertTrue(any(s.get("ref") == "imageValues" and s["repoURL"] == "https://github.com/pmh-only/lab.git" for s in sources))
                helm = next(s["helm"] for s in sources if "helm" in s)
                self.assertIn(f"$imageValues/image-updater/helm-values/{name}.yml", helm["valueFiles"])
                values = yaml.safe_load((ROOT / f"image-updater/helm-values/{name}.yml").read_text())
                for image in updater["spec"]["applicationRefs"][0]["images"]:
                    key = image["manifestTargets"]["helm"].get("spec") or image["manifestTargets"]["helm"]["tag"]
                    v = values
                    inline = helm["valuesObject"]
                    for part in key.split("."):
                        v = v[part]
                        inline = inline.get(part, {})
                    self.assertIsInstance(v, str)
                    self.assertEqual(inline, {}, "inline values must not shadow the Git-updated image")
            else:
                self.assertEqual(updater["spec"]["writeBackConfig"]["gitConfig"]["writeBackTarget"], "kustomization")
        self.assertNotIn("automated", apps["vault"]["spec"]["syncPolicy"])

    def test_bootstrap_reads_the_single_gitops_owned_declaration_source(self):
        code = (ROOT / "bootstrap/services/register_image_updaters.py").read_text()
        self.assertIn('"reviewed.yml", "deployed.yml", "helm.yml", "mail.yml"', code)
        self.assertIn('"HEAD:image-updater/" + filename', code)
        self.assertNotIn("HEAD:apps/{name}.yml", code)

    def test_ssh_host_verification_is_not_disabled_by_default_secret_behavior(self):
        code = (ROOT / "bootstrap/services/image_updater.py").read_text()
        self.assertIn('"insecure": "false"', code)
        self.assertIn('"-cas="', code)

    def test_speed_sqlite_has_no_overlapping_writers_and_waits_for_http(self):
        deployment = yaml.safe_load((ROOT / "speed/deployment.yml").read_text())
        self.assertEqual(deployment["spec"]["strategy"]["type"], "Recreate")
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        for probe in ["startupProbe", "readinessProbe"]:
            self.assertEqual(container[probe]["httpGet"], {"path": "/", "port": 8080})


if __name__ == "__main__":
    unittest.main()
