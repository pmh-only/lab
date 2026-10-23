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
            if slug == "rustfs":
                doc = next(yaml.safe_load_all((ROOT / "minio/minio.yml").read_text()))
                env = {e["name"]: e for e in doc["spec"]["template"]["spec"]["containers"][0]["env"]}
                self.assertEqual(env["RUSTFS_IDENTITY_OPENID_CLIENT_ID_pmh_codes"]["value"], declaration["clientID"])
                self.assertEqual(env["RUSTFS_IDENTITY_OPENID_REDIRECT_URI_pmh_codes"]["value"], declaration["redirectURI"])
                self.assertEqual(env["RUSTFS_IDENTITY_OPENID_GROUPS_CLAIM_pmh_codes"]["value"], "rustfs_policy")
                self.assertEqual(env["RUSTFS_IDENTITY_OPENID_CLIENT_SECRET_pmh_codes"]["valueFrom"]["secretKeyRef"]["name"], "rustfs-oidc")
                self.assertFalse(any("ROLE_POLICY" in name for name in env))
                self.assertIn("if request.user.is_superuser else []", declaration["extraScopeMappings"][0]["expression"])
                self.assertEqual(declaration["readerPaths"], ["minio/minio-secrets", "minio/rustfs-oidc"])
                continue
            if slug == "welplan":
                doc = yaml.safe_load((ROOT / "welplan/deployment.yml").read_text())
                env = {e["name"]: e.get("value") for e in doc["spec"]["template"]["spec"]["containers"][0]["env"]}
                self.assertEqual(env["ADMIN_OIDC_CLIENT_ID"], declaration["clientID"])
                self.assertEqual(declaration["redirectURI"], "https://welplan.pmh.codes/admin/callback")
                continue
            if slug == "tailscale":
                self.assertEqual(declaration["clientID"], "lab-tailscale")
                self.assertEqual(declaration["redirectURI"], "https://login.tailscale.com/a/oauth_response")
                self.assertEqual(declaration["vaultPath"], "tailscale/tailscale-oidc")
                self.assertNotEqual(declaration["vaultPath"], "tailscale/operator-oauth")
                continue
            if slug == "track":
                doc = next(yaml.safe_load_all((ROOT / "track/deployment.yml").read_text()))
                env = {e["name"]: e.get("value") for e in doc["spec"]["template"]["spec"]["containers"][0]["env"]}
                self.assertEqual(env["OIDC_CLIENT_ID"], declaration["clientID"])
                self.assertEqual(env["OIDC_REDIRECT_URI"], declaration["redirectURI"])
                continue
            if slug == "mail":
                self.assertEqual(declaration["clientID"], "lab-mail")
                self.assertEqual(declaration["redirectURI"], "https://mail.pmh.codes/api/auth/callback/oidc")
                self.assertEqual(declaration["readerPaths"], ["mail/mailui-secret", "mail/mail-oidc"])
                continue
            if slug == "immich":
                desired = json.loads((ROOT / "immich/bootstrap.json").read_text())
                self.assertEqual(declaration["clientID"], desired["oauth"]["clientId"])
                self.assertEqual([declaration["redirectURI"], *declaration["additionalRedirectURIs"]], desired["oauth"]["redirectURIs"])
                continue
            if slug == "seafile":
                self.assertEqual(declaration["clientID"], "lab-seafile")
                self.assertEqual(declaration["redirectURI"], "https://drive.pmh.codes/oauth/callback/")
                continue
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
            if slug in {"stmt", "connect", "books"}:
                filename = "backend.yml" if slug == "books" else "deployment.yml"
                docs = list(yaml.safe_load_all((ROOT / slug / filename).read_text()))
                env = docs[0]["spec"]["template"]["spec"]["containers"][0]["env"]
                actual = next(e["value"] for e in env if e["name"] == "OIDC_CLIENT_ID")
                self.assertEqual(actual, declaration["clientID"])
                redirect = f"https://{slug}.pmh.codes/" + ("oidc/callback" if slug == "connect" else "auth/callback")
                self.assertEqual(declaration["redirectURI"], redirect)
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

    def test_rustfs_claim_never_grants_admin_to_ordinary_users(self):
        expression = DECLARATIONS["rustfs"]["extraScopeMappings"][0]["expression"]
        for superuser in [False, True]:
            request = Mock()
            request.user.is_superuser = superuser
            claim = eval(expression.removeprefix("return "), {"request": request})
            self.assertEqual(claim, {"rustfs_policy": ["consoleAdmin"] if superuser else []})

    def test_custom_scope_drift_is_not_silently_overwritten(self):
        desired = DECLARATIONS["rustfs"]
        api, vault = Mock(), Mock()
        vault.get.return_value = {"client-secret": "x" * 64}
        mapping = dict(desired["extraScopeMappings"][0], pk="mapping-id", expression="return {\"rustfs_policy\": [\"consoleAdmin\"]}")
        api.list.side_effect = [[], [mapping]]
        with self.assertRaisesRegex(RuntimeError, "refusing privilege changes"):
            provision_client(vault, api, "rustfs", desired)
        api.request.assert_not_called()

    def test_existing_immich_client_preserves_all_strict_web_and_mobile_callbacks(self):
        desired = DECLARATIONS["immich"]
        secret = "fresh-immich-placeholder-" * 3
        redirects = [{"matching_mode": "strict", "url": uri, "redirect_uri_type": "authorization"} for uri in [desired["redirectURI"], *desired["additionalRedirectURIs"]]]
        provider = {"pk": 45, "name": "lab bootstrap: immich", "client_id": desired["clientID"], "client_type": "confidential", "client_secret": secret, "issuer_mode": "per_provider", "redirect_uris": redirects}
        api, vault = Mock(), Mock()
        api.list.return_value = [provider]
        api.request.return_value = {"provider": 45}
        vault.get.return_value = {"client-secret": secret}
        discovery = {"issuer": "https://auth.pmh.codes/application/o/immich/"}
        with patch("oidc.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(discovery).encode())):
            provision_client(vault, api, "immich", desired)
        vault.create.assert_not_called()
        self.assertEqual(len(redirects), 3)
        self.assertIn('app.immich:///oauth-callback', [r["url"] for r in redirects])
        policy = next(call.kwargs["payload"] for call in vault.run.call_args_list if call.args[:2] == ("policy", "write"))
        for path in desired["readerPaths"]:
            self.assertIn(path, policy)

    def test_unrelated_existing_provider_is_not_taken_over(self):
        api, vault = Mock(), Mock()
        api.list.return_value = [{"client_id": DECLARATIONS["go"]["clientID"], "name": "user-managed"}]
        vault.get.return_value = None
        with self.assertRaises(RuntimeError):
            provision_client(vault, api, "go", DECLARATIONS["go"])
        vault.create.assert_not_called()
        api.request.assert_not_called()

    def test_connect_companion_tokens_are_preserved(self):
        desired = DECLARATIONS["connect"]
        fields = {k: "fresh-placeholder-" * 5 for k in ["OIDC_CLIENT_SECRET", *desired["companionSecretFields"]]}
        provider = {"pk": 44, "name": "lab bootstrap: connect", "client_id": desired["clientID"],
                    "client_secret": fields["OIDC_CLIENT_SECRET"], "issuer_mode": "per_provider", "redirect_uris": [
                        {"matching_mode": "strict", "url": desired["redirectURI"], "redirect_uri_type": "authorization"}]}
        api, vault = Mock(), Mock()
        api.list.return_value = [provider]
        api.request.return_value = {"provider": 44}
        vault.get.return_value = fields.copy()
        discovery = {"issuer": "https://auth.pmh.codes/application/o/connect/"}
        with patch("oidc.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(discovery).encode())):
            provision_client(vault, api, "connect", desired)
        vault.create.assert_not_called()
        self.assertEqual(vault.get.return_value, fields)

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
