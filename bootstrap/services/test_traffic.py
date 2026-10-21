import subprocess
import unittest

import yaml

from provision import ROOT


class TrafficTests(unittest.TestCase):
    def test_native_geoip_and_logs_are_preserved(self):
        code = (ROOT / "traffic/prepare-assets.mjs").read_text()
        self.assertIn("COPYFILE_EXCL", code)
        self.assertIn('openSync("/logs/all.log", "a"', code)
        self.assertNotIn("rmSync", code)
        self.assertNotIn("truncate", code)
        config = yaml.safe_load((ROOT / "traffic/aggregator_cm.yml").read_text())["data"]["goaccess.conf"]
        self.assertIn("anonymize-ip true", config)
        self.assertIn("geoip-database /logs/GeoLite2-ASN.mmdb", config)
        self.assertIn("geoip-database /logs/GeoLite2-City.mmdb", config)

    def test_workloads_are_pinned_and_do_not_get_kubernetes_credentials(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "traffic")], text=True)))
        for doc in docs:
            if doc["kind"] not in {"Deployment", "DaemonSet"}:
                continue
            pod = doc["spec"]["template"]["spec"]
            self.assertFalse(pod["automountServiceAccountToken"])
            for container in pod.get("initContainers", []) + pod["containers"]:
                self.assertIn("@sha256:", container["image"])
            if doc["kind"] == "Deployment":
                self.assertEqual(doc["spec"]["strategy"]["type"], "Recreate")
                host = next(v["hostPath"] for v in pod["volumes"] if "hostPath" in v)
                self.assertEqual(host, {"path": "/mnt/data/logs", "type": "DirectoryOrCreate"})
            else:
                self.assertTrue(pod["containers"][0]["volumeMounts"][0]["readOnly"])


if __name__ == "__main__":
    unittest.main()
