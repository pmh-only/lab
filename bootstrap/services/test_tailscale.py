import io
import json
import subprocess
import unittest
from unittest.mock import patch

import yaml

from provision import ROOT
from tailscale import access_token


class TailscaleTests(unittest.TestCase):
    def test_operator_uses_pinned_native_images_existing_vault_secret_and_no_api_proxy(self):
        apps = list(yaml.safe_load_all((ROOT / "apps/tailscale.yml").read_text()))
        operator = next(d for d in apps if d["metadata"]["name"] == "tailscale")
        sources = operator["spec"]["sources"]
        self.assertEqual(sources[0]["path"], "tailscale_auth")
        chart = next(s for s in sources if s.get("chart"))
        self.assertEqual(chart["targetRevision"], "1.104.2")
        values = chart["helm"]["valuesObject"]
        self.assertEqual(values["oauthSecretVolume"]["secret"]["secretName"], "operator-oauth")
        self.assertNotIn("oauth", values)
        self.assertEqual(values["operatorConfig"]["hostname"], "lab-operator")
        self.assertEqual(values["apiServerProxyConfig"], {"mode": "false", "allowImpersonation": "false"})
        for part in ["operatorConfig", "proxyConfig"]:
            self.assertTrue(values[part]["image"]["digest"].startswith("sha256:"))

    def test_secret_dependency_precedes_operator_without_connector_crd_cycle(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "tailscale_auth")], text=True)))
        self.assertEqual({d["kind"] for d in docs}, {"VaultAuth", "VaultStaticSecret", "ServiceAccount"})
        for d in docs:
            self.assertEqual(d["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "-2")
        secret = next(d for d in docs if d["kind"] == "VaultStaticSecret")
        self.assertEqual(secret["spec"]["path"], "tailscale/operator-oauth")
        self.assertEqual(secret["spec"]["rolloutRestartTargets"], [{"kind": "Deployment", "name": "operator"}])

    def test_old_remote_devices_are_not_fabricated_or_deployed_in_new_tailnet(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "tailscale_configs")], text=True)))
        self.assertEqual([d["kind"] for d in docs], ["Connector"])
        self.assertNotIn("namespace", docs[0]["metadata"])
        self.assertEqual(docs[0]["spec"]["tags"], ["tag:k8s"])
        self.assertEqual(docs[0]["spec"]["subnetRouter"]["advertiseRoutes"], ["10.0.0.0/8", "172.16.0.0/16", "172.17.0.0/16"])
        self.assertTrue((ROOT / "tailscale_configs/service.yml").is_file())

    def test_oauth_values_are_only_form_body_and_missing_scopes_are_rejected(self):
        credentials = {"client_id": "test-client", "client_secret": "private-test-secret"}
        data = {"access_token": "private-test-token", "scope": "devices:core auth_keys services"}
        with patch("tailscale.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(data).encode())) as call:
            self.assertEqual(access_token(credentials), "private-test-token")
            req = call.call_args.args[0]
            self.assertNotIn(credentials["client_secret"], req.full_url)
            self.assertIn(b"client_secret=private-test-secret", req.data)
        data["scope"] = "devices:core:read"
        with patch("tailscale.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(data).encode())):
            with self.assertRaises(RuntimeError):
                access_token(credentials)


if __name__ == "__main__":
    unittest.main()
