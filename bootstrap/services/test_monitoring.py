import subprocess
import unittest

import yaml

from provision import ROOT


class MonitoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "monitoring")], text=True)))

    def test_persistent_state_is_retained_and_writers_do_not_overlap(self):
        for doc in self.docs:
            if doc["kind"] == "PersistentVolumeClaim":
                self.assertEqual(doc["metadata"]["annotations"]["argocd.argoproj.io/sync-options"], "Prune=false")
            if doc["kind"] == "Deployment" and doc["metadata"]["name"] in {"grafana", "thanos-store", "thanos-compactor"}:
                self.assertEqual(doc["spec"]["strategy"]["type"], "Recreate")
        prom = next(d for d in self.docs if d["kind"] == "StatefulSet")
        init = prom["spec"]["template"]["spec"]["initContainers"][0]
        self.assertNotIn("rm ", " ".join(init["command"]))
        self.assertIn("@sha256:", init["image"])

    def test_fresh_grafana_admin_and_encryption_preserve_anonymous_viewer(self):
        grafana = next(d for d in self.docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "grafana")
        env = {e["name"]: e for e in grafana["spec"]["template"]["spec"]["containers"][0]["env"]}
        for key in ["GF_SECURITY_ADMIN_PASSWORD", "GF_SECURITY_SECRET_KEY", "GF_RENDERING_RENDERER_TOKEN"]:
            self.assertEqual(env[key]["valueFrom"]["secretKeyRef"], {"name": "monitoring-secret", "key": key})
        ini = next(d for d in self.docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "grafana-config")["data"]["grafana.ini"]
        self.assertIn("[auth.anonymous]\nenabled = true", ini)
        self.assertIn("org_role = Viewer", ini)

    def test_prometheus_discovery_does_not_conflict_and_thanos_is_pinned(self):
        config = next(d for d in self.docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "prometheus-config")
        prom = yaml.safe_load(config["data"]["prometheus.yml"])
        for job in prom["scrape_configs"]:
            for sd in job.get("kubernetes_sd_configs", []):
                namespace = sd.get("namespaces", {})
                self.assertFalse(namespace.get("own_namespace") and namespace.get("names"))
        for doc in self.docs:
            if doc["kind"] not in {"Deployment", "StatefulSet", "DaemonSet"}:
                continue
            for container in doc["spec"]["template"]["spec"]["containers"]:
                self.assertIn("@sha256:", container["image"])


if __name__ == "__main__":
    unittest.main()
