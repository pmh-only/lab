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


if __name__ == "__main__":
    unittest.main()
