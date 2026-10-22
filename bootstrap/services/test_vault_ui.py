import subprocess
import unittest

import yaml

from provision import ROOT


class VaultUITests(unittest.TestCase):
    def test_ui_route_authenticates_existing_tls_backend_without_managing_vault(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "vault_ui")], text=True)))
        self.assertEqual({d["kind"] for d in docs}, {"ConfigMap", "HTTPRoute", "BackendTLSPolicy"})
        route = next(d for d in docs if d["kind"] == "HTTPRoute")
        self.assertEqual(route["spec"]["hostnames"], ["vault.pmh.codes"])
        self.assertEqual(route["spec"]["rules"][0]["backendRefs"][0]["port"], 8200)
        tls = next(d for d in docs if d["kind"] == "BackendTLSPolicy")
        self.assertEqual(tls["spec"]["targetRefs"][0]["name"], "vault-ui")
        self.assertEqual(tls["spec"]["validation"]["hostname"], "vault.vault.svc.cluster.local")
        self.assertEqual(tls["spec"]["validation"]["caCertificateRefs"][0]["name"], "vault-ui-backend-ca")
        ca = next(d for d in docs if d["kind"] == "ConfigMap")["data"]["ca.crt"]
        self.assertIn("BEGIN CERTIFICATE", ca)
        self.assertNotIn("PRIVATE KEY", ca)
        app = yaml.safe_load((ROOT / "apps/vault-ui.yml").read_text())
        self.assertEqual(app["spec"]["source"]["path"], "vault_ui")
        vault = yaml.safe_load((ROOT / "apps/vault.yml").read_text())
        self.assertNotIn("automated", vault["spec"]["syncPolicy"])


if __name__ == "__main__":
    unittest.main()
