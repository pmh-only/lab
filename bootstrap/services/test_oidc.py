import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import yaml

from oidc import provision_client
from provision import ROOT


DECLARATIONS = json.loads(Path(__file__).with_name("oidc.json").read_text())


class OIDCTests(unittest.TestCase):
    def test_public_client_ids_match_existing_security_policies(self):
        for slug, declaration in DECLARATIONS.items():
            if slug == "remote":
                docs = list(yaml.safe_load_all((ROOT / "remote/deployment.yml").read_text()))
                server = next(d for d in docs if d["metadata"]["name"] == "remote-guacamole")
                env = server["spec"]["template"]["spec"]["containers"][0]["env"]
                actual = {e["name"]: e["value"] for e in env if "value" in e}
                self.assertEqual(actual["OPENID_CLIENT_ID"], declaration["clientID"])
                self.assertEqual(actual["OPENID_REDIRECT_URI"], declaration["redirectURI"])
                self.assertTrue(declaration["publicClient"])
                self.assertEqual(declaration["grantTypes"], ["implicit"])
                continue
            if slug == "stmt":
                docs = list(yaml.safe_load_all((ROOT / "stmt/deployment.yml").read_text()))
                env = docs[0]["spec"]["template"]["spec"]["containers"][0]["env"]
                actual = next(e["value"] for e in env if e["name"] == "OIDC_CLIENT_ID")
                self.assertEqual(actual, declaration["clientID"])
                self.assertEqual(declaration["redirectURI"], "https://stmt.pmh.codes/auth/callback")
                continue
            directory = "pdf_configs" if slug == "pdf" else slug
            docs = list(yaml.safe_load_all((ROOT / directory / "ingress.yml").read_text()))
            policy = next(d["spec"]["oidc"] for d in docs if d["kind"] == "SecurityPolicy")
            self.assertEqual(policy["clientID"], declaration["clientID"])
            self.assertEqual(policy["provider"]["issuer"], "https://auth.pmh.codes/application/o/" + slug + "/")
            self.assertTrue(declaration["redirectURI"].endswith("/oauth2/callback"))

    def test_existing_client_is_not_rotated(self):
        desired = DECLARATIONS["go"]
        secret = "new-placeholder-" * 5
        provider = {"pk": 42, "name": "lab bootstrap: go", "client_id": desired["clientID"],
                    "client_secret": secret, "issuer_mode": "per_provider", "redirect_uris": [
                        {"matching_mode": "strict", "url": desired["redirectURI"], "redirect_uri_type": "authorization"}]}
        api, vault = Mock(), Mock()
        api.list.return_value = [provider]
        api.request.return_value = {"provider": 42}
        vault.get.return_value = {"client-secret": secret}
        discovery = {"issuer": "https://auth.pmh.codes/application/o/go/"}
        with patch("oidc.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(discovery).encode())):
            provision_client(vault, api, "go", desired)
        vault.create.assert_not_called()
        api.request.assert_called_once_with("core/applications/go/", missing_ok=True)

    def test_unrelated_existing_provider_is_not_taken_over(self):
        api, vault = Mock(), Mock()
        api.list.return_value = [{"client_id": DECLARATIONS["go"]["clientID"], "name": "user-managed"}]
        vault.get.return_value = None
        with self.assertRaises(RuntimeError):
            provision_client(vault, api, "go", DECLARATIONS["go"])
        vault.create.assert_not_called()
        api.request.assert_not_called()

    def test_native_public_client_does_not_fabricate_a_client_secret(self):
        desired = DECLARATIONS["remote"]
        provider = {"pk": 43, "name": "lab bootstrap: remote", "client_id": desired["clientID"],
                    "client_type": "public", "issuer_mode": "per_provider", "grant_types": ["implicit"],
                    "sub_mode": "user_username", "redirect_uris": [
                        {"matching_mode": "strict", "url": desired["redirectURI"], "redirect_uri_type": "authorization"}]}
        api, vault = Mock(), Mock()
        api.list.return_value = [provider]
        api.request.return_value = {"provider": 43}
        discovery = {"issuer": "https://auth.pmh.codes/application/o/remote/"}
        with patch("oidc.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(discovery).encode())):
            provision_client(vault, api, "remote", desired)
        vault.get.assert_not_called()
        vault.create.assert_not_called()
        vault.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
