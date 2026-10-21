"""Safety checks for the temporary, explicitly untrusted public edge."""

from pathlib import Path
import subprocess
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


class BootstrapEdgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rendered = subprocess.check_output(["kubectl", "kustomize", str(ROOT / "gateway/bootstrap")], text=True)
        cls.documents = list(yaml.safe_load_all(rendered))
        cls.resources = {document["kind"]: document for document in cls.documents}
        cls.resources["Certificate"] = next(d for d in cls.documents if d["kind"] == "Certificate" and d["metadata"]["name"] == "gateway-bootstrap-tls")
        cls.config = cls.resources["ConfigMap"]["data"]["nginx.conf"]

    def test_only_bootstrap_resources_are_deployed(self):
        self.assertEqual(set(self.resources), {"ConfigMap", "Service", "DaemonSet", "Certificate", "Issuer"})
        self.assertTrue(all(d["metadata"]["namespace"] == "gateway" for d in self.documents))
        self.assertEqual(self.resources["Issuer"]["spec"], {"selfSigned": {}})

    def test_new_certificate_uses_confirmed_addresses_and_fresh_key(self):
        certificate = self.resources["Certificate"]["spec"]
        self.assertEqual(set(certificate["ipAddresses"]), {"138.2.112.39", "168.110.121.95"})
        self.assertEqual(certificate["issuerRef"]["name"], "gateway-bootstrap")
        self.assertEqual(certificate["privateKey"]["rotationPolicy"], "Always")
        self.assertNotIn("not.ai.kr", certificate["dnsNames"])

    def test_staging_issuance_is_isolated_from_served_tls(self):
        certificate = next(d["spec"] for d in self.documents if d["kind"] == "Certificate" and d["metadata"]["name"] == "gateway-pmh-codes-staging")
        self.assertEqual(certificate["issuerRef"]["name"], "letsencrypt-staging")
        self.assertEqual(set(certificate["dnsNames"]), {"pmh.codes", "*.pmh.codes"})
        self.assertNotIn("ipAddresses", certificate)
        self.assertEqual(certificate["privateKey"]["rotationPolicy"], "Always")
        volumes = self.resources["DaemonSet"]["spec"]["template"]["spec"]["volumes"]
        self.assertNotIn(certificate["secretName"], {v["secret"]["secretName"] for v in volumes if "secret" in v})

    def test_no_ssh_ech_or_hsts_dependency(self):
        self.assertNotIn("listen 22", self.config)
        self.assertNotIn("ssl_ech_file", self.config)
        self.assertNotIn("Strict-Transport-Security", self.config)
        spec = self.resources["DaemonSet"]["spec"]["template"]["spec"]
        self.assertFalse(spec["automountServiceAccountToken"])
        self.assertNotIn("initContainers", spec)
        self.assertEqual({v["secret"]["secretName"] for v in spec["volumes"] if "secret" in v}, {"gateway-bootstrap-tls"})

    def test_management_is_blocked_and_client_headers_are_overwritten(self):
        self.assertIn("names.pmh.codes 1;", self.config)
        self.assertEqual(self.config.count("if ($private_management_host) { return 403; }"), 2)
        self.assertIn("proxy_set_header X-Forwarded-For $remote_addr;", self.config)
        self.assertIn("proxy_set_header X-Real-IP $remote_addr;", self.config)
        self.assertNotIn("$proxy_add_x_forwarded_for", self.config)

    def test_rollout_is_node_limited_and_image_pinned(self):
        daemonset = self.resources["DaemonSet"]["spec"]
        self.assertEqual(daemonset["updateStrategy"]["rollingUpdate"], {"maxUnavailable": 1, "maxSurge": 0})
        pod = daemonset["template"]["spec"]
        self.assertTrue(pod["hostNetwork"])
        expressions = pod["affinity"]["nodeAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]["nodeSelectorTerms"][0]["matchExpressions"]
        self.assertEqual(set(expressions[0]["values"]), {"pmhoci", "pmhoci2"})
        self.assertIn("@sha256:", pod["containers"][0]["image"])
        self.assertEqual({p["containerPort"] for p in pod["containers"][0]["ports"]}, {80, 443})

    def test_certificate_changes_only_restart_opted_in_edge(self):
        annotations = self.resources["DaemonSet"]["metadata"]["annotations"]
        self.assertEqual(annotations["secret.reloader.stakater.com/reload"], "gateway-bootstrap-tls")
        labels = self.resources["Certificate"]["spec"]["secretTemplate"]["labels"]
        self.assertEqual(labels, {"edge.pmh.codes/reload": "true"})
        app = yaml.safe_load((ROOT / "apps/gateway-reloader.yml").read_text())
        self.assertEqual(app["spec"]["destination"]["namespace"], "gateway")
        self.assertEqual(app["spec"]["source"]["targetRevision"], "2.2.18")
        values = app["spec"]["source"]["helm"]["valuesObject"]
        self.assertTrue(values["image"]["digest"].startswith("sha256:"))
        self.assertFalse(values["reloader"]["watchGlobally"])
        self.assertFalse(values["reloader"]["autoReloadAll"])
        self.assertTrue(values["reloader"]["ignoreConfigMaps"])
        self.assertEqual(values["reloader"]["reloadStrategy"], "annotations")

    def test_argocd_ignores_only_the_reloader_annotation(self):
        app = next(d for d in yaml.safe_load_all((ROOT / "apps/gateway.yml").read_text()) if d["kind"] == "Application")
        self.assertEqual(app["spec"]["ignoreDifferences"], [{
            "group": "apps", "kind": "DaemonSet", "namespace": "gateway", "name": "gateway-nginx",
            "jsonPointers": ["/spec/template/metadata/annotations/reloader.stakater.com~1last-reloaded-from"],
        }])
        self.assertIn("RespectIgnoreDifferences=true", app["spec"]["syncPolicy"]["syncOptions"])


if __name__ == "__main__":
    unittest.main()
