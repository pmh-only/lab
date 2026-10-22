import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

import yaml

from guessaiword import configuration, DATABASE_URL, MODEL
from provision import ROOT


class GuessAIWordTests(unittest.TestCase):
    def test_native_properties_preserve_supplied_key_use_fresh_file_db_and_never_drop_schema(self):
        api_key = "sk-private-fixture-" + "x" * 32
        password = "y" * 64
        text = configuration(api_key, password)
        self.assertIn("guessaiword.ai.apikey=" + api_key, text)
        self.assertIn("spring.datasource.password=" + password, text)
        self.assertIn("spring.datasource.url=" + DATABASE_URL, text)
        self.assertIn("guessaiword.ai.model=" + MODEL, text)
        self.assertIn("spring.jpa.hibernate.ddl-auto=update", text)
        self.assertNotIn("create-drop", text)
        self.assertNotIn("jdbc:h2:mem:", text)
        self.assertIn("spring.h2.console.settings.web-allow-others=false", text)
        self.assertIn("classpath:/frontend/dist/", text)
        for invalid in ["sk-wrong\nnew.property=unsafe", "not-an-openai-key"]:
            with self.assertRaises(RuntimeError):
                configuration(invalid, password)

    def test_exclusive_configuration_and_retained_single_writer_storage(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "guessaiword")], text=True)))
        deployment = next(d for d in docs if d["kind"] == "Deployment")
        self.assertEqual(deployment["spec"]["strategy"]["type"], "Recreate")
        pod = deployment["spec"]["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertEqual(pod["nodeSelector"]["kubernetes.io/hostname"], "pmhoci")
        self.assertEqual(pod["securityContext"]["runAsUser"], 1000)
        container = pod["containers"][0]
        self.assertIn("@sha256:", container["image"])
        env = {e["name"]: e["value"] for e in container["env"]}
        self.assertEqual(env["SPRING_CONFIG_LOCATION"], "file:/app/config/application.properties")
        self.assertNotIn("ADDITIONAL", str(env))
        self.assertIn("/var/lib/guessaiword", [m["mountPath"] for m in container["volumeMounts"]])
        self.assertNotIn("/app", [m["mountPath"] for m in container["volumeMounts"]])
        pvc = next(d for d in docs if d["kind"] == "PersistentVolumeClaim")
        self.assertEqual(pvc["metadata"]["annotations"]["argocd.argoproj.io/sync-options"], "Prune=false")
        self.assertNotIn("volumeName", pvc["spec"])

    def test_public_route_preserves_native_game_auth_without_added_sso(self):
        docs = list(yaml.safe_load_all((ROOT / 'guessaiword/ingress.yml').read_text()))
        self.assertEqual({d['kind'] for d in docs}, {'HTTPRoute', 'EnvoyExtensionPolicy'})
        route = next(d for d in docs if d['kind'] == 'HTTPRoute')
        self.assertEqual(route['spec']['hostnames'], ['guess.pmh.codes'])
        self.assertEqual(route['metadata']['annotations']['argocd.argoproj.io/sync-wave'], '1')
        policy = next(d for d in docs if d['kind'] == 'EnvoyExtensionPolicy')
        code = policy['spec']['lua'][0]['inline']
        self.assertIn('^GAME_TOKEN=', code)
        self.assertIn('; Secure', code)
        self.assertNotIn('HttpOnly', code)
        self.assertIn('table.insert(cookies, value)', code)

    def test_runtime_archive_removes_old_config_but_preserves_business_code_and_stored_libs(self):
        with tempfile.TemporaryDirectory(prefix="guessaiword-test-", dir="/tmp/opencode" if Path("/tmp/opencode").is_dir() else None) as directory:
            root = Path(directory)
            source, prepared = root / "source.jar", root / "prepared.jar"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr('META-INF/MANIFEST.MF', 'Main-Class: native.Launcher\n')
                archive.writestr('BOOT-INF/classes/application.properties', 'old.compromised.fixture=not-real\n')
                archive.writestr('BOOT-INF/classes/native/App.class', b'native-class-fixture')
                entry = zipfile.ZipInfo('BOOT-INF/lib/native.jar')
                entry.compress_type = zipfile.ZIP_STORED
                archive.writestr(entry, b'unchanged-nested-library')
            script = (ROOT / 'guessaiword/prepare-jar.py').read_text().replace("Path('/source/app.jar')", f"Path({str(source)!r})").replace("Path('/prepared/app.jar')", f"Path({str(prepared)!r})")
            exec(compile(script, 'prepare-jar.py', 'exec'), {})
            self.assertFalse(source.exists())
            with zipfile.ZipFile(prepared) as archive:
                self.assertNotIn('BOOT-INF/classes/application.properties', archive.namelist())
                self.assertEqual(archive.read('BOOT-INF/classes/native/App.class'), b'native-class-fixture')
                self.assertEqual(archive.read('BOOT-INF/lib/native.jar'), b'unchanged-nested-library')
                self.assertEqual(archive.getinfo('BOOT-INF/lib/native.jar').compress_type, zipfile.ZIP_STORED)


if __name__ == "__main__":
    unittest.main()
