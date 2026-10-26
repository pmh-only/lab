import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import yaml

from provision import ROOT, PROFILES


def initializer():
    spec = importlib.util.spec_from_file_location("seafile_initialize", ROOT / "seafile/initialize.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SeafileTests(unittest.TestCase):
    def test_notification_logs_use_the_existing_shared_mount_without_nested_subpaths(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "seafile")], text=True)))
        deployment = next(d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "seafile-noti")
        pod = deployment["spec"]["template"]["spec"]
        self.assertEqual(pod["nodeSelector"], {"kubernetes.io/hostname": "pmhoci"})
        self.assertEqual(pod["containers"][0]["volumeMounts"], [{"mountPath": "/shared", "name": "seafile-noti-storage"}])
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
                self.assertIn("@sha256:", container["image"])
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


if __name__ == "__main__":
    unittest.main()
