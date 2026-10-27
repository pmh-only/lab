import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

import yaml

from provision import ROOT, PROFILES


def initializer():
    spec = importlib.util.spec_from_file_location("seafile_initialize", ROOT / "seafile/initialize.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SeafileTests(unittest.TestCase):
    def setUp(self):
        self.path_patch = patch.object(sys, "path", [str(ROOT / "seafile")] + sys.path)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)

    def test_community_ccnet_config_uses_existing_app_identity_and_preserves_custom_config(self):
        from configparser import ConfigParser
        module = initializer()
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            (data / "conf").mkdir()
            (data / "conf/seafile.conf").write_text(
                "[database]\ntype=mysql\nhost=mysql.example\nport=3306\nuser=seafile\npassword=test-only%literal\ndb_name=seafile_db\n"
            )
            with patch.dict(os.environ, {"SEAFILE_MYSQL_DB_CCNET_DB_NAME": "ccnet_db"}):
                module.prepare_community_ccnet_config(data)
            parser = ConfigParser(interpolation=None)
            parser.optionxform = str
            parser.read(data / "conf/ccnet.conf")
            self.assertEqual(parser["Database"]["USER"], "seafile")
            self.assertEqual(parser["Database"]["PASSWD"], "test-only%literal")
            self.assertEqual(parser["Database"]["DB"], "ccnet_db")
            existing = (data / "conf/ccnet.conf").read_text()
            module.prepare_community_ccnet_config(data)
            self.assertEqual((data / "conf/ccnet.conf").read_text(), existing)

    def test_community_disables_pro_event_features_but_preserves_database(self):
        from configparser import ConfigParser
        module = initializer()
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            (data / "conf").mkdir()
            path = data / "conf/seafevents.conf"
            path.write_text("[DATABASE]\nname=seahub_db\n[INDEX FILES]\nenabled=true\nes_host=elasticsearch\n[AUDIT]\nenabled=true\n[STATISTICS]\nenabled=true\n")
            module.prepare_community_events_config(data)
            config = ConfigParser(interpolation=None)
            config.read(path)
            self.assertFalse(config.getboolean("INDEX FILES", "enabled"))
            self.assertFalse(config.getboolean("AUDIT", "enabled"))
            self.assertEqual(config["INDEX FILES"]["es_host"], "elasticsearch")
            self.assertEqual(config["DATABASE"]["name"], "seahub_db")
            self.assertTrue(config.getboolean("STATISTICS", "enabled"))

    def test_server_and_initializers_use_community_not_pro(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "seafile")], text=True)))
        deployment = next(d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "seafile")
        pod = deployment["spec"]["template"]["spec"]
        for container in pod["initContainers"] + pod["containers"]:
            self.assertRegex(container["image"], r"^seafileltd/seafile-mc:12\.0\.[0-9]+-arm$")
        search = next(d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "elasticsearch")
        self.assertEqual(search["spec"]["replicas"], 0)
        self.assertTrue(any(d["kind"] == "PersistentVolumeClaim" and d["metadata"]["name"] == "seafile-search" for d in docs))

    def test_branding_is_immutable_and_preserves_unrelated_customizations(self):
        module = initializer()
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            (data / "conf").mkdir()
            integration = ROOT / "seafile/branding"
            unrelated = data / "seahub-data/custom/existing.css"
            unrelated.parent.mkdir(parents=True)
            unrelated.write_text("/* operator customization */")
            first = module.install_branding(data, integration)
            second = module.install_branding(data, integration)
            self.assertEqual(first, second)
            self.assertEqual(unrelated.read_text(), "/* operator customization */")
            for key in ("css", "logo", "favicon"):
                self.assertTrue((data / "seahub-data" / first[key]).is_file())
            css_asset = data / "seahub-data" / first["css"]
            css_asset.write_text("unmanaged content at a managed asset path")
            with self.assertRaisesRegex(RuntimeError, "Existing brand asset differs"):
                module.install_branding(data, integration)
            self.assertEqual(css_asset.read_text(), "unmanaged content at a managed asset path")

    def test_branding_settings_use_native_hooks_without_changing_authentication(self):
        module = initializer()
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            (data / "conf").mkdir()
            manifest = module.install_branding(data, ROOT / "seafile/branding")
            source = data / "conf/seahub_lab.py"
            source.write_text((ROOT / "seafile/seahub_lab.py").read_text())
            spec = importlib.util.spec_from_file_location("branded_seahub_lab", source)
            settings = importlib.util.module_from_spec(spec)
            with patch.dict(os.environ, {"OAUTH_CLIENT_SECRET": "test-only"}):
                spec.loader.exec_module(settings)
            self.assertEqual(settings.SITE_NAME, "PMH Drive")
            self.assertEqual(settings.BRANDING_CSS, manifest["css"])
            self.assertEqual(settings.LOGO_PATH, manifest["logo"])
            self.assertEqual(settings.FAVICON_PATH, manifest["favicon"])
            self.assertEqual(settings.OAUTH_PROVIDER, "authentik")
            self.assertIn("seahub_discord_quota.DiscordQuotaMiddleware", settings.EXTRA_MIDDLEWARE)
            self.assertFalse(hasattr(settings, "ENABLED_ROLE_PERMISSIONS"))

    def test_unmanaged_brand_manifest_is_not_overwritten(self):
        module = initializer()
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            (data / "conf").mkdir()
            manifest = data / "conf/pmh-drive-brand.json"
            manifest.write_text('{"managed_by": "operator"}')
            with self.assertRaisesRegex(RuntimeError, "Unmanaged Seafile brand manifest"):
                module.install_branding(data, ROOT / "seafile/branding")
            self.assertEqual(manifest.read_text(), '{"managed_by": "operator"}')

    def test_branding_keeps_native_controls_and_assets_self_contained(self):
        css = (ROOT / "seafile/branding/theme.css").read_text()
        self.assertNotIn("@import", css)
        self.assertNotIn("display: none", css)
        self.assertNotIn("http", css)
        self.assertIn(":focus-visible", css)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("forced-colors", css)
        self.assertIn(".side-panel:has(.side-nav)", css)
        for name in ("logo.svg", "icon.svg"):
            root = ET.fromstring((ROOT / "seafile/branding" / name).read_text())
            self.assertFalse(any(element.tag.endswith("script") for element in root.iter()))

    def test_discord_quota_uses_native_per_user_limit_without_changing_default_quota(self):
        with patch.dict(os.environ, {"OAUTH_CLIENT_SECRET": "test-only"}):
            spec = importlib.util.spec_from_file_location("seahub_lab", ROOT / "seafile/seahub_lab.py")
            settings = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(settings)
        self.assertIn("seafile", settings.OAUTH_SCOPE)
        self.assertEqual(settings.OAUTH_ATTRIBUTE_MAP["seafile_role"], (False, "role"))
        self.assertIn("seahub_discord_quota.DiscordQuotaMiddleware", settings.EXTRA_MIDDLEWARE)
        self.assertFalse(hasattr(settings, "ENABLED_ROLE_PERMISSIONS"))
        # Native Seahub removes conf from sys.path before resolving middleware.
        # Loading settings must already have cached this module for Django.
        self.assertIn("seahub_discord_quota", sys.modules)
        spec = importlib.util.spec_from_file_location("seahub_custom_functions", ROOT / "seafile/seahub_custom_functions.py")
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        quota = types.SimpleNamespace(mark_discord_login=Mock())
        with patch.dict("sys.modules", {"seahub_discord_quota": quota}):
            self.assertEqual(hook.custom_get_user_role("discord_10gb"), "default")
        quota.mark_discord_login.assert_called_once_with()
        for invalid in ("admin", "default", "", None):
            with self.subTest(role=invalid), self.assertRaises(ValueError):
                hook.custom_get_user_role(invalid)

    def test_notification_logs_use_the_existing_shared_mount_without_nested_subpaths(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "seafile")], text=True)))
        deployment = next(d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "seafile-noti")
        pod = deployment["spec"]["template"]["spec"]
        self.assertEqual(pod["nodeSelector"], {"kubernetes.io/hostname": "pmhoci"})
        self.assertEqual(pod["containers"][0]["volumeMounts"], [{"mountPath": "/shared", "name": "seafile-noti-storage"}])
        self.assertEqual(pod["initContainers"][0]["command"], ["sh", "-ec", "mkdir -p /shared/seafile/logs"])
        self.assertEqual(pod["initContainers"][0]["image"], pod["containers"][0]["image"])
        self.assertEqual(pod["volumes"][0]["hostPath"], {"path": "/mnt/data/seafile-noti", "type": "DirectoryOrCreate"})
        self.assertEqual(deployment["spec"]["strategy"]["type"], "Recreate")

    def test_mysql_sha2_plugin_is_pinned_without_weaker_server_authentication(self):
        script = (ROOT / "seafile/prepare_mysql_plugins.py").read_text()
        self.assertIn("ead7fdf6f5fc79a4809db03889763791190973591b872a93c063f5109abfe0ff", script)
        self.assertIn("hashlib.sha256(archive).hexdigest() != SHA256", script)
        self.assertIn("caching_sha2_password.so", script)
        self.assertNotIn("mysql_native_password", script)
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "seafile")], text=True)))
        pod = next(d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "seafile")["spec"]["template"]["spec"]
        self.assertEqual(pod["initContainers"][0]["name"], "mysql-client-plugins")
        self.assertNotIn("env", pod["initContainers"][0])
        env = {e["name"]: e for e in pod["containers"][0]["env"]}
        self.assertEqual(env["MARIADB_PLUGIN_DIR"]["value"], "/run/mariadb-client-plugins")

    def test_no_root_credentials_and_all_images_are_pinned(self):
        self.assertNotIn("DB_ROOT_PASSWD", PROFILES["seafile"][1])
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "seafile")], text=True)))
        waves = {d["metadata"]["name"]: int(d["metadata"].get("annotations", {}).get("argocd.argoproj.io/sync-wave", "0")) for d in docs if d["kind"] == "Deployment"}
        self.assertGreater(waves["seafile-sdoc"], waves["seafile"])
        self.assertGreater(waves["seafile-noti"], waves["seafile"])
        for deployment in [d for d in docs if d["kind"] == "Deployment"]:
            pod = deployment["spec"]["template"]["spec"]
            self.assertFalse(pod["automountServiceAccountToken"])
            for container in pod.get("initContainers", []) + pod["containers"]:
                self.assertRegex(container["image"], r"(?:@sha256:[a-f0-9]{64}|:[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.]+)?)$")
                self.assertNotIn("DB_ROOT_PASSWD", [e["name"] for e in container.get("env", [])])
            if deployment["metadata"]["name"] != "memcached":
                self.assertEqual(deployment["spec"]["strategy"]["type"], "Recreate")

    def test_unmanaged_existing_data_is_never_reinitialized(self):
        module = initializer()
        with tempfile.TemporaryDirectory() as directory:
            module.DATA = Path(directory)
            module.MARKER = module.DATA / ".lab-native-bootstrap-v1"
            (module.DATA / "seafile-data").mkdir()
            with self.assertRaisesRegex(RuntimeError, "refusing reinitialization"):
                module.initialize()

    def test_native_existing_database_flag_and_repeat_safety(self):
        module = initializer()
        with tempfile.TemporaryDirectory() as directory:
            module.DATA = Path(directory) / "data"
            module.MARKER = module.DATA / ".lab-native-bootstrap-v1"
            module.INTEGRATION = Path(directory) / "integration"
            module.INTEGRATION.mkdir()
            (module.INTEGRATION / "seahub_lab.py").write_text("# managed non-secret integration\n")
            (module.INTEGRATION / "seahub_custom_functions.py").write_text(
                '\"\"\"GitOps-managed Seahub OAuth role hook; test fixture.\"\"\"\n'
            )
            (module.INTEGRATION / "seahub_discord_quota.py").write_bytes(
                (ROOT / "seafile/seahub_discord_quota.py").read_bytes()
            )
            for name in ("theme.css", "logo.svg", "icon.svg"):
                (module.INTEGRATION / name).write_bytes((ROOT / "seafile/branding" / name).read_bytes())
            upstream_dir = Path(directory) / "upstream"
            upstream_dir.mkdir()
            (upstream_dir / "setup-seafile-mysql.py").write_text("def main():\n    seahub_config.do_syncdb()\n    db_config.root_conn.close()\n")
            upstream = types.SimpleNamespace(call=Mock(), get_script=lambda name: str(upstream_dir / name), get_install_dir=lambda: str(upstream_dir))

            def native_setup():
                upstream.call(str(upstream_dir / "setup-seafile-mysql.sh") + " auto -n seafile", env={"MYSQL_USER": "seafile"})
                (module.DATA / "conf").mkdir()
                (module.DATA / "conf/seafile.conf").write_text("[database]\nuser=seafile\n")
                (module.DATA / "conf/seahub_settings.py").write_text("# native settings\n")
                (module.DATA / "seafile-data").mkdir()
                (module.DATA / "seafile-data/current_version").write_text("12.0.14")

            upstream.init_seafile_server = Mock(side_effect=native_setup)
            with patch.dict("sys.modules", {"bootstrap": upstream}), patch.dict(os.environ, {"SEAFILE_VERSION": "12.0.14"}), patch.object(module, "native_schema_complete", return_value=False), patch.object(module.subprocess, "run", return_value=Mock(returncode=0)) as run:
                module.initialize()
                self.assertIn("--use-existing-db 1", run.call_args.args[0])
                self.assertNotIn("MYSQL_ROOT_PASSWD", run.call_args.kwargs["env"])
                self.assertEqual(run.call_args.kwargs["env"]["LAB_SEAFILE_NATIVE_SCHEMA_COMPLETE"], "false")
                patched = (upstream_dir / "setup-seafile-mysql.py").read_text()
                self.assertIn('if os.environ.get("LAB_SEAFILE_NATIVE_SCHEMA_COMPLETE") != "true":', patched)
                self.assertIn("if db_config.root_conn:", patched)
                original = (module.DATA / "conf/seahub_settings.py").read_text()
                module.initialize()
                upstream.init_seafile_server.assert_called_once()
                self.assertEqual((module.DATA / "conf/seahub_settings.py").read_text(), original)
                custom_hook = module.DATA / "conf/seahub_custom_functions.py"
                custom_hook.write_text("# unrelated operator customization\n")
                with self.assertRaisesRegex(RuntimeError, "Unmanaged Seahub custom functions"):
                    module.initialize()
                self.assertEqual(custom_hook.read_text(), "# unrelated operator customization\n")


if __name__ == "__main__":
    unittest.main()
