import subprocess
import unittest

import yaml

from provision import ROOT


class GatewayCertificateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "gateway")], text=True)))

    def test_original_certificate_is_rendered_with_all_current_gateway_ips(self):
        cert = next(d for d in self.docs if d["kind"] == "Certificate" and d["metadata"]["name"] == "gateway-tls-secret")
        self.assertEqual(set(cert["spec"]["ipAddresses"]), {"168.110.121.95", "138.2.112.39", "168.107.39.218"})
        self.assertEqual(cert["spec"]["secretName"], "gateway-tls-secret")
        self.assertEqual(cert["spec"]["issuerRef"]["name"], "letsencrypt")
        self.assertEqual(cert["spec"]["renewBefore"], "48h")
        self.assertEqual(cert["spec"]["secretTemplate"]["labels"]["edge.pmh.codes/reload"], "true")
        self.assertEqual(set(cert["spec"]["dnsNames"]), {
            "pmh.codes", "*.pmh.codes", "pmh.so", "*.pmh.so", "as218822.net", "not.ai.kr",
            "*.here.pmh.codes", "*.here.pmh.so", "*.s3.pmh.codes", "*.s3.pmh.so",
            "*.mc.pmh.codes", "*.mc.pmh.so", "*.a.certificate.for.pmh.codes",
        })

    def test_edge_mounts_the_single_original_certificate_without_migration_patches(self):
        certs = [d for d in self.docs if d["kind"] == "Certificate"]
        self.assertEqual(len(certs), 1)
        daemon = next(d for d in self.docs if d["kind"] == "DaemonSet")
        tls = next(v for v in daemon["spec"]["template"]["spec"]["volumes"] if v["name"] == "tls")
        self.assertEqual(tls["secret"]["secretName"], certs[0]["spec"]["secretName"])
        self.assertFalse((ROOT / "gateway/public-certificate.yml").exists())
        self.assertNotIn("patches", yaml.safe_load((ROOT / "gateway/kustomization.yml").read_text()))

    def test_ip_http01_and_all_dns_names_have_real_solvers(self):
        issuer = next(d for d in self.docs if d["kind"] == "ClusterIssuer")
        self.assertEqual(issuer["spec"]["acme"]["profile"], "shortlived")
        solvers = issuer["spec"]["acme"]["solvers"]
        self.assertEqual(set(solvers[0]["selector"]["dnsZones"]), {"as218822.net", "not.ai.kr", "pmh.so", "pmh.codes"})
        self.assertNotIn("cloudflare", solvers[0]["dns01"])
        http = next(s["http01"] for s in solvers if "http01" in s)
        self.assertNotIn("waitInsteadOfSelfCheck", http)
        self.assertEqual(http["gatewayHTTPRoute"]["serviceType"], "ClusterIP")
        self.assertEqual(http["gatewayHTTPRoute"]["parentRefs"][0]["sectionName"], "http")

    def test_http_acme_path_is_proxied_without_redirecting_ip_validation(self):
        config = next(d["data"]["nginx.conf"] for d in self.docs if d["kind"] == "ConfigMap")
        http = config.split("listen  80 default_server;", 1)[1].split("listen 443 ssl default_server;", 1)[0]
        acme = http.split("location ^~ /.well-known/acme-challenge/ {", 1)[1].split("}", 1)[0]
        self.assertIn("proxy_pass http://$envoy_gateway:80;", acme)
        self.assertNotIn("return 301", acme)
        self.assertIn("return 301 https://$host$request_uri;", http)
