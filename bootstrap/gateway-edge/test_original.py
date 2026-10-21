"""The active gateway must use the user's original NGINX configuration."""

from pathlib import Path
import subprocess
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "b45d1cf072c9b58c85daf7f0afc1ece672ad7f7e"


class OriginalGatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = list(yaml.safe_load_all(subprocess.check_output(["git", "show", BASELINE + ":gateway/nginx.yml"], cwd=ROOT, text=True)))
        cls.rendered = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "gateway")], text=True)))

    def test_entire_original_nginx_configuration_is_preserved(self):
        original = next(d for d in self.original if d["kind"] == "ConfigMap")
        current = next(d for d in self.rendered if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "gateway-nginx-config")
        self.assertEqual(current["data"], original["data"])

    def test_original_service_ports_and_address_are_preserved(self):
        original = next(d for d in self.original if d["kind"] == "Service")
        current = next(d for d in self.rendered if d["kind"] == "Service" and d["metadata"]["name"] == "gateway-nginx")
        self.assertEqual(current["spec"], original["spec"])

    def test_original_daemonset_except_fresh_certificate_reference(self):
        original = next(d for d in self.original if d["kind"] == "DaemonSet")["spec"]
        current = next(d for d in self.rendered if d["kind"] == "DaemonSet")["spec"]
        original["template"]["spec"]["volumes"][0]["secret"]["secretName"] = "gateway-pmh-codes-tls"
        # Kustomize resolves the existing pinned image, as it did before bootstrap.
        image = current["template"]["spec"]["containers"][0]["image"]
        self.assertIn("@sha256:", image)
        original["template"]["spec"]["containers"][0]["image"] = image
        self.assertEqual(current, original)

    def test_original_envoy_resources_are_in_the_same_application(self):
        kinds = {d["kind"] for d in self.rendered}
        self.assertTrue({"Gateway", "GatewayClass", "EnvoyProxy", "BackendTrafficPolicy"}.issubset(kinds))
        app = next(d for d in yaml.safe_load_all((ROOT / "apps/gateway.yml").read_text()) if d["kind"] == "Application")
        self.assertEqual(app["spec"]["source"]["path"], "gateway")
        self.assertFalse((ROOT / "gateway/bootstrap/nginx.conf").exists())

    def test_old_sealed_secrets_and_retired_certificate_ips_are_not_deployed(self):
        self.assertFalse(any(d["kind"] == "SealedSecret" for d in self.rendered))
        certificates = [d for d in self.rendered if d["kind"] == "Certificate"]
        self.assertEqual(len(certificates), 1)
        self.assertEqual(certificates[0]["spec"]["secretName"], "gateway-pmh-codes-tls")
        self.assertNotIn("ipAddresses", certificates[0]["spec"])


if __name__ == "__main__":
    unittest.main()
