import re
import subprocess
import unittest
from unittest.mock import patch

import yaml

from provision import ROOT
from register_image_updaters import REVIEWED, DEPLOYED, HELM, ENABLED, declaration


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
        self.assertIn("--warmup-cache=false", pod["containers"][0]["args"])
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

    def test_all_enabled_apps_have_one_owned_updater_without_vault_or_paused_workloads(self):
        managed = {d["metadata"]["name"]: d for d in self.docs if d["kind"] == "ImageUpdater"}
        self.assertEqual(set(managed), ENABLED)
        self.assertEqual(len(managed), 45)
        self.assertIn("as218822", ENABLED)
        self.assertTrue({"kopia", "velero", "velero-ui"}.issubset(ENABLED))
        self.assertTrue(ENABLED.isdisjoint({"welplan", "ghost", "vault", "vault-backup", "vault-secrets-operator", "vault-ui"}))
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
                settings = image["commonUpdateSettings"]
                strategy = settings["updateStrategy"]
                self.assertIn(strategy, {"digest", "semver", "newest-build"})
                if strategy == "semver":
                    self.assertIn(image["imageName"].rsplit(":", 1)[-1], {"*", "*-0"})
                elif strategy == "digest":
                    self.assertIn(":", image["imageName"].rsplit("/", 1)[-1])
                    self.assertFalse(re.match(r"^v?\d", image["imageName"].rsplit(":", 1)[-1]), "numeric versions must not stay digest-only")
                else:
                    self.assertTrue(settings["allowTags"].startswith("regexp:^"))
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
                    for part in filter(None, re.split(r"\.|\[|\]", key)):
                        if part.isdigit():
                            v = v[int(part)]
                            inline = inline[int(part)] if isinstance(inline, list) else {}
                        else:
                            v = v[part]
                            inline = inline.get(part, {})
                    self.assertIsInstance(v, str)
                    self.assertEqual(inline, {}, "inline values must not shadow the Git-updated image")
            else:
                self.assertEqual(updater["spec"]["writeBackConfig"]["gitConfig"]["writeBackTarget"], "kustomization")
        self.assertNotIn("automated", apps["vault"]["spec"]["syncPolicy"])
        vault_pin = yaml.safe_load((ROOT / "image-updater/helm-values/vault.yml").read_text())
        self.assertRegex(vault_pin["server"]["image"]["tag"], r"^2\.2\.1@sha256:[a-f0-9]{64}$")

    def test_as218822_tracks_all_pinned_images_with_one_owner(self):
        updater = next(d for d in self.docs if d["kind"] == "ImageUpdater" and d["metadata"]["name"] == "as218822")
        images = updater["spec"]["applicationRefs"][0]["images"]
        pinned = yaml.safe_load((ROOT / "as218822/kustomization.yml").read_text())["images"]
        self.assertEqual({i["imageName"] for i in images}, {f'{i["name"]}:{i["newTag"]}' for i in pinned})
        app_docs = list(yaml.safe_load_all((ROOT / "apps/as218822.yml").read_text()))
        self.assertFalse(any(d and d["kind"] == "ImageUpdater" for d in app_docs))

    def test_backup_updaters_cover_deployed_images_without_stale_pins(self):
        managed = {d["metadata"]["name"]: d for d in self.docs if d["kind"] == "ImageUpdater"}
        kopia_images = managed["kopia"]["spec"]["applicationRefs"][0]["images"]
        self.assertEqual({i["imageName"] for i in kopia_images}, {"kopia/kopia:latest", "nginx:stable-alpine"})
        velero_images = managed["velero"]["spec"]["applicationRefs"][0]["images"]
        self.assertEqual({i["imageName"] for i in velero_images}, {"docker.io/velero/velero:*", "velero/velero-plugin-for-aws:*"})
        for image in velero_images:
            pattern = image["commonUpdateSettings"]["allowTags"].removeprefix("regexp:")
            for tag in ["v1.18.4", "v2.0.0", "v99.1.2"]:
                self.assertRegex(tag, pattern)
            for tag in ["1220", "v1220", "latest", "v1.18.4-rc.1", "v1.18.4-amd64"]:
                self.assertIsNone(re.match(pattern, tag))
        values = yaml.safe_load((ROOT / "image-updater/helm-values/velero.yml").read_text())
        self.assertNotIn("digest", values["image"], "a separate digest would override the updated tag")
        self.assertEqual(values["initContainers"][0]["name"], "velero-plugin-for-aws")
        self.assertEqual(values["initContainers"][0]["securityContext"]["capabilities"]["drop"], ["ALL"])
        apps = {d["metadata"]["name"]: d for d in yaml.safe_load_all((ROOT / "apps/velero.yml").read_text())}
        for name in ["velero", "velero-ui"]:
            chart = next(s for s in apps[name]["spec"]["sources"] if "chart" in s)
            self.assertEqual(chart["targetRevision"], "x")
            self.assertNotIn("image", chart["helm"]["valuesObject"])
        self.assertNotIn("initContainers", apps["velero"]["spec"]["sources"][1]["helm"]["valuesObject"])

    def test_cert_manager_excludes_numeric_builds_and_requires_arm64(self):
        updater = next(d for d in self.docs if d["kind"] == "ImageUpdater" and d["metadata"]["name"] == "cert-manager")
        images = updater["spec"]["applicationRefs"][0]["images"]
        self.assertEqual({i["alias"] for i in images}, {"controller", "webhook", "cainjector"})
        for image in images:
            settings = image["commonUpdateSettings"]
            self.assertEqual(settings["platforms"], ["linux/arm64"])
            pattern = settings["allowTags"].removeprefix("regexp:")
            for tag in ["v1.21.3", "v2.0.0", "v99.1.2"]:
                self.assertRegex(tag, pattern)
            for tag in ["608111629", "v608111629", "latest", "v1.21.3-rc.1", "v1.21.3-amd64"]:
                self.assertIsNone(re.match(pattern, tag))
        values = yaml.safe_load((ROOT / "image-updater/helm-values/cert-manager.yml").read_text())
        for image in [values["image"], values["webhook"]["image"], values["cainjector"]["image"]]:
            self.assertRegex(image["tag"], r"^v\d+\.\d+\.\d+$")

    def test_versioned_variants_allow_new_majors_but_exclude_prerelease_and_wrong_flavors(self):
        managed = {d["metadata"]["name"]: d for d in self.docs if d["kind"] == "ImageUpdater"}
        cases = [
            # Community migration is intentionally held on the validated 12.0 branch.
            ("seafile", "seafile", "12.0.14-arm", ["13.0.0-arm", "12.0.14", "12.0.14-rc1-arm", "12.0.14-amd64"]),
            ("seafile", "memcached", "99.0.0-alpine", ["99.0.0", "99.0.0-rc1-alpine"]),
            ("solver", "docker", "99.0.0-dind", ["99.0.0", "99.0.0-rc1-dind", "99.0.0-cli"]),
            ("track", "postgis", "99-3.10-alpine", ["99-3.10", "99-3.10-alpine-rc1"]),
            ("immich", "postgres", "99-vectorchord9.0.0-pgvectors8.0.0", ["99-alpine", "99-vectorchord9.0.0-pgvectors8.0.0-rc1"]),
        ]
        for app, alias, accepted, rejected in cases:
            image = next(i for i in managed[app]["spec"]["applicationRefs"][0]["images"] if i["alias"] == alias)
            pattern = image["commonUpdateSettings"]["allowTags"].removeprefix("regexp:")
            self.assertRegex(accepted, pattern)
            for tag in rejected:
                self.assertIsNone(re.match(pattern, tag))

    def test_helm_charts_track_latest_stable_except_vault(self):
        charts = {}
        for path in (ROOT / "apps").glob("*.yml"):
            for app in yaml.safe_load_all(path.read_text()):
                if not app or app["kind"] != "Application":
                    continue
                spec = app["spec"]
                for source in spec.get("sources", [spec.get("source", {})]):
                    if "chart" in source:
                        charts[app["metadata"]["name"]] = source["targetRevision"]
        self.assertEqual(charts.pop("vault"), "0.34.1")
        self.assertEqual(charts.pop("vault-secrets-operator"), "1.6.0")
        self.assertEqual(len(charts), 9)
        self.assertTrue(all(version == "x" for version in charts.values()))

    def test_bootstrap_reads_the_single_gitops_owned_declaration_source(self):
        code = (ROOT / "bootstrap/services/register_image_updaters.py").read_text()
        self.assertIn('"reviewed.yml", "deployed.yml", "helm.yml", "mail.yml"', code)
        self.assertIn('"HEAD:image-updater/" + filename', code)
        self.assertNotIn("HEAD:apps/{name}.yml", code)

    def test_bootstrap_accepts_each_declared_update_policy(self):
        def committed_source(args, **kwargs):
            return (ROOT / args[2].removeprefix("HEAD:")).read_text()

        with patch("register_image_updaters.subprocess.check_output", side_effect=committed_source):
            for name in ENABLED:
                self.assertEqual(declaration(name)["metadata"]["name"], name)
            for name in {"vault", "vault-backup", "vault-ui", "vault-secrets-operator"}:
                with self.assertRaises(RuntimeError):
                    declaration(name)

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
