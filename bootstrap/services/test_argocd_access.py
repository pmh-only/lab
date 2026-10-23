import subprocess
import unittest

import yaml

from provision import ROOT


class ArgoAccessTests(unittest.TestCase):
    def test_fresh_native_server_certificate_and_verified_tls_route(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "argocd-access")], text=True)))
        certificate = next(d for d in docs if d["kind"] == "Certificate")
        self.assertEqual(certificate["spec"]["secretName"], "argocd-server-tls")
        self.assertEqual(certificate["spec"]["dnsNames"], ["argo.pmh.codes"])
        route = next(d for d in docs if d["kind"] == "HTTPRoute")
        self.assertEqual(route["spec"]["hostnames"], ["argo.pmh.codes"])
        self.assertEqual(route["spec"]["rules"][0]["backendRefs"][0]["port"], 443)
        tls = next(d for d in docs if d["kind"] == "BackendTLSPolicy")
        self.assertEqual(tls["spec"]["validation"], {"hostname": "argo.pmh.codes", "wellKnownCACertificates": "System"})
        self.assertEqual(route["metadata"]["annotations"], tls["metadata"]["annotations"])
        self.assertFalse(any(d["kind"] in {"Deployment", "Secret", "SecurityPolicy"} for d in docs))

    def test_native_auth_is_not_disabled_and_admin_ui_is_not_tracked(self):
        bootstrap = (ROOT / "bootstrap/argocd/kustomization.yml").read_text()
        self.assertIn("url: https://argo.pmh.codes", bootstrap)
        self.assertNotIn("server.insecure: true", bootstrap)
        self.assertNotIn("users.anonymous.enabled: true", bootstrap)
        nginx = next(yaml.safe_load_all((ROOT / "gateway/nginx.yml").read_text()))["data"]["nginx.conf"]
        self.assertIn('argo.pmh.codes       "";', nginx)
