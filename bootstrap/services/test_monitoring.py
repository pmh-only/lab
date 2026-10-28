import json
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

    def test_scd41_dashboard_uses_existing_scrape_and_reports_missing_data(self):
        configs = {d["metadata"]["name"]: d for d in self.docs if d["kind"] == "ConfigMap"}
        deployment = next(d for d in self.docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "grafana")
        volume = next(v for v in deployment["spec"]["template"]["spec"]["volumes"] if v["name"] == "grafana-dashboards")
        dashboard = json.loads(configs[volume["configMap"]["name"]]["data"]["scd41.json"])
        self.assertEqual(dashboard["uid"], "scd41")
        self.assertFalse(dashboard["editable"])
        self.assertEqual(dashboard["refresh"], "15s")
        prom = yaml.safe_load(configs["prometheus-config"]["data"]["prometheus.yml"])
        job = next(j for j in prom["scrape_configs"] if j["job_name"] == "scd41")
        self.assertEqual(job["static_configs"][0]["targets"], ["pmhraspberry.tailscale.svc.cluster.local:9811"])
        instance = next(v for v in dashboard["templating"]["list"] if v["name"] == "instance")
        self.assertIn('label_values(up{', instance["query"])
        panels = dashboard["panels"]
        self.assertEqual(len(panels), 11)
        self.assertEqual(len({p["id"] for p in panels}), len(panels))
        cells = set()
        for panel in panels:
            grid = panel["gridPos"]
            self.assertLessEqual(grid["x"] + grid["w"], 24)
            for x in range(grid["x"], grid["x"] + grid["w"]):
                for y in range(grid["y"], grid["y"] + grid["h"]):
                    self.assertNotIn((x, y), cells)
                    cells.add((x, y))
            self.assertEqual(panel["datasource"]["uid"], "${datasource}")
            for target in panel["targets"]:
                self.assertIn('cluster="lab",job="scd41"', target["expr"])
                self.assertIn('instance=~"$instance"', target["expr"])
                self.assertNotIn("or vector(0)", target["expr"])
            if panel["id"] in {1, 2, 3, 7, 8, 9}:
                expr = panel["targets"][0]["expr"]
                self.assertIn("scd41_last_success_timestamp_seconds", expr)
                self.assertIn(" < 60", expr)
                self.assertIn("scd41_up", expr)
                self.assertIn(" == 1", expr)
            if panel["type"] == "stat":
                self.assertTrue(panel["targets"][0]["instant"])
                self.assertIn("noValue", panel["fieldConfig"]["defaults"])
            else:
                self.assertFalse(panel["fieldConfig"]["defaults"]["custom"]["spanNulls"])
        self.assertIn("rate(scd41_read_errors_total", panels[-1]["targets"][0]["expr"])

    def test_home_dashboard_is_provisioned_read_only_and_retained(self):
        configs = {d["metadata"]["name"]: d for d in self.docs if d["kind"] == "ConfigMap"}
        provider = yaml.safe_load(configs["grafana-dashboard-provider"]["data"]["dashboards.yaml"])["providers"][0]
        self.assertTrue(provider["disableDeletion"])
        self.assertFalse(provider["allowUiUpdates"])
        self.assertEqual(provider["options"]["path"], "/etc/grafana/dashboards")
        self.assertIn("default_home_dashboard_path = /etc/grafana/dashboards/lab-overview.json", configs["grafana-config"]["data"]["grafana.ini"])
        deployment = next(d for d in self.docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "grafana")
        pod = deployment["spec"]["template"]["spec"]
        mounts = {m["name"]: m for m in pod["containers"][0]["volumeMounts"]}
        for name in ["grafana-dashboard-provider", "grafana-dashboards"]:
            self.assertTrue(mounts[name]["readOnly"])
            self.assertNotIn("subPath", mounts[name])
        volume = next(v for v in pod["volumes"] if v["name"] == "grafana-dashboards")
        dashboard = json.loads(configs[volume["configMap"]["name"]]["data"]["lab-overview.json"])
        self.assertEqual(dashboard["uid"], "lab-overview")
        self.assertFalse(dashboard["editable"])
        self.assertEqual(dashboard["refresh"], "30s")
        panels = dashboard["panels"]
        self.assertEqual(len({p["id"] for p in panels}), len(panels))
        self.assertEqual(len(panels), 17)
        disk = next(p for p in panels if p["id"] == 17)
        self.assertEqual(disk["title"], "Disk capacity by filesystem")
        self.assertEqual([t["refId"] for t in disk["targets"]], ["A", "B", "C", "D"])
        for target in disk["targets"]:
            self.assertTrue(target["instant"])
            self.assertEqual(target["format"], "table")
            self.assertIn("nodename,mountpoint,device,fstype", target["expr"])
            self.assertNotIn('mountpoint="/"', target["expr"])
            self.assertIn('fstype!~"tmpfs|devtmpfs|overlay|squashfs|nsfs|fuse"', target["expr"])
        self.assertIn(" > 0", disk["targets"][3]["expr"])
        self.assertEqual(disk["transformations"][0]["id"], "merge")
        cells = set()
        for panel in panels:
            grid = panel["gridPos"]
            self.assertLessEqual(grid["x"] + grid["w"], 24)
            for x in range(grid["x"], grid["x"] + grid["w"]):
                for y in range(grid["y"], grid["y"] + grid["h"]):
                    self.assertNotIn((x, y), cells)
                    cells.add((x, y))
            self.assertEqual(panel["datasource"]["uid"], "${datasource}")
            for target in panel["targets"]:
                self.assertIn('cluster="lab"', target["expr"])
                self.assertNotIn("or vector(0)", target["expr"])
        namespace = next(v for v in dashboard["templating"]["list"] if v["name"] == "namespace")
        self.assertTrue(namespace["includeAll"])
        self.assertEqual(namespace["allValue"], ".*")


if __name__ == "__main__":
    unittest.main()
