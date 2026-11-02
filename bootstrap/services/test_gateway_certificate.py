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
        previous = yaml.safe_load((ROOT / "gateway/public-certificate.yml").read_text())
        self.assertEqual(set(cert["spec"]["dnsNames"]), set(previous["spec"]["dnsNames"]))

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
