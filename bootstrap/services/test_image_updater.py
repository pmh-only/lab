import subprocess
import unittest

import yaml

from provision import ROOT
from register_image_updaters import REVIEWED


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
        secret = next(v["secret"] for v in pod["volumes"] if v["name"] == "ssh-signing-key")
        self.assertEqual(secret["secretName"], "git")
        self.assertFalse(secret["optional"])
        self.assertEqual(secret["defaultMode"], 0o440)
        vss = next(d for d in self.docs if d["kind"] == "VaultStaticSecret")
        self.assertEqual(vss["spec"]["path"], "argocd/image-updater-git")
        self.assertEqual(vss["spec"]["destination"]["name"], "git")

    def test_mail_is_single_owned_and_does_not_track_removed_bridge(self):
        updater = next(d for d in self.docs if d["kind"] == "ImageUpdater")
        self.assertEqual(updater["spec"]["writeBackConfig"]["method"], "git:secret:argocd/git")
        ref = updater["spec"]["applicationRefs"][0]
        self.assertEqual(ref["namePattern"], "mail")
        self.assertEqual({i["alias"] for i in ref["images"]}, {"mail", "mail-worker"})
        self.assertTrue(all(i["commonUpdateSettings"]["updateStrategy"] == "digest" for i in ref["images"]))
        app_docs = list(yaml.safe_load_all((ROOT / "apps/mail.yml").read_text()))
        self.assertFalse(any(d and d["kind"] == "ImageUpdater" for d in app_docs))

    def test_registration_does_not_blindly_update_version_adapters_or_stateful_infrastructure(self):
        self.assertTrue(REVIEWED.isdisjoint({"database", "nameserver", "trace", "traffic", "visualized", "authentik", "immich", "minio", "gateway", "monitoring", "seafile"}))
        for name in REVIEWED:
            docs = list(yaml.safe_load_all((ROOT / "apps" / f"{name}.yml").read_text()))
            updater = next(d for d in docs if d and d["kind"] == "ImageUpdater")
            self.assertEqual(updater["spec"]["applicationRefs"][0]["namePattern"], name)
            for image in updater["spec"]["applicationRefs"][0]["images"]:
                self.assertFalse(image["imageName"].startswith("gchcr.io/"))
                self.assertEqual(image["commonUpdateSettings"]["updateStrategy"], "digest")


if __name__ == "__main__":
    unittest.main()
